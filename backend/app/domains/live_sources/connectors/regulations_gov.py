"""Regulations.gov v4 search connector for official US rulemaking records."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.connectors.evidence_base import EvidenceSearchConnector
from app.domains.live_sources.evidence_schemas import EvidenceRecord, EvidenceSearchIntent, EvidenceSearchResponse
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


# Regulations.gov v4 rejects page[size] below 5 with a bare HTTP 400.
# EvidenceSearchIntent allows page_size >= 1, so a caller asking for a
# single record — which the evidence-search endpoint permits, and which the
# upstream canary did — got a 400 rather than one result. Request the
# supported minimum and let the caller's own limit apply to the response.
_MIN_PAGE_SIZE = 5


class RegulationsGovConnector(EvidenceSearchConnector):
    provider_key = "regulations_gov"

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def search(self, intent: EvidenceSearchIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> EvidenceSearchResponse:
        if not self.api_key:
            raise ValueError("REGULATIONS_GOV_API_KEY is not configured — obtain a free data.gov API key")
        params: dict[str, str | int] = {
            "filter[searchTerm]": intent.query,
            "page[size]": max(intent.page_size, _MIN_PAGE_SIZE),
            "sort": "-postedDate",
            "api_key": self.api_key,
        }
        if len(intent.record_types) == 1:
            params["filter[documentType]"] = intent.record_types[0]
        url = f"{self.base_url}/documents"
        if client is not None:
            response = await client.get(url, params=params)
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                response = await c.get(url, params=params)
        response.raise_for_status()
        body = response.json()
        records: list[EvidenceRecord] = []
        for item in body.get("data") or []:
            attrs = item.get("attributes") or {}
            record_id = str(item.get("id") or "").strip()
            title = str(attrs.get("title") or "").strip()
            if not record_id or not title:
                continue
            records.append(EvidenceRecord(
                provider_key=self.provider_key, record_id=record_id,
                record_type=str(attrs.get("documentType") or item.get("type") or "document"),
                title=title, summary=str(attrs.get("abstract") or "")[:2000], jurisdiction="US",
                published_at=attrs.get("postedDate"), effective_at=attrs.get("effectiveDate"),
                source_url=f"https://www.regulations.gov/document/{record_id}",
                metadata={"agency_id": attrs.get("agencyId"), "docket_id": attrs.get("docketId"),
                          "comment_end_date": attrs.get("commentEndDate")},
            ))
        return EvidenceSearchResponse(
            provider_key=self.provider_key, query=intent.query,
            # Trimmed back to what was actually asked for, since the request
            # above may have been widened to the upstream's minimum.
            records=records[: intent.page_size],
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )


class RegulationsGovLiveConnector(LiveSourceConnector):
    """Compatibility adapter that sends the newest official hit through Ask Kriton's existing citation path."""
    provider_key = "regulations_gov"

    def __init__(self, base_url: str, api_key: str) -> None:
        self.search_connector = RegulationsGovConnector(base_url, api_key)

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        response = await self.search_connector.search(
            EvidenceSearchIntent(provider_key=self.provider_key, query=intent.company_query or intent.indicator_label, page_size=5),
            timeout=timeout, client=client,
        )
        if not response.records:
            raise ValueError("Regulations.gov returned no matching official documents")
        record = response.records[0]
        value = record.summary or f"{record.record_type}: {record.title}"
        return NormalizedResponse(
            provider_key=self.provider_key, indicator_code=record.record_id,
            indicator_label=record.title, country_code="US", country_label="United States",
            value=value, unit="", observation_period=record.published_at or "current",
            as_of=response.fetched_at, source_url=str(record.source_url),
            citation_title=f"Regulations.gov — {record.title}", company_query=intent.company_query,
        )
