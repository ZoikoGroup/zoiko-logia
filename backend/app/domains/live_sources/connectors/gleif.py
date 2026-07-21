"""
GLEIF (Global Legal Entity Identifier Foundation) connector —
https://api.gleif.org/api/v1. Fully keyless, no registration required
(confirmed live this session: /lei-records accepts unauthenticated requests
with no rate-limit rejection). Replaces OpenCorporates as the company-lookup
fallback for every jurisdiction the classifier resolves that isn't US/UK
(which have their own dedicated statutory registries — SEC EDGAR/Companies
House) — OpenCorporates now requires a paid plan (minimum £2,250/year), so
this keyless alternative is used instead. See
live_sources/classifier.py's detect_company_lookup_intent().

Trade-off (documented, not hidden): GLEIF is a Legal Entity Identifier
registry, not a universal company register — it only covers entities that
hold an LEI (required for financial-market participants, increasingly
common for larger corporates generally). It won't find a small business
with no LEI, unlike Companies House/SEC EDGAR's full statutory coverage.

Single-endpoint lookup (no separate search-then-profile step needed, unlike
Companies House/OpenCorporates — the search response already carries the
full entity record): GET /lei-records?filter[entity.legalName]=<name>&
filter[entity.jurisdiction]=<alpha-2 code>&page[size]=1. jurisdiction_code
is this codebase's own alpha-2 country_code, used as-is — GLEIF's
entity.jurisdiction filter takes plain ISO 3166-1 alpha-2 codes, confirmed
live this session against GB/IN/AE, so (unlike OpenCorporates) no
lowercasing/translation table is needed.

Verified live this session:
- GB + "Tesco" -> TESCO PLC, Welwyn Garden City, no. 00445790, ACTIVE
- IN + "Reliance Industries" -> multiple RELIANCE ... entities, ACTIVE
- AE + "Emirates" -> Emirates, Dubai, ACTIVE
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


class GLEIFConnector(LiveSourceConnector):
    provider_key = "gleif"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float) -> NormalizedResponse:
        if not intent.company_query:
            raise ValueError("GLEIF connector requires LiveDataIntent.company_query")

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{self.base_url}/lei-records",
                params={
                    "filter[entity.legalName]": intent.company_query,
                    "filter[entity.jurisdiction]": intent.country_code,
                    "page[size]": "1",
                },
            )
            response.raise_for_status()
            records = response.json().get("data") or []
            if not records:
                raise ValueError(
                    f"GLEIF: no LEI record found matching {intent.company_query!r} in {intent.country_code!r}"
                )
            attributes = records[0]["attributes"]

        entity = attributes["entity"]
        lei = attributes["lei"]
        legal_name = entity["legalName"]["name"]
        status = entity.get("status", "unknown")
        registered_as = entity.get("registeredAs") or "unknown"
        creation_date = (entity.get("creationDate") or "unknown")[:10]

        return NormalizedResponse(
            provider_key=self.provider_key,
            indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label,
            country_code=intent.country_code,
            country_label=intent.country_label,
            value=status,
            unit="",
            observation_period=creation_date,
            as_of=datetime.now(timezone.utc).isoformat(),
            source_url=f"https://search.gleif.org/#/record/{lei}",
            citation_title=(
                f"GLEIF — {legal_name} (Reg. No. {registered_as}, LEI {lei}), "
                f"status: {status}, registered: {creation_date}"
            ),
            company_query=intent.company_query,
        )
