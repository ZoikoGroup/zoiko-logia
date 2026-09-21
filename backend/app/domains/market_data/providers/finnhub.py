"""Finnhub — global quotes, profiles, fundamentals and symbol search.

REST only in this adapter. Finnhub also offers a WebSocket feed at
wss://ws.finnhub.io for continuous trade updates; that is deliberately not
implemented here, because a stream does not fit the request/response answer
pipeline this adapter feeds — see the market_data package docstring and the
streaming note in app/orchestration/market_data.py.

Freshness is reported as delayed rather than realtime: whether a key is
entitled to realtime US trades depends on the account's plan, which the API
does not state in a quote response. Claiming realtime on a delayed feed would
be exactly the kind of unverifiable assertion this product exists to avoid, so
the conservative label is used unless an operator overrides it.

Docs: https://finnhub.io/docs/api
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

from app.domains.market_data.http import as_float, request_json
from app.domains.market_data.providers.base import (
    CAP_FUNDAMENTALS,
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
    ProviderBadResponse,
    StockQuote,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FinnhubProvider(BaseStockProvider):
    name = "finnhub"
    CAPABILITIES = frozenset({CAP_QUOTE, CAP_PROFILE, CAP_FUNDAMENTALS, CAP_SEARCH})
    API_KEY_ENV = "FINNHUB_API_KEY"
    BASE_URL_ENV = "FINNHUB_API_BASE_URL"
    DEFAULT_BASE_URL = "https://finnhub.io/api/v1"

    def auth_headers(self) -> dict[str, str]:
        # Header rather than the ?token= query param, so the key cannot end up
        # in an access log or a redirect chain.
        return {"X-Finnhub-Token": self.require_configured()}

    def freshness(self) -> str:
        """Operator-declared entitlement. The API cannot tell us, so this is
        config, and it defaults to the conservative answer."""
        return FRESHNESS_REALTIME if os.getenv("FINNHUB_REALTIME", "").lower() in {"1", "true", "yes"} else FRESHNESS_DELAYED

    async def _probe(self, client: httpx.AsyncClient) -> None:
        await request_json(
            client, self.name, f"{self.base_url()}/quote",
            params={"symbol": "AAPL"}, headers=self.auth_headers(), retries=0,
        )

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int = 5) -> list[EntityRef]:
        payload = await request_json(
            client, self.name, f"{self.base_url()}/search",
            params={"q": query}, headers=self.auth_headers(),
        )
        results = (payload or {}).get("result") or []
        return [
            EntityRef(
                name=str(item.get("description", "")).strip(),
                ticker=str(item.get("displaySymbol") or item.get("symbol") or "").strip(),
            )
            for item in results[:limit]
            if item.get("symbol")
        ]

    async def get_quote(self, client: httpx.AsyncClient, ref: EntityRef) -> StockQuote:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for a quote")

        payload = await request_json(
            client, self.name, f"{self.base_url()}/quote",
            params={"symbol": ref.ticker}, headers=self.auth_headers(),
        )
        price = as_float((payload or {}).get("c"))
        # Finnhub answers 200 with every field zeroed for an unknown symbol,
        # rather than 404 — so a zero price means "no such symbol", not "this
        # share is worthless", and must not be reported as a figure.
        if price is None or price == 0:
            raise ProviderBadResponse(self.name, f"no quote data for {ref.ticker}")

        timestamp = as_float(payload.get("t"))
        return StockQuote(
            symbol=ref.ticker,
            price=price,
            provider=self.name,
            freshness=self.freshness(),
            fetched_at=_now_iso(),
            company_name=ref.name,
            change=as_float(payload.get("d")),
            change_percent=as_float(payload.get("dp")),
            open=as_float(payload.get("o")),
            high=as_float(payload.get("h")),
            low=as_float(payload.get("l")),
            previous_close=as_float(payload.get("pc")),
            provider_timestamp=(
                datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds") if timestamp else ""
            ),
            source_url=f"https://finnhub.io/quote/{ref.ticker}",
        )

    async def get_company_profile(self, client: httpx.AsyncClient, ref: EntityRef) -> CompanyProfile:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for a company profile")

        payload = await request_json(
            client, self.name, f"{self.base_url()}/stock/profile2",
            params={"symbol": ref.ticker}, headers=self.auth_headers(),
        )
        if not isinstance(payload, dict) or not payload.get("name"):
            raise ProviderBadResponse(self.name, f"no company profile for {ref.ticker}")

        market_cap = as_float(payload.get("marketCapitalization"))
        return CompanyProfile(
            company_name=str(payload.get("name", "")),
            provider=self.name,
            symbol=ref.ticker,
            exchange=str(payload.get("exchange", "")),
            country=str(payload.get("country", "")),
            currency=str(payload.get("currency", "")),
            industry=str(payload.get("finnhubIndustry", "")),
            # Finnhub reports market cap in millions of the listing currency.
            market_cap=market_cap * 1_000_000 if market_cap is not None else None,
            website=str(payload.get("weburl", "")),
            identifiers={"ipo": str(payload.get("ipo", "")), "ticker": ref.ticker},
            source_url=str(payload.get("weburl", "")) or f"https://finnhub.io/quote/{ref.ticker}",
        )

    async def get_fundamentals(self, client: httpx.AsyncClient, ref: EntityRef) -> list[FinancialMetric]:
        if not ref.ticker:
            raise ProviderBadResponse(self.name, "a ticker is required for fundamentals")

        payload = await request_json(
            client, self.name, f"{self.base_url()}/stock/metric",
            params={"symbol": ref.ticker, "metric": "all"}, headers=self.auth_headers(),
        )
        metrics = (payload or {}).get("metric") or {}
        if not isinstance(metrics, dict) or not metrics:
            raise ProviderBadResponse(self.name, f"no fundamentals for {ref.ticker}")

        # A curated subset: the whole payload is ~100 ratios, and dumping all of
        # them into an answer prompt buries the figure the user asked about.
        # Values Finnhub reports in millions of the listing currency. Scaled to
        # absolute units on the way out so the whole subsystem speaks one unit —
        # get_company_profile() above already does this, and two methods of the
        # same provider disagreeing about scale is how a market cap gets
        # reported a million times too small.
        in_millions = {"marketCapitalization"}
        wanted = {
            "marketCapitalization": ("Market capitalisation", "USD"),
            "peBasicExclExtraTTM": ("P/E ratio (TTM)", "ratio"),
            "epsBasicExclExtraItemsTTM": ("EPS (TTM)", "per share"),
            "revenuePerShareTTM": ("Revenue per share (TTM)", "per share"),
            "grossMarginTTM": ("Gross margin (TTM)", "%"),
            "netProfitMarginTTM": ("Net profit margin (TTM)", "%"),
            "roeTTM": ("Return on equity (TTM)", "%"),
            "totalDebt/totalEquityQuarterly": ("Debt to equity", "ratio"),
            "currentRatioQuarterly": ("Current ratio", "ratio"),
        }
        out: list[FinancialMetric] = []
        for key, (label, unit) in wanted.items():
            value = as_float(metrics.get(key))
            if value is None:
                continue
            if key in in_millions:
                value *= 1_000_000
            out.append(
                FinancialMetric(
                    metric=label,
                    value=value,
                    provider=self.name,
                    symbol=ref.ticker,
                    company=ref.name,
                    unit=unit,
                    period="TTM" if "TTM" in key else "latest quarter",
                    source_url=f"https://finnhub.io/quote/{ref.ticker}",
                )
            )
        if not out:
            raise ProviderBadResponse(self.name, f"no usable fundamentals for {ref.ticker}")
        return out
