"""Official legislation.gov.uk Atom search connector."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from xml.etree import ElementTree

import httpx

from app.domains.live_sources.connectors.evidence_base import EvidenceSearchConnector
from app.domains.live_sources.evidence_schemas import EvidenceRecord, EvidenceSearchIntent, EvidenceSearchResponse

_ATOM = "{http://www.w3.org/2005/Atom}"


class LegislationGovUKConnector(EvidenceSearchConnector):
    provider_key = "legislation_gov_uk"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def search(self, intent: EvidenceSearchIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> EvidenceSearchResponse:
        url = f"{self.base_url}/all/data.feed"
        params = {"title": intent.query, "results-count": intent.page_size}
        if client is not None:
            response = await client.get(url, params=params, headers={"Accept": "application/atom+xml"})
        else:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
                response = await c.get(url, params=params, headers={"Accept": "application/atom+xml"})
        for delay in (0.5, 1.0):
            if response.status_code != 202:
                break
            await asyncio.sleep(delay)
            if client is not None:
                response = await client.get(url, params=params, headers={"Accept": "application/atom+xml"})
            else:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
                    response = await c.get(url, params=params, headers={"Accept": "application/atom+xml"})
        if response.status_code == 202:
            raise ValueError("legislation.gov.uk is still preparing the Atom feed; retry later")
        response.raise_for_status()
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise ValueError(f"legislation.gov.uk returned invalid Atom XML: {exc}") from exc
        records = []
        for entry in root.findall(f"{_ATOM}entry"):
            title = (entry.findtext(f"{_ATOM}title") or "").strip()
            identifier = (entry.findtext(f"{_ATOM}id") or "").strip()
            link = next((node.get("href") for node in entry.findall(f"{_ATOM}link") if node.get("rel") in (None, "alternate")), None)
            if not title or not (link or identifier):
                continue
            source_url = link or identifier
            records.append(EvidenceRecord(
                provider_key=self.provider_key, record_id=identifier.rsplit("/", 1)[-1] or title,
                record_type="UK legislation", title=title,
                summary=(entry.findtext(f"{_ATOM}summary") or "")[:2000], jurisdiction="GB",
                published_at=entry.findtext(f"{_ATOM}published") or entry.findtext(f"{_ATOM}updated"),
                source_url=source_url, metadata={"atom_id": identifier},
            ))
        return EvidenceSearchResponse(provider_key=self.provider_key, query=intent.query, records=records,
                                      fetched_at=datetime.now(timezone.utc).isoformat())
