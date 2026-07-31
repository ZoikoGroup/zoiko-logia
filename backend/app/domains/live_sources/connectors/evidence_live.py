"""Adapter for sending the newest evidence-search hit through Ask Kriton's citation path."""
from __future__ import annotations

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.connectors.evidence_base import EvidenceSearchConnector
from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


class EvidenceLiveConnector(LiveSourceConnector):
    def __init__(self, provider_key: str, search_connector: EvidenceSearchConnector) -> None:
        self.provider_key = provider_key
        self.search_connector = search_connector

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        response = await self.search_connector.search(
            EvidenceSearchIntent(
                provider_key=self.provider_key, query=intent.company_query or intent.indicator_label,
                jurisdiction=intent.country_code, page_size=5,
            ), timeout=timeout, client=client,
        )
        if not response.records:
            raise ValueError(f"{self.provider_key} returned no matching official records")
        record = response.records[0]
        value = record.summary or f"{record.record_type}: {record.title}"
        return NormalizedResponse(
            provider_key=self.provider_key, indicator_code=record.record_id,
            indicator_label=record.title, country_code=intent.country_code,
            country_label=intent.country_label, value=value, unit="",
            observation_period=record.published_at or record.effective_at or "current",
            as_of=response.fetched_at, source_url=str(record.source_url),
            citation_title=record.title, company_query=intent.company_query,
        )
