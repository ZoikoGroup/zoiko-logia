"""Twelve Data — global quotes, price history, company profiles, fundamentals
and symbol search, from a single provider.

REST only in this adapter. Twelve Data also offers a WebSocket feed at
wss://ws.twelvedata.com for continuous price updates; that is deliberately not
implemented here, because a stream does not fit the request/response answer
pipeline this adapter feeds — see the market_data package docstring and the
streaming note in app/orchestration/market_data.py.

Freshness is reported as delayed rather than realtime: the free tier is roughly
15 minutes behind, and whether a key is entitled to realtime depends on the
account's plan, which the quote response does not state. Claiming realtime on a
delayed feed would be exactly the kind of unverifiable assertion this product
exists to avoid, so the conservative label is used unless an operator overrides
it with TWELVE_DATA_REALTIME.

Twelve Data signals many failures — bad symbol, exhausted plan credits — as an
HTTP 200 with {"status": "error", "code": …} rather than an HTTP error status,
so the body is inspected explicitly and mapped onto the typed errors http.py
already raises for real HTTP statuses.

Docs: https://twelvedata.com/docs
"""
from __future__ import annotations

import os
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
    FRESHNESS_REALTIME,
    CompanyProfile,
    EntityRef,
    FinancialMetric,
    OHLCVBar,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderRateLimited,
    StockQuote,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _raise_on_error_body(name: str, payload: Any) -> dict:
    """Twelve Data answers 200 with {"status":"error","code":…} for a bad symbol
    or an exhausted plan. Map that onto the typed errors the registry routes on,
    so an out-of-credits key backs off (429) and a bad symbol stops (bad
    response) rather than both looking like a generic failure."""
    if not isinstance(payload, dict):
        raise ProviderBadResponse(name, "response body was not an object")
    if payload.get("status") == "error":
        code = payload.get("code")
        message = str(payload.get("message") or "request rejected")
        if code == 429:
            raise ProviderRateLimited(name, message)
        if code in (401, 403):
            raise ProviderAuthError(name, message)
        raise ProviderBadResponse(name, message)
    return payload


class TwelveDataProvider(BaseStockProvider):
    name = "twelve_data"
    CAPABILITIES = frozenset({CAP_QUOTE, CAP_HISTORY, CAP_PROFILE, CAP_FUNDAMENTALS, CAP_SEARCH})
    API_KEY_ENV = "TWELVE_DATA_API_KEY"
    BASE_URL_ENV = "TWELVE_DATA_API_BASE_URL"
    DEFAULT_BASE_URL = "https://api.twelvedata.com"

    def auth_headers(self) -> dict[str, str]:
        # Header rather than the ?apikey= query param, so the key cannot end up
        # in an access log or a redirect chain.
        return {"Authorization": f"apikey {self.require_configured()}"}

    def freshness(self) -> str:
        """Operator-declared entitlement. The API cannot tell us, so this is
        config, and it defaults to the conservative answer."""
        return (
            FRESHNESS_REALTIME
            if os.getenv("TWELVE_DATA_REALTIME", "").lower() in {"1", "true", "yes"}
            else FRESHNESS_DELAYED
        )

    async def _probe(self, client: httpx.AsyncClient) -> None:
        payload = await request_json(
            client, self.name, f"{self.base_url()}/quote",
            params={"symbol": "AAPL"}, headers=self.auth_headers(), retries=0,
        )
        _raise_on_error_body(self.name, payload)

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int = 5) -> list[EntityRef]:
        payload = await request_json(
            client, self.name, f"{self.base_url()}/symbol_search",
            params={"symbol": query, "outputsize": limit}, headers=self.auth_headers(),
        )
        results = (payload or {}).get("data") if isinstance(payload, dict) else None
        return [
            EntityRef(
                name=str(item.get("instrument_name", "")).strip(),
                ticker=str(item.get("symbol", "")).strip(),
                exchange=str(item.get("exchange", "")).strip(),
                country=str(item.get("country", "")).strip(),
            )
            for item in (results or [])[:limit]
            if item.get("symbol")
        ]

    async def get_quote(self, client: httpx.AsyncClient, ref: EntityRef) -> StockQuote:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for a quote")

        payload = _raise_on_error_body(
            self.name,
            await request_json(
                client, self.name, f"{self.base_url()}/quote",
                params={"symbol": ref.ticker}, headers=self.auth_headers(),
            ),
        )
        price = as_float(payload.get("close"))
        if price is None or price == 0:
            raise ProviderBadResponse(self.name, f"no quote data for {ref.ticker}")

        timestamp = as_float(payload.get("timestamp"))
        is_open = payload.get("is_market_open")
        return StockQuote(
            symbol=ref.ticker,
            price=price,
            provider=self.name,
            freshness=self.freshness(),
            fetched_at=_now_iso(),
            company_name=str(payload.get("name") or ref.name or ""),
            exchange=str(payload.get("exchange", "")),
            currency=str(payload.get("currency", "")),
            change=as_float(payload.get("change")),
            change_percent=as_float(payload.get("percent_change")),
            open=as_float(payload.get("open")),
            high=as_float(payload.get("high")),
            low=as_float(payload.get("low")),
            previous_close=as_float(payload.get("previous_close")),
            volume=as_float(payload.get("volume")),
            provider_timestamp=(
                datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds") if timestamp else ""
            ),
            market_status=("open" if is_open is True else "closed" if is_open is False else ""),
            source_url=f"https://twelvedata.com/stocks/{ref.ticker.lower()}",
        )

    async def get_history(
        self, client: httpx.AsyncClient, ref: EntityRef, *, interval: str = "1day", limit: int = 30
    ) -> list[OHLCVBar]:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for price history")

        payload = _raise_on_error_body(
            self.name,
            await request_json(
                client, self.name, f"{self.base_url()}/time_series",
                params={"symbol": ref.ticker, "interval": interval or "1day", "outputsize": max(1, min(limit, 400))},
                headers=self.auth_headers(),
            ),
        )
        values = payload.get("values")
        if not isinstance(values, list) or not values:
            raise ProviderBadResponse(self.name, f"no price history for {ref.ticker}")

        meta = payload.get("meta") or {}
        currency = str(meta.get("currency", ""))
        exchange = str(meta.get("exchange", ""))
        # Twelve Data returns newest-first; the pipeline expects oldest→newest so
        # bars[0] is the start of the window and bars[-1] the latest.
        bars: list[OHLCVBar] = []
        for row in reversed(values):
            close = as_float(row.get("close"))
            if close is None:
                continue
            bars.append(
                OHLCVBar(
                    symbol=ref.ticker,
                    timestamp=str(row.get("datetime", "")),
                    open=as_float(row.get("open")) or 0.0,
                    high=as_float(row.get("high")) or 0.0,
                    low=as_float(row.get("low")) or 0.0,
                    close=close,
                    provider=self.name,
                    volume=as_float(row.get("volume")),
                    interval=interval or "1day",
                    currency=currency,
                    exchange=exchange,
                )
            )
        if not bars:
            raise ProviderBadResponse(self.name, f"no usable price history for {ref.ticker}")
        return bars

    async def get_company_profile(self, client: httpx.AsyncClient, ref: EntityRef) -> CompanyProfile:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for a company profile")

        payload = _raise_on_error_body(
            self.name,
            await request_json(
                client, self.name, f"{self.base_url()}/profile",
                params={"symbol": ref.ticker}, headers=self.auth_headers(),
            ),
        )
        if not payload.get("name"):
            raise ProviderBadResponse(self.name, f"no company profile for {ref.ticker}")

        return CompanyProfile(
            company_name=str(payload.get("name", "")),
            provider=self.name,
            symbol=ref.ticker,
            exchange=str(payload.get("exchange", "")),
            country=str(payload.get("country", "")),
            currency=str(payload.get("currency", "")),
            industry=str(payload.get("industry", "")),
            sector=str(payload.get("sector", "")),
            website=str(payload.get("website", "")),
            identifiers={"ticker": ref.ticker, "type": str(payload.get("type", ""))},
            source_url=str(payload.get("website", "")) or f"https://twelvedata.com/stocks/{ref.ticker.lower()}",
        )

    async def get_fundamentals(self, client: httpx.AsyncClient, ref: EntityRef) -> list[FinancialMetric]:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for fundamentals")

        payload = _raise_on_error_body(
            self.name,
            await request_json(
                client, self.name, f"{self.base_url()}/statistics",
                params={"symbol": ref.ticker}, headers=self.auth_headers(),
            ),
        )
        stats = payload.get("statistics") or {}
        valuation = stats.get("valuations_metrics") or {}
        financials = stats.get("financials") or {}
        profitability = (financials.get("profitability") or {}) if isinstance(financials, dict) else {}
        income = (financials.get("income_statement") or {}) if isinstance(financials, dict) else {}

        # A curated subset — the full payload is dozens of ratios, and dumping
        # all of them into an answer prompt buries the figure the user asked for.
        wanted: list[tuple[dict, str, str, str]] = [
            (valuation, "market_capitalization", "Market capitalisation", "USD"),
            (valuation, "trailing_pe", "P/E ratio (trailing)", "ratio"),
            (valuation, "forward_pe", "P/E ratio (forward)", "ratio"),
            (valuation, "price_to_sales_ttm", "Price / sales (TTM)", "ratio"),
            (valuation, "price_to_book_mrq", "Price / book (MRQ)", "ratio"),
            (profitability, "profit_margin", "Profit margin", "%"),
            (profitability, "operating_margin", "Operating margin", "%"),
            (income, "revenue_ttm", "Revenue (TTM)", "USD"),
            (income, "gross_profit_ttm", "Gross profit (TTM)", "USD"),
        ]
        out: list[FinancialMetric] = []
        for source, key, label, unit in wanted:
            value = as_float(source.get(key)) if isinstance(source, dict) else None
            if value is None:
                continue
            # Twelve Data reports margins as fractions (0.25), not percents.
            if unit == "%" and abs(value) <= 1:
                value *= 100
            out.append(
                FinancialMetric(
                    metric=label,
                    value=value,
                    provider=self.name,
                    symbol=ref.ticker,
                    company=ref.name,
                    unit=unit,
                    period="TTM" if "ttm" in key else "latest",
                    source_url=f"https://twelvedata.com/stocks/{ref.ticker.lower()}",
                )
            )
        if not out:
            raise ProviderBadResponse(self.name, f"no usable fundamentals for {ref.ticker}")
        return out
