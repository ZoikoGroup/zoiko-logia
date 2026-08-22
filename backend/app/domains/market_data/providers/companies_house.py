"""Companies House — official UK company register and statutory filings.

Authoritative for UK company identity, status and filing history. No market
data of any kind: this is a registry, not an exchange, so it declares only the
filings/profile/search capabilities and the registry never routes a price
question here.

Authentication is HTTP Basic with the API key as the USERNAME and an empty
password — not a Bearer token, which is the single most common way to get a
401 from this API.

Docs: https://developer.company-information.service.gov.uk/
"""
from __future__ import annotations

import re

import httpx

from app.domains.market_data.http import request_json
from app.domains.market_data.providers.base import (
    CAP_FILINGS,
    CAP_OWNERSHIP,
    CAP_PROFILE,
    CAP_SEARCH,
    BaseStockProvider,
)
from app.domains.market_data.schemas import (
    FRESHNESS_FILING,
    CompanyProfile,
    EntityRef,
    FilingRecord,
    OwnershipStake,
    ProviderBadResponse,
)

_WEB_BASE = "https://find-and-update.company-information.service.gov.uk"

# PSC "natures_of_control" band strings — statutory filing vocabulary, not
# something this codebase invents. Only "ownership-of-shares-*" entries state
# a share-of-the-whole figure; voting-rights/appointment/influence entries are
# real control facts but not a percentage of shares, so get_ownership() below
# skips PSCs whose natures_of_control carry none of these.
_SHARE_BAND = re.compile(r"^ownership-of-shares-(\d+)-to-(\d+)-percent$")
# Older filings use open-ended wording instead of the newer banded system —
# economically the same 75-100% band, so normalized to it rather than treated
# as a separate, narrower case.
_SHARE_MORE_THAN = re.compile(r"^ownership-of-shares-more-than-(\d+)-percent$")


def _parse_share_band(nature: str) -> tuple[float, float] | None:
    match = _SHARE_BAND.match(nature)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = _SHARE_MORE_THAN.match(nature)
    if match:
        return float(match.group(1)), 100.0
    return None


class CompaniesHouseProvider(BaseStockProvider):
    name = "companies_house"
    CAPABILITIES = frozenset({CAP_FILINGS, CAP_PROFILE, CAP_SEARCH, CAP_OWNERSHIP})
    API_KEY_ENV = "COMPANIES_HOUSE_API_KEY"
    BASE_URL_ENV = "COMPANIES_HOUSE_API_BASE_URL"
    DEFAULT_BASE_URL = "https://api.company-information.service.gov.uk"

    def auth(self) -> httpx.Auth:
        # Key as username, empty password. See module docstring.
        return httpx.BasicAuth(self.require_configured(), "")

    async def _probe(self, client: httpx.AsyncClient) -> None:
        await request_json(
            client, self.name, f"{self.base_url()}/search/companies",
            params={"q": "test", "items_per_page": 1}, auth=self.auth(), retries=0,
        )

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int = 5) -> list[EntityRef]:
        payload = await request_json(
            client, self.name, f"{self.base_url()}/search/companies",
            params={"q": query, "items_per_page": limit}, auth=self.auth(),
        )
        items = (payload or {}).get("items") or []
        return [
            EntityRef(
                name=str(item.get("title", "")).strip(),
                company_number=str(item.get("company_number", "")).strip(),
                country="GB",
                company_status=str(item.get("company_status", "")).strip(),
                company_type=str(item.get("company_type", "")).strip(),
            )
            for item in items
            if item.get("company_number")
        ]

    async def _resolve_number(self, client: httpx.AsyncClient, ref: EntityRef) -> str:
        """A company number, resolved by search when the question only gave a
        name. Returns "" when nothing matched — the caller reports "not found"
        rather than falling through to another provider, because Companies
        House is authoritative for UK registration: if it has no record, no
        other source can supply one."""
        if ref.company_number:
            return ref.company_number
        candidates = await self.search(client, ref.name or "", limit=1)
        return candidates[0].company_number if candidates else ""

    async def get_company_profile(self, client: httpx.AsyncClient, ref: EntityRef) -> CompanyProfile:
        number = await self._resolve_number(client, ref)
        if not number:
            raise ProviderBadResponse(self.name, "no UK company matched that name")

        payload = await request_json(client, self.name, f"{self.base_url()}/company/{number}", auth=self.auth())
        if not isinstance(payload, dict) or not payload.get("company_name"):
            raise ProviderBadResponse(self.name, "company profile response was missing company_name")

        address = payload.get("registered_office_address") or {}
        accounts = (payload.get("accounts") or {}).get("next_accounts") or {}
        return CompanyProfile(
            company_name=str(payload.get("company_name", "")),
            provider=self.name,
            country="GB",
            source_url=f"{_WEB_BASE}/company/{number}",
            identifiers={
                "company_number": number,
                "company_status": str(payload.get("company_status", "")),
                "company_type": str(payload.get("type", "")),
                "incorporated_on": str(payload.get("date_of_creation", "")),
                "registered_office": ", ".join(
                    str(address.get(k, "")) for k in ("address_line_1", "locality", "postal_code") if address.get(k)
                ),
                "next_accounts_due": str(accounts.get("due_on", "")),
            },
        )

    async def get_filings(self, client: httpx.AsyncClient, ref: EntityRef, *, limit: int = 10) -> list[FilingRecord]:
        number = await self._resolve_number(client, ref)
        if not number:
            raise ProviderBadResponse(self.name, "no UK company matched that name")

        profile = await request_json(client, self.name, f"{self.base_url()}/company/{number}", auth=self.auth())
        company_name = str((profile or {}).get("company_name", "")) if isinstance(profile, dict) else ""

        payload = await request_json(
            client, self.name, f"{self.base_url()}/company/{number}/filing-history",
            params={"items_per_page": limit}, auth=self.auth(),
        )
        items = (payload or {}).get("items") or []

        records: list[FilingRecord] = []
        for item in items[:limit]:
            transaction_id = str(item.get("transaction_id", ""))
            records.append(
                FilingRecord(
                    company_name=company_name,
                    filing_type=str(item.get("type", "")),
                    filing_date=str(item.get("date", "")),
                    provider=self.name,
                    company_number=number,
                    description=str(item.get("description", "")).replace("-", " "),
                    document_id=transaction_id,
                    source_url=f"{_WEB_BASE}/company/{number}/filing-history/{transaction_id}"
                    if transaction_id
                    else f"{_WEB_BASE}/company/{number}/filing-history",
                )
            )
        return records

    async def get_ownership(self, client: httpx.AsyncClient, ref: EntityRef) -> list[OwnershipStake]:
        """Real, named persons-with-significant-control (PSC) — the only
        genuine "share of the whole" data this codebase has access to. Bands,
        never exact percentages (min_percent/max_percent), and only PSCs the
        register discloses (generally >25% control) — both real properties of
        the filing, not something this method loses on the way out."""
        number = await self._resolve_number(client, ref)
        if not number:
            raise ProviderBadResponse(self.name, "no UK company matched that name")

        profile = await request_json(client, self.name, f"{self.base_url()}/company/{number}", auth=self.auth())
        company_name = str((profile or {}).get("company_name", "")) if isinstance(profile, dict) else ""

        payload = await request_json(
            client, self.name, f"{self.base_url()}/company/{number}/persons-with-significant-control",
            auth=self.auth(),
        )
        items = (payload or {}).get("items") or []

        stakes: list[OwnershipStake] = []
        for item in items:
            natures = [str(n) for n in (item.get("natures_of_control") or [])]
            bands = [b for n in natures if (b := _parse_share_band(n)) is not None]
            # Multiple ownership-of-shares entries should not occur per PSC,
            # but if they do, the widest reported band is the honest one to
            # show rather than an arbitrary first match.
            min_percent = min((b[0] for b in bands), default=None)
            max_percent = max((b[1] for b in bands), default=None)
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            stakes.append(
                OwnershipStake(
                    name=name,
                    kind=str(item.get("kind", "")),
                    provider=self.name,
                    nature_of_control=natures,
                    min_percent=min_percent,
                    max_percent=max_percent,
                    notified_on=str(item.get("notified_on", "")),
                    ceased=bool(item.get("ceased_on")),
                    company_number=number,
                    company_name=company_name,
                    source_url=f"{_WEB_BASE}/company/{number}/persons-with-significant-control",
                )
            )
        if not stakes:
            raise ProviderBadResponse(self.name, "no persons with significant control on record")
        return stakes


# Statutory filings are as-filed and dated — never "delayed" or "realtime".
FRESHNESS = FRESHNESS_FILING
