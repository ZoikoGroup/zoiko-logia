"""
Companies House connector — https://api.company-information.service.gov.uk.
Needs a free API key, sent as the username of HTTP Basic Auth with a blank
password (confirmed live this session: an unauthenticated request returns
a clean 401 "Empty Authorization header", confirming this exact mechanism).
Full response-shape behavior not yet exercised with a real key, since none
was available at implementation time — see this connector's docstring
comments for the documented shape this was built against.

Two-step lookup: /search/companies?q=<name> resolves a free-text company
name to a company_number, then /company/{number} fetches the profile.
indicator_code is always "profile" for this connector today (see
live_sources/classifier.py's detect_company_lookup_intent()) — there's no
per-concept selection like SEC EDGAR's us-gaap concepts, since a company
profile doesn't decompose into comparable numeric line items the way
XBRL financial facts do.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


class CompaniesHouseConnector(LiveSourceConnector):
    provider_key = "companies_house"

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def fetch(self, intent: LiveDataIntent, *, timeout: float) -> NormalizedResponse:
        if not self.api_key:
            raise ValueError(
                "COMPANIES_HOUSE_API_KEY is not configured — register a free key at "
                "https://developer.company-information.service.gov.uk/ and add it to backend/.env"
            )
        if not intent.company_query:
            raise ValueError("Companies House connector requires LiveDataIntent.company_query")

        auth = httpx.BasicAuth(self.api_key, "")
        async with httpx.AsyncClient(timeout=timeout, auth=auth) as client:
            search_response = await client.get(
                f"{self.base_url}/search/companies", params={"q": intent.company_query, "items_per_page": "1"}
            )
            search_response.raise_for_status()
            results = (search_response.json().get("items") or [])
            if not results:
                raise ValueError(f"Companies House: no company found matching {intent.company_query!r}")
            company_number = results[0]["company_number"]

            profile_response = await client.get(f"{self.base_url}/company/{company_number}")
            profile_response.raise_for_status()
            profile = profile_response.json()

        company_name = profile.get("company_name", intent.company_query)
        status = profile.get("company_status", "unknown")
        incorporated = profile.get("date_of_creation", "unknown")

        return NormalizedResponse(
            provider_key=self.provider_key,
            indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label,
            country_code=intent.country_code,
            country_label=intent.country_label,
            value=status,
            unit="",
            observation_period=incorporated,
            as_of=datetime.now(timezone.utc).isoformat(),
            source_url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}",
            citation_title=(
                f"Companies House — {company_name} (No. {company_number}), "
                f"status: {status}, incorporated: {incorporated}"
            ),
            company_query=intent.company_query,
        )
