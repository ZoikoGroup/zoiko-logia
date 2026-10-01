"""Index levels for the benchmark indices the product is asked about.

S&P 500, FTSE 100, S&P/TSX Composite, S&P/ASX 200, ISEQ All Share, DAX,
Euronext 100, Nikkei 225, NIFTY 50, SENSEX and the SSE Composite. None of
the key-gated market providers below serve index levels: Finnhub's stock quote
endpoint returns every field zeroed for an index, its candle endpoint needs a
paid tier, Alpha Vantage's GLOBAL_QUOTE and TIME_SERIES_DAILY return "Invalid
API call" for ^-symbols, and Polygon route here via the shared quote endpoint
which carries no index series. All were verified live before this provider
was written, so the old failure mode was not "no source exists" but "the
industry's free tiers do not sell indices through stock endpoints".

This adapter therefore uses Yahoo Finance's public chart endpoint, which is
free, keyless and serves all the above (and a closed set of benchmarks beyond
them — see identity.resolve_index()). It is deliberately a MARKET quote path
only:

  - it refuses any symbol that does not start with "^" — with the one
    exception of the SSE Composite, which Yahoo stopped serving under its
    caret symbol (^SSEC is HTTP 404) and now serves only as the caret-less
    code 000001.SS — so a stray ordinary-stock ticker can never be picked up;
  - it is last-resort/only-listed for INTENT_INDEX in registry.py, never for
    INTENT_QUOTE on companies;
  - freshness is labelled delayed, never realtime, because the chart API does
    not state its entitlement and claiming realtime on a delayed feed would be
    the unverifiable assertion this product exists to avoid.

The endpoint itself is parsed in yahoo_chart.py, which yahoo_equity.py shares:
one parser for one payload, so the two adapters cannot drift into disagreeing
about what Yahoo said.
"""
from __future__ import annotations

import httpx

from app.domains.market_data.http import make_client
from app.domains.market_data.providers.base import (
    CAP_HISTORY,
    CAP_QUOTE,
    BaseStockProvider,
)
from app.domains.market_data.providers.yahoo_chart import (
    bars_from_chart,
    fetch_chart,
    quote_from_meta,
)
from app.domains.market_data.schemas import (
    EntityRef,
    OHLCVBar,
    ProviderBadResponse,
    StockQuote,
)

_YAHOO_BASE_DEFAULT = "https://query1.finance.yahoo.com/v8/finance"


class IndexQuoteProvider(BaseStockProvider):
    name = "index_quote"
    CAPABILITIES = frozenset({CAP_QUOTE, CAP_HISTORY})
    BASE_URL_ENV = "YAHOO_INDEX_API_BASE_URL"
    DEFAULT_BASE_URL = _YAHOO_BASE_DEFAULT

    def configured(self) -> bool:
        # Keyless by design — see module docstring. Always enabled, so the
        # registry picks it up for INTENT_INDEX without an operator having to
        # do anything, while the ticker guard below keeps it off every other
        # intent.
        return True

    async def _probe(self, client: httpx.AsyncClient) -> None:
        # One fixed index, small range — an availability probe, not a data call.
        await self._chart(client, "^GSPC", "5d")

    async def _chart(self, client: httpx.AsyncClient, symbol: str, span: str) -> dict:
        # The SSE Composite lost its caret symbol on Yahoo (^SSEC = HTTP 404) and
        # is now served only as 000001.SS. That single caret-less code is allowed
        # through; anything else without a "^" is not an index and is refused.
        if not symbol.startswith("^") and symbol != "000001.SS":
            raise ProviderBadResponse(self.name, f"{symbol} is not an index; refusing")
        return await fetch_chart(client, self.name, self.base_url(), symbol, span=span)

    async def get_quote(self, client: httpx.AsyncClient, ref: EntityRef) -> StockQuote:
        payload = await self._chart(client, ref.ticker, "5d")
        return quote_from_meta(payload.get("meta") or {}, self.name, ref)

    async def get_history(
        self, client: httpx.AsyncClient, ref: EntityRef, *, interval: str = "1d", limit: int = 30
    ) -> list[OHLCVBar]:
        # "max" is deliberate for an index: the caller has already coarsened the
        # interval to fit the span it asked for, and an index's full history is
        # cheap to return and impossible to re-fetch later.
        payload = await self._chart(client, ref.ticker, "max")
        return bars_from_chart(payload, ref.ticker, self.name, interval=interval, limit=limit)


async def probe_index_quote() -> bool:
    """Startup/health helper: is the keyless index endpoint reachable?

    Used by the orchestration layer's own health reporting; never raises."""
    try:
        async with make_client(timeout=5.0) as client:
            await IndexQuoteProvider()._probe(client)
        return True
    except Exception:  # noqa: BLE001 — a connectivity probe must never raise
        return False