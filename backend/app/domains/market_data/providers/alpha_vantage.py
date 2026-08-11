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
        """
        if not isinstance(payload, dict):
            raise ProviderBadResponse(self.name, "response was not a JSON object")
        if "Note" in payload or "Information" in payload:
            raise ProviderRateLimited(self.name, "call frequency limit reached")
        if "Error Message" in payload:
            raise ProviderBadResponse(self.name, str(payload["Error Message"])[:160])
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
