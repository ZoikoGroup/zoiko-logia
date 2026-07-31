"""SAM.gov Get Opportunities Public API v2 connector."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from app.domains.live_sources.connectors.evidence_base import EvidenceSearchConnector
from app.domains.live_sources.evidence_schemas import EvidenceRecord, EvidenceSearchIntent, EvidenceSearchResponse


class SAMGovConnector(EvidenceSearchConnector):
    provider_key = "sam_gov"

    def __init__(self, endpoint: str, api_key: str) -> None:
        self.endpoint = endpoint
        self.api_key = api_key

    async def search(self, intent: EvidenceSearchIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> EvidenceSearchResponse:
        if not self.api_key:
            raise ValueError("SAM_GOV_API_KEY is not configured — create a free SAM.gov public API key")
        today = datetime.now(timezone.utc).date()
        # SAM.gov counts both boundary dates, so 364 days produces its maximum
        # supported 365-date search window. A 365-day subtraction is rejected.
        params = {"api_key": self.api_key, "title": intent.query, "postedFrom": (today - timedelta(days=364)).strftime("%m/%d/%Y"),
                  "postedTo": today.strftime("%m/%d/%Y"), "limit": intent.page_size, "offset": 0}
        if client is not None:
            response = await client.get(self.endpoint, params=params)
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                response = await c.get(self.endpoint, params=params)
        if response.is_error:
            # The API key is a query parameter. Avoid raise_for_status(), whose
            # exception string includes the complete URL and can leak the key.
            raise RuntimeError(f"SAM.gov API request failed with HTTP {response.status_code}") from None
        items = response.json().get("opportunitiesData") or []
        records = []
        for item in items:
            record_id = str(item.get("noticeId") or item.get("noticeid") or "").strip()
            title = str(item.get("title") or "").strip()
            if not record_id or not title:
                continue
            records.append(EvidenceRecord(
                provider_key=self.provider_key, record_id=record_id, record_type=str(item.get("type") or "US contract opportunity"),
                title=title, summary=str(item.get("fullParentPathName") or "")[:2000], jurisdiction="US",
                published_at=item.get("postedDate"), effective_at=item.get("responseDeadLine"),
                source_url=item.get("uiLink") or f"https://sam.gov/opp/{record_id}/view",
                metadata={"solicitation_number": item.get("solicitationNumber"), "naics_code": item.get("naicsCode")},
            ))
        return EvidenceSearchResponse(provider_key=self.provider_key, query=intent.query, records=records,
                                      fetched_at=datetime.now(timezone.utc).isoformat())
