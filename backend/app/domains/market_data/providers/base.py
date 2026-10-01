"""The contract every market-data provider implements.

Modelled on app/domains/model_gateway/providers/base.py: one Protocol that the
registry depends on, so swapping or adding a provider requires no change
anywhere else.

Two differences from the model-gateway case, both forced by the domain:

  - Capabilities are declared, not assumed. Companies House has no share
    prices; Alpha Vantage has no UK statutory filings. A single fat interface
    where two thirds of the methods raise would make the registry guess, so
    each adapter states CAPABILITIES and the registry only routes work a
    provider can actually do.

  - Methods raise rather than return a sentinel on failure. The registry needs
    to tell "this provider is down, try the next one" apart from "the provider
    answered, and the answer is that there is no such company" — a None return
    cannot express that difference, and silently falling through to the next
    provider on a legitimate empty result would produce contradictory answers.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from app.domains.market_data.schemas import (
    CapabilityNotSupported,
    CompanyProfile,
    EntityRef,
    FilingRecord,
    FinancialMetric,
    OHLCVBar,
    OwnershipStake,
    ProviderHealth,
    ProviderNotConfigured,
    StockQuote,
)

# Capability tokens. Kept as plain strings so the registry's routing table reads
# as data rather than as imports.
CAP_QUOTE = "quote"
CAP_HISTORY = "history"
CAP_PROFILE = "profile"
CAP_FUNDAMENTALS = "fundamentals"
CAP_FILINGS = "filings"
CAP_SEARCH = "search"
CAP_OWNERSHIP = "ownership"


class BaseStockProvider:
    """Default implementation: every capability unsupported until an adapter
    overrides it. Subclasses declare what they can do and implement exactly
    that, so an unimplemented method can never silently return empty and look
    like "no data" when it means "not asked properly"."""

    name: str = "base"
    CAPABILITIES: frozenset[str] = frozenset()
    API_KEY_ENV: str = ""
    BASE_URL_ENV: str = ""
    DEFAULT_BASE_URL: str = ""

    # ── configuration ────────────────────────────────────────────────────────

    def api_key(self) -> str:
        return os.getenv(self.API_KEY_ENV, "").strip() if self.API_KEY_ENV else ""

    def base_url(self) -> str:
        configured = os.getenv(self.BASE_URL_ENV, "").strip() if self.BASE_URL_ENV else ""
        return (configured or self.DEFAULT_BASE_URL).rstrip("/")

    def configured(self) -> bool:
        """Whether an operator has enabled this provider. Unconfigured is not an
        error state — it is the default, and the registry simply skips it."""
        return bool(self.api_key())

    def require_configured(self) -> str:
        key = self.api_key()
        if not key:
            raise ProviderNotConfigured(self.name, f"{self.API_KEY_ENV} is not set")
        return key

    def supports(self, capability: str) -> bool:
        return capability in self.CAPABILITIES

    def auth_headers(self) -> dict[str, str]:
        return {}

    def auth(self) -> Optional[httpx.Auth]:
        """httpx auth object, for providers that use HTTP Basic rather than a
        header or query parameter."""
        return None

    # ── capabilities ─────────────────────────────────────────────────────────

    async def get_quote(self, client: httpx.AsyncClient, ref: EntityRef) -> StockQuote:
        raise CapabilityNotSupported(self.name, "quotes are not available from this provider")

    async def get_history(
        self, client: httpx.AsyncClient, ref: EntityRef, *, interval: str = "1d", limit: int = 30
    ) -> list[OHLCVBar]:
        raise CapabilityNotSupported(self.name, "historical bars are not available from this provider")

    async def get_company_profile(self, client: httpx.AsyncClient, ref: EntityRef) -> CompanyProfile:
        raise CapabilityNotSupported(self.name, "company profiles are not available from this provider")

    async def get_fundamentals(self, client: httpx.AsyncClient, ref: EntityRef) -> list[FinancialMetric]:
        raise CapabilityNotSupported(self.name, "fundamentals are not available from this provider")

    async def get_filings(self, client: httpx.AsyncClient, ref: EntityRef, *, limit: int = 10) -> list[FilingRecord]:
        raise CapabilityNotSupported(self.name, "filings are not available from this provider")

    async def get_ownership(self, client: httpx.AsyncClient, ref: EntityRef) -> list[OwnershipStake]:
        raise CapabilityNotSupported(self.name, "ownership/PSC data is not available from this provider")

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int = 5) -> list[EntityRef]:
        raise CapabilityNotSupported(self.name, "search is not available from this provider")

    # ── health ───────────────────────────────────────────────────────────────

    async def health_check(self, client: httpx.AsyncClient) -> ProviderHealth:
        """Reports configured/reachable only. Never echoes the key, not even
        truncated — this feeds a status endpoint."""
        if not self.configured():
            return ProviderHealth(provider=self.name, configured=False, detail="API key not set")
        try:
            await self._probe(client)
            return ProviderHealth(provider=self.name, configured=True, reachable=True)
        except Exception as exc:  # noqa: BLE001 — health must never raise
            detail = exc.message if hasattr(exc, "message") else type(exc).__name__
            return ProviderHealth(provider=self.name, configured=True, reachable=False, detail=str(detail))

    async def _probe(self, client: httpx.AsyncClient) -> None:
        raise CapabilityNotSupported(self.name, "no health probe implemented")
