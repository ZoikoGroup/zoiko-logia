"""Alpha Vantage — global quotes, OHLCV history, company overview and statements.

REST only, deliberately: Alpha Vantage's documented stock API is REST, and there
is no WebSocket product to integrate. Nothing here should be extended into a
streaming implementation.

Two provider-specific traps this adapter has to handle, both of which produce
silently wrong answers if ignored:

  1. Throttling arrives as HTTP 200. When the daily cap is hit the body is
     `{"Note": "...call frequency..."}` or `{"Information": "..."}` with a
     success status, so naive code reads it as an empty result and reports "no
     data" instead of "rate limited". _check_envelope() converts it to a real
     ProviderRateLimited so the registry can fall back.
  2. The free tier is roughly 25 requests per day. That is a demo allowance,
     not a production one, which is why the registry ranks this provider last
     for every intent — it is a fallback, not a primary.

Docs: https://www.alphavantage.co/documentation/
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.domains.market_data.http import as_float, request_json
from app.domains.market_data.providers.base import (
    CAP_FUNDAMENTALS,
    CAP_HISTORY,
    CAP_PROFILE,
    CAP_QUOTE,
    CAP_SEARCH,
    BaseStockProvider,
)
from app.domains.market_data.schemas import (
    FRESHNESS_DELAYED,
    FRESHNESS_HISTORICAL,
    CompanyProfile,
    EntityRef,
    FinancialMetric,
    OHLCVBar,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderRateLimited,
    StockQuote,
)

_SERIES_FUNCTION = {
    "1d": ("TIME_SERIES_DAILY", "Time Series (Daily)"),
    "1w": ("TIME_SERIES_WEEKLY", "Weekly Time Series"),
    "1mo": ("TIME_SERIES_MONTHLY", "Monthly Time Series"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_INVALID_KEY_MARKERS = (
    "apikey is invalid",
    "api key is invalid",
    "invalid api key",
    "invalid apikey",
    "apikey is invalid or missing",
    "api key is missing",
)

# Alpha Vantage never answers an authentication failure with a non-200 status.
# Measured live on 2026-09-30, across TIME_SERIES_DAILY / GLOBAL_QUOTE / OVERVIEW
# and with the configured key plus two invalid controls:
#
#   configured key, quota available -> {"Meta Data", "Time Series (Daily)"}
#   configured key, daily cap hit    -> {"Information": "We have detected your API
#                                       key as <KEY> and our standard API rate limit
#                                       is 25 requests per day..."}
#   key the provider does not know   -> {"Information": "We have detected your API
#                                       key as <KEY> and our standard API rate limit
#                                       is 25 requests per day..."}
#   key mid-request-rate             -> {"Information": "...spread out your free API
#                                       requests... (1 request per second)"}
#   empty key                        -> {"Error Message": "the parameter apikey is
#                                       invalid or missing..."}
#
# Rows 2 and 3 are the same body. A key the provider does not recognise and a key
# whose 25-request daily allowance is spent are NOT distinguishable from the
# error path. An earlier revision of this file treated the
# "We have detected your API key as" opener as proof of an unrecognised key and
# raised ProviderAuthError; that misclassifies a working key that has simply run
# out of daily quota, and would report a valid credential as rejected. The
# provider cannot support the distinction, so neither can this adapter.
#
# What is established, and it is not "the endpoint responded":
#   - the configured key is VALID, because it returns a full
#     "Time Series (Daily)" dataset that neither invalid control returns;
#   - the empty key is an authentication failure ("Error Message" wording), and
#     that is the only body that means anything other than "try later";
#   - the ambiguous 200-with-prose body means the quota is spent or the key is
#     unknown, and the honest classification is the retryable one.
#
# SECRETS: row 2 and row 3 both embed the caller's own API key in the message.
# The text is therefore only ever tested, never propagated. This audit saw that
# payload render a live key to a terminal, so the guard is pinned by a test.
_REDACTED = "<redacted>"


class AlphaVantageProvider(BaseStockProvider):
    name = "alpha_vantage"
    CAPABILITIES = frozenset({CAP_QUOTE, CAP_HISTORY, CAP_PROFILE, CAP_FUNDAMENTALS, CAP_SEARCH})
    API_KEY_ENV = "ALPHA_VANTAGE_API_KEY"
    BASE_URL_ENV = "ALPHA_VANTAGE_API_BASE_URL"
    DEFAULT_BASE_URL = "https://www.alphavantage.co"

    def _params(self, **extra: Any) -> dict[str, Any]:
        # Alpha Vantage only accepts the key as a query parameter; there is no
        # header form. http.py redacts `apikey` from every log line it emits.
        return {"apikey": self.require_configured(), **extra}

    def _check_envelope(self, payload: Any) -> dict[str, Any]:
        """Turn Alpha Vantage's 200-with-an-error-body into a typed error.

        Without this the throttle message is indistinguishable from an empty
        result, and the pipeline reports "no data available" for a company that
        has plenty — the failure mode is a confidently wrong answer.

        A third shape has to be separated as well: a rejected or missing key also
        arrives as HTTP 200 with `{"Error Message": "the parameter apikey is
        invalid or missing..."}`. That is an AUTHENTICATION failure, not a
        missing company, and folding it into ProviderBadResponse made a
        misconfigured key read as "that ticker does not exist". ProviderBadResponse
        also stops the fallback chain in service.fetch_for_intent (the provider
        answered, so trying the next one could only guess at a different
        company), which is the wrong response to a bad credential.
        A fourth shape must be separated, and it is the subtle one. A key whose
        daily allowance is spent, and a key the provider does not recognise, both
        arrive as HTTP 200 with
        `{"Information": "We have detected your API key as <KEY> and our standard
        API rate limit is 25 requests per day..."}`. The provider does not
        distinguish those two cases, so this adapter cannot either: both are
        reported as ProviderRateLimited, the conservative reading, because it is
        the one that does not tell an operator their key is broken. Only the
        unambiguous "Error Message: the parameter apikey is invalid or missing"
        body - an empty or absent key - is raised as an authentication failure.

        An earlier revision keyed on the "We have detected your API key as"
        opener and raised ProviderAuthError there. That was wrong: it reported a
        valid key with a spent daily quota as a rejected credential. The
        echoed key is never copied into any exception message either way.
        """
        if not isinstance(payload, dict):
            raise ProviderBadResponse(self.name, "response was not a JSON object")
        if "Note" in payload or "Information" in payload:
            # Tested, never propagated: this body carries the caller's own key.
            raise ProviderRateLimited(self.name, "call frequency limit reached")
        if "Error Message" in payload:
            message = str(payload["Error Message"])
            lowered = message.lower()
            if any(marker in lowered for marker in _INVALID_KEY_MARKERS):
                raise ProviderAuthError(self.name, "API key rejected or missing")
            raise ProviderBadResponse(self.name, message[:160])
        return payload

    async def _get(self, client: httpx.AsyncClient, **params: Any) -> dict[str, Any]:
        payload = await request_json(client, self.name, f"{self.base_url()}/query", params=self._params(**params))
        return self._check_envelope(payload)

    async def _probe(self, client: httpx.AsyncClient) -> None:
        await self._get(client, function="GLOBAL_QUOTE", symbol="AAPL")

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int = 5) -> list[EntityRef]:
        payload = await self._get(client, function="SYMBOL_SEARCH", keywords=query)
        matches = payload.get("bestMatches") or []
        return [
            EntityRef(
                name=str(m.get("2. name", "")).strip(),
                ticker=str(m.get("1. symbol", "")).strip(),
                country=str(m.get("4. region", "")).strip(),
            )
            for m in matches[:limit]
            if m.get("1. symbol")
        ]

    async def get_quote(self, client: httpx.AsyncClient, ref: EntityRef) -> StockQuote:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for a quote")

        payload = await self._get(client, function="GLOBAL_QUOTE", symbol=ref.ticker)
        quote = payload.get("Global Quote") or {}
        price = as_float(quote.get("05. price"))
        if price is None:
            raise ProviderBadResponse(self.name, f"no quote data for {ref.ticker}")

        percent = str(quote.get("10. change percent", "")).rstrip("%")
        return StockQuote(
            symbol=ref.ticker,
            price=price,
            provider=self.name,
            # Alpha Vantage's stock quotes are end-of-day / delayed on all
            # commonly-held plans; never labelled realtime.
            freshness=FRESHNESS_DELAYED,
            fetched_at=_now_iso(),
            company_name=ref.name,
            open=as_float(quote.get("02. open")),
            high=as_float(quote.get("03. high")),
            low=as_float(quote.get("04. low")),
            previous_close=as_float(quote.get("08. previous close")),
            volume=as_float(quote.get("06. volume")),
            change=as_float(quote.get("09. change")),
            change_percent=as_float(percent),
            provider_timestamp=str(quote.get("07. latest trading day", "")),
            source_url=f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ref.ticker}",
        )

    async def get_history(
        self, client: httpx.AsyncClient, ref: EntityRef, *, interval: str = "1d", limit: int = 30
    ) -> list[OHLCVBar]:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for history")

        function, series_key = _SERIES_FUNCTION.get(interval, _SERIES_FUNCTION["1d"])
        payload = await self._get(client, function=function, symbol=ref.ticker, outputsize="compact")
        series = payload.get(series_key) or {}
        if not series:
            raise ProviderBadResponse(self.name, f"no historical series for {ref.ticker}")

        bars: list[OHLCVBar] = []
        for day in sorted(series.keys())[-limit:]:
            row = series[day] or {}
            close = as_float(row.get("4. close"))
            if close is None:
                continue
            bars.append(
                OHLCVBar(
                    symbol=ref.ticker,
                    timestamp=day,
                    open=as_float(row.get("1. open")) or close,
                    high=as_float(row.get("2. high")) or close,
                    low=as_float(row.get("3. low")) or close,
                    close=close,
                    volume=as_float(row.get("5. volume")),
                    provider=self.name,
                    interval=interval,
                )
            )
        if not bars:
            raise ProviderBadResponse(self.name, f"historical series for {ref.ticker} had no usable closes")
        return bars

    async def get_company_profile(self, client: httpx.AsyncClient, ref: EntityRef) -> CompanyProfile:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for a company profile")

        payload = await self._get(client, function="OVERVIEW", symbol=ref.ticker)
        if not payload.get("Name"):
            raise ProviderBadResponse(self.name, f"no company overview for {ref.ticker}")

        return CompanyProfile(
            company_name=str(payload.get("Name", "")),
            provider=self.name,
            symbol=ref.ticker,
            exchange=str(payload.get("Exchange", "")),
            country=str(payload.get("Country", "")),
            currency=str(payload.get("Currency", "")),
            industry=str(payload.get("Industry", "")),
            sector=str(payload.get("Sector", "")),
            market_cap=as_float(payload.get("MarketCapitalization")),
            identifiers={"ticker": ref.ticker, "cik": str(payload.get("CIK", ""))},
            source_url=f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ref.ticker}",
        )

    async def get_fundamentals(self, client: httpx.AsyncClient, ref: EntityRef) -> list[FinancialMetric]:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for fundamentals")

        payload = await self._get(client, function="OVERVIEW", symbol=ref.ticker)
        if not payload.get("Name"):
            raise ProviderBadResponse(self.name, f"no fundamentals for {ref.ticker}")

        currency = str(payload.get("Currency", ""))
        company = str(payload.get("Name", ""))
        wanted = {
            "MarketCapitalization": ("Market capitalisation", currency),
            "RevenueTTM": ("Revenue (TTM)", currency),
            "GrossProfitTTM": ("Gross profit (TTM)", currency),
            "EBITDA": ("EBITDA", currency),
            "EPS": ("EPS", "per share"),
            "PERatio": ("P/E ratio", "ratio"),
            "ProfitMargin": ("Profit margin", "ratio"),
            "ReturnOnEquityTTM": ("Return on equity (TTM)", "ratio"),
            "DividendYield": ("Dividend yield", "ratio"),
        }
        out: list[FinancialMetric] = []
        for key, (label, unit) in wanted.items():
            value = as_float(payload.get(key))
            if value is None:
                continue
            out.append(
                FinancialMetric(
                    metric=label,
                    value=value,
                    provider=self.name,
                    symbol=ref.ticker,
                    company=company,
                    unit=unit,
                    period="TTM" if "TTM" in key else "latest reported",
                    fiscal_period=str(payload.get("LatestQuarter", "")),
                    currency=currency,
                    source_url=f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ref.ticker}",
                )
            )
        if not out:
            raise ProviderBadResponse(self.name, f"no usable fundamentals for {ref.ticker}")
        return out


FRESHNESS_DEFAULT = FRESHNESS_HISTORICAL
