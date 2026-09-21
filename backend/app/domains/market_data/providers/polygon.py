"""Polygon.io — US-focused snapshots, historical aggregates and ticker reference.

REST only. Polygon's WebSocket clusters need a paid plan for anything
real-time, and streaming does not fit the request/response answer pipeline this
adapter feeds, so it is out of scope here.

Freshness is the important subtlety with this provider: the free tier serves
end-of-day data only, so the previous-close endpoint is what a free key can
actually reach. This adapter therefore reports `historical` unless an operator
declares a real-time entitlement, rather than presenting yesterday's close as
today's price.

Docs: https://polygon.io/docs
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

from app.domains.market_data.http import as_float, request_json
from app.domains.market_data.providers.base import (
    CAP_HISTORY,
    CAP_PROFILE,
    CAP_QUOTE,
    CAP_SEARCH,
    BaseStockProvider,
)
from app.domains.market_data.schemas import (
    FRESHNESS_HISTORICAL,
    FRESHNESS_REALTIME,
    CompanyProfile,
    EntityRef,
    OHLCVBar,
    ProviderBadResponse,
    StockQuote,
)

_INTERVAL_TO_AGG = {
    "1d": ("1", "day"),
    "1w": ("1", "week"),
    "1mo": ("1", "month"),
    "1h": ("1", "hour"),
    "5m": ("5", "minute"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ms_to_iso(ms: float | None) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds")


class PolygonProvider(BaseStockProvider):
    name = "polygon"
    CAPABILITIES = frozenset({CAP_QUOTE, CAP_HISTORY, CAP_PROFILE, CAP_SEARCH})
    API_KEY_ENV = "POLYGON_API_KEY"
    BASE_URL_ENV = "POLYGON_API_BASE_URL"
    DEFAULT_BASE_URL = "https://api.polygon.io"

    def auth_headers(self) -> dict[str, str]:
        # Bearer header rather than ?apiKey=, keeping the key out of logs.
        return {"Authorization": f"Bearer {self.require_configured()}"}

    def freshness(self) -> str:
        return (
            FRESHNESS_REALTIME
            if os.getenv("POLYGON_REALTIME", "").lower() in {"1", "true", "yes"}
            else FRESHNESS_HISTORICAL
        )

    async def _probe(self, client: httpx.AsyncClient) -> None:
        await request_json(
            client, self.name, f"{self.base_url()}/v3/reference/tickers",
            params={"search": "AAPL", "limit": 1}, headers=self.auth_headers(), retries=0,
        )

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int = 5) -> list[EntityRef]:
        payload = await request_json(
            client, self.name, f"{self.base_url()}/v3/reference/tickers",
            params={"search": query, "active": "true", "limit": limit},
            headers=self.auth_headers(),
        )
        results = (payload or {}).get("results") or []
        return [
            EntityRef(
                name=str(item.get("name", "")).strip(),
                ticker=str(item.get("ticker", "")).strip(),
                exchange=str(item.get("primary_exchange", "")).strip(),
                country=str(item.get("locale", "")).upper(),
            )
            for item in results
            if item.get("ticker")
        ]

    async def get_quote(self, client: httpx.AsyncClient, ref: EntityRef) -> StockQuote:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for a quote")

        # prev-close is the endpoint a free key can actually reach; realtime
        # snapshots are a paid entitlement. Reporting it honestly as the
        # previous close beats presenting a stale figure as the live price.
        payload = await request_json(
            client, self.name, f"{self.base_url()}/v2/aggs/ticker/{ref.ticker}/prev",
            params={"adjusted": "true"}, headers=self.auth_headers(),
        )
        results = (payload or {}).get("results") or []
        if not results:
            raise ProviderBadResponse(self.name, f"no price data for {ref.ticker}")

        bar = results[0]
        close = as_float(bar.get("c"))
        if close is None:
            raise ProviderBadResponse(self.name, f"price data for {ref.ticker} had no close")

        open_ = as_float(bar.get("o"))
        return StockQuote(
            symbol=ref.ticker,
            price=close,
            provider=self.name,
            freshness=self.freshness(),
            fetched_at=_now_iso(),
            company_name=ref.name,
            currency="USD",
            open=open_,
            high=as_float(bar.get("h")),
            low=as_float(bar.get("l")),
            previous_close=open_,
            volume=as_float(bar.get("v")),
            change=(close - open_) if open_ is not None else None,
            change_percent=((close - open_) / open_ * 100) if open_ else None,
            provider_timestamp=_ms_to_iso(as_float(bar.get("t"))),
            market_status="previous close",
            source_url=f"https://polygon.io/quote/{ref.ticker}",
        )

    async def get_history(
        self, client: httpx.AsyncClient, ref: EntityRef, *, interval: str = "1d", limit: int = 30
    ) -> list[OHLCVBar]:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for history")

        multiplier, timespan = _INTERVAL_TO_AGG.get(interval, ("1", "day"))
        payload = await request_json(
            client, self.name,
            f"{self.base_url()}/v2/aggs/ticker/{ref.ticker}/range/{multiplier}/{timespan}/"
            f"{_range_start(limit, timespan)}/{_today()}",
            params={"adjusted": "true", "sort": "asc", "limit": limit},
            headers=self.auth_headers(),
        )
        results = (payload or {}).get("results") or []
        if not results:
            raise ProviderBadResponse(self.name, f"no historical bars for {ref.ticker}")

        bars: list[OHLCVBar] = []
        for row in results[-limit:]:
            close = as_float(row.get("c"))
            if close is None:
                continue
            bars.append(
                OHLCVBar(
                    symbol=ref.ticker,
                    timestamp=_ms_to_iso(as_float(row.get("t"))),
                    open=as_float(row.get("o")) or close,
                    high=as_float(row.get("h")) or close,
                    low=as_float(row.get("l")) or close,
                    close=close,
                    volume=as_float(row.get("v")),
                    provider=self.name,
                    interval=interval,
                    currency="USD",
                )
            )
        if not bars:
            raise ProviderBadResponse(self.name, f"historical bars for {ref.ticker} had no usable closes")
        return bars

    async def get_company_profile(self, client: httpx.AsyncClient, ref: EntityRef) -> CompanyProfile:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for a company profile")

        payload = await request_json(
            client, self.name, f"{self.base_url()}/v3/reference/tickers/{ref.ticker}",
            headers=self.auth_headers(),
        )
        result = (payload or {}).get("results") or {}
        if not result.get("name"):
            raise ProviderBadResponse(self.name, f"no company profile for {ref.ticker}")

        return CompanyProfile(
            company_name=str(result.get("name", "")),
            provider=self.name,
            symbol=ref.ticker,
            exchange=str(result.get("primary_exchange", "")),
            country=str(result.get("locale", "")).upper(),
            currency=str(result.get("currency_name", "")).upper(),
            sector=str(result.get("sic_description", "")),
            market_cap=as_float(result.get("market_cap")),
            website=str(result.get("homepage_url", "")),
            identifiers={
                "ticker": ref.ticker,
                "cik": str(result.get("cik", "")),
                "composite_figi": str(result.get("composite_figi", "")),
            },
            source_url=str(result.get("homepage_url", "")) or f"https://polygon.io/quote/{ref.ticker}",
        )


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _range_start(limit: int, timespan: str) -> str:
    """Calendar window wide enough to contain `limit` bars once weekends and
    holidays are removed — roughly 7/5 of the trading days, plus a margin."""
    from datetime import timedelta

    per_bar_days = {"minute": 1, "hour": 1, "day": 1.6, "week": 8, "month": 32}.get(timespan, 1.6)
    span = max(7, int(limit * per_bar_days) + 5)
    return (datetime.now(timezone.utc).date() - timedelta(days=span)).isoformat()
