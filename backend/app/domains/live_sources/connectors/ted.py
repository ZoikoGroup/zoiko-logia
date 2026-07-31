"""TED API v3 search for published EU procurement notices."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.evidence_base import EvidenceSearchConnector
from app.domains.live_sources.evidence_schemas import EvidenceRecord, EvidenceSearchIntent, EvidenceSearchResponse


def _first(value):
    if isinstance(value, list):
        return value[0] if value else ""
    if isinstance(value, dict):
        preferred = value.get("eng") or value.get("ENG") or value.get("en")
        return _first(preferred if preferred is not None else next(iter(value.values()), ""))
    return value or ""


class TEDConnector(EvidenceSearchConnector):
    provider_key = "ted"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def search(self, intent: EvidenceSearchIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> EvidenceSearchResponse:
        term = intent.query.replace('"', " ").strip()
        payload = {"query": f'FT ~ "{term}"', "fields": ["publication-number", "notice-title", "publication-date", "buyer-name", "notice-type"],
                   "page": 1, "limit": intent.page_size, "scope": "ACTIVE", "paginationMode": "PAGE_NUMBER"}
        url = f"{self.base_url}/notices/search"
        if client is not None:
            response = await client.post(url, json=payload)
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                response = await c.post(url, json=payload)
        response.raise_for_status()
        body = response.json()
        items = body.get("notices") or body.get("results") or []
        records = []
        for item in items:
            record_id = str(_first(item.get("publication-number") or item.get("notice-id") or item.get("noticeId") or item.get("id"))).strip()
            title = str(_first(item.get("notice-title") or item.get("title"))).strip()
            links = item.get("links") or {}
            html_url = _first(links.get("html") if isinstance(links, dict) else links)
            if not record_id or not title:
                continue
            records.append(EvidenceRecord(
                provider_key=self.provider_key, record_id=record_id, record_type="EU procurement notice",
                title=title, summary=str(_first(item.get("buyer-name")))[:2000], jurisdiction="EU",
                published_at=str(_first(item.get("publication-date") or item.get("publicationDate"))) or None,
                source_url=html_url or f"https://ted.europa.eu/en/notice/-/detail/{record_id}", metadata={"raw_links": links},
            ))
        return EvidenceSearchResponse(provider_key=self.provider_key, query=intent.query, records=records,
                                      fetched_at=datetime.now(timezone.utc).isoformat())
