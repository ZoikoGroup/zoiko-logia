"""Listed-equity quotes, history and name lookup, from Yahoo's keyless chart.

Why this exists: the key-gated providers in this directory are all US-shaped.
Verified live before this adapter was written —

  - Finnhub answers a local listing with HTTP 403 (its free tier covers US
    equities and US-listed ADRs only), so 7203.T, 6758.T, SIE.DE, MC.PA,
    TTE.PA, 0700.HK and 600519.SS all failed;
  - Polygon answers a foreign symbol with an error document the adapter
    classifies as a bad response, which STOPS the fallback chain rather than
    continuing to the next provider, so one unusable provider ended the search;
  - Alpha Vantage's free tier is ~25 calls a day and its fundamentals coverage
    outside the US is thin.

Yahoo's chart endpoint serves all of those, keylessly, and also serves its own
search endpoint, which is what makes "Siemens share price" — a question with no
ticker in it — resolvable at all.

What this provider will NOT do, stated up front because each is a way this
endpoint will happily return a confident wrong answer:

  - It accepts equities only. Caret symbols belong to index_quote, and the "="
    in EURUSD=X / BTC-USD marks a currency pair or a coin, neither of which is a
    share. Those are refused before any request is made, so a stray symbol
    cannot become someone else's price.
  - Search results are only returned when every word of the search term appears
    in the returned company's name. Yahoo's ranking is a relevance score, not an
    identity: a search for "Siemens" also returns Siemens Energy, and for
    "Total" it returns dozens of unrelated issuers. Failing closed here is what
    stops a stranger's fundamentals being attached to the question.
  - Freshness is `delayed`, always. The endpoint publishes no entitlement, and
    the delay it does report (exchangeDataDelayedBy) is carried into the quote's
    market status rather than dropped.

Docs: https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
      https://query1.finance.yahoo.com/v1/finance/search?q={query}
"""
from __future__ import annotations

import os
import re

import httpx

from app.domains.market_data.providers.base import (
    CAP_HISTORY,
    CAP_QUOTE,
    CAP_SEARCH,
    BaseStockProvider,
)
from app.domains.market_data.providers.yahoo_chart import (
    HEADERS,
    INTERVAL_TO_YAHOO,
    bars_from_chart,
    fetch_chart,
    quote_from_meta,
)
from app.domains.market_data.schemas import (
    CapabilityNotSupported,
    EntityRef,
    OHLCVBar,
    ProviderBadResponse,
    StockQuote,
)
from app.domains.market_data.http import request_json

_YAHOO_BASE_DEFAULT = "https://query1.finance.yahoo.com"
_CHART_BASE = f"{_YAHOO_BASE_DEFAULT}/v8/finance"
_SEARCH_PATH = "/v1/finance/search"

# A symbol Yahoo would serve: letters, digits, dots and dashes, with at least one
# letter. This admits both plain US tickers (AAPL) and suffixed local listings
# (7203.T, BARC.L, 0700.HK, 600519.SS).
_EQUITY_SYMBOL = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9.\-]{1,20}$")

# The exchanges this product serves, keyed by Yahoo's `exchange` CODE (search
# results also carry a human `exchDisp` like "XETRA" or "Paris", which is a
# label, not an identifier). Only codes that unambiguously identify one country
# are here; anything else leaves EntityRef.country empty rather than guessing,
# because a wrong country on a resolved entity is the same defect this whole
# module is written to avoid.
#
# Verified live, and the list is short on purpose. Notably absent: PNK (OTC
# Markets) and IOB (the London international orderbook) — both carry foreign
# companies' securities, so PNK is not "a US exchange" and mapping it would
# label a German listing as American. The German regional venues (MUN, STU,
# HAM, DUS, HAN) ARE mapped: every listing on them is a German listing.
_EXCHANGE_COUNTRY = {
    "NYQ": "US", "NMS": "US",          # NYSE, NASDAQ
    "LSE": "GB",                      # London
    "TOR": "CA",                      # Toronto
    "ASX": "AU",
    "GER": "DE", "FRA": "DE",         # XETRA, Frankfurt
    "MUN": "DE", "STU": "DE", "HAM": "DE", "DUS": "DE", "HAN": "DE",
    "PAR": "FR",                      # Euronext Paris
    "JPX": "JP",                      # Tokyo
    "NSI": "IN", "BSE": "IN",         # NSE, Bombay
    "HKG": "HK",
    "ISE": "IE",
}

# Equity instrument type only. Yahoo mixes equities, ETFs, indices, mutual
# funds and currencies into one ranked list, and the temptation is real: a
# search for "Shopify" returns "Harvest Shopify Enhanced High Income Shares
# ETF" alongside the company. A fund's price is not a company's share price, so
# ETFs are not returned — a question about a fund states its ticker, which
# resolves locally without any search.
_EQUITY_TYPE = "EQUITY"


class YahooEquityProvider(BaseStockProvider):
    name = "yahoo_equity"
    CAPABILITIES = frozenset({CAP_QUOTE, CAP_HISTORY, CAP_SEARCH})
    BASE_URL_ENV = "YAHOO_EQUITY_API_BASE_URL"
    DEFAULT_BASE_URL = _YAHOO_BASE_DEFAULT

    def configured(self) -> bool:
        """Opt-in, even though it needs no credential.

        The other providers in this directory are enabled by their API keys, and
        the product's contract is that an operator who has configured none of
        them gets NO market data — the answer falls back to the web-grounded
        path, which two tests assert. A keyless provider that reports itself
        configured breaks that contract silently: every company question would
        start reaching a third party the operator never chose. So this one is
        off until asked for, with YAHOO_EQUITY_ENABLED=1.

        (index_quote is enabled unconditionally, and that is not an oversight to
        be copied: index levels had NO source at all before it, so it only ever
        added capability. Company quotes already had four configured sources.)
        """
        return os.getenv("YAHOO_EQUITY_ENABLED", "").strip().lower() in {"1", "true", "yes"}

    def _check_symbol(self, symbol: str) -> str:
        """Reject anything that is not plainly a listed equity symbol.

        Runs before every request. A refusal here is a refusal to ask, which
        matters because Yahoo's search would happily answer for ^TNX or
        EURUSD=X and the caller asked about a company.
        """
        candidate = (symbol or "").strip()
        if not candidate:
            raise ProviderBadResponse(self.name, "a ticker is required for market data")
        if candidate.startswith("^"):
            raise ProviderBadResponse(self.name, f"{candidate} is an index, not an equity")
        if "=" in candidate or "-" in candidate:
            # Yahoo marks currency pairs (EURUSD=X) and crypto (BTC-USD) with
            # these; neither is a share, and both would return a plausible
            # number for a question about a company.
            raise ProviderBadResponse(self.name, f"{candidate} is not an equity symbol")
        if not _EQUITY_SYMBOL.match(candidate):
            raise ProviderBadResponse(self.name, f"{candidate} is not a usable equity symbol")
        return candidate

    async def _probe(self, client: httpx.AsyncClient) -> None:
        await fetch_chart(
            client, self.name, f"{self.base_url()}/v8/finance", "AAPL", span="5d"
        )

    async def get_quote(self, client: httpx.AsyncClient, ref: EntityRef) -> StockQuote:
        symbol = self._check_symbol(ref.ticker)
        payload = await fetch_chart(
            client, self.name, f"{self.base_url()}/v8/finance", symbol, span="5d"
        )
        return quote_from_meta(payload.get("meta") or {}, self.name, EntityRef(
            ticker=symbol, name=ref.name
        ))

    async def get_history(
        self, client: httpx.AsyncClient, ref: EntityRef, *, interval: str = "1d", limit: int = 30
    ) -> list[OHLCVBar]:
        symbol = self._check_symbol(ref.ticker)
        if interval not in INTERVAL_TO_YAHOO:
            # Intraday would need Yahoo's per-interval retention limits, which
            # are short and would silently truncate a long request. Saying "I
            # cannot do this interval" lets the registry try a provider that can.
            raise CapabilityNotSupported(self.name, f"interval {interval} is not served")
        payload = await fetch_chart(
            client, self.name, f"{self.base_url()}/v8/finance", symbol,
            interval=interval, limit=limit,
        )
        return bars_from_chart(payload, symbol, self.name, interval=interval, limit=limit)

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int = 5) -> list[EntityRef]:
        term = (query or "").strip()
        if not term:
            return []
        payload = await request_json(
            client, self.name, f"{self.base_url()}{_SEARCH_PATH}",
            params={"q": term, "quotesCount": 20, "newsCount": 0, "listsCount": 0},
            headers=HEADERS, retries=0,
        )
        quotes = (payload or {}).get("quotes") or []
        found: list[EntityRef] = []
        for item in quotes:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip()
            if not symbol or not _EQUITY_SYMBOL.match(symbol):
                continue
            if str(item.get("quoteType") or "").upper() != _EQUITY_TYPE:
                continue
            code = str(item.get("exchange") or "").strip()
            found.append(
                EntityRef(
                    # longname, never shortname: Yahoo pads shortname with
                    # listing furniture ("SIEMENS AG          N",
                    # "RYANAIR HOLDINGS PLC ORD EUR0.0") and a display name
                    # carrying that is worse than none.
                    name=str(item.get("longname") or "").strip(),
                    ticker=symbol,
                    exchange=str(item.get("exchDisp") or "").strip(),
                    country=_EXCHANGE_COUNTRY.get(code, ""),
                )
            )
        return found[:limit]
