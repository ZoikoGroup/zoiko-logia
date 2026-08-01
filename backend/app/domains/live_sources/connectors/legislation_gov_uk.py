"""Official legislation.gov.uk Atom search connector."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from xml.etree import ElementTree

import httpx

from app.core.config import get_settings
from app.domains.live_sources.connectors.evidence_base import EvidenceSearchConnector
from app.domains.live_sources.evidence_schemas import EvidenceRecord, EvidenceSearchIntent, EvidenceSearchResponse

_ATOM = "{http://www.w3.org/2005/Atom}"


def _parse_delays(raw: str) -> tuple[float, ...]:
    delays = []
    for item in raw.split(","):
        try:
            value = float(item.strip())
        except ValueError:
            continue
        if value > 0:
            delays.append(value)
    return tuple(delays)


class LegislationGovUKConnector(EvidenceSearchConnector):
    provider_key = "legislation_gov_uk"

    def __init__(self, base_url: str, retry_delays: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        # The published ladder was (0.5, 1.0) — 1.5 seconds total, against a
        # host observed to sit on HTTP 202 well past that, which is why every
        # live probe gave up before the feed was ever built. Configurable and
        # longer by default; still bounded, since a caller waiting on this is
        # a user waiting on an answer.
        configured = retry_delays if retry_delays is not None else get_settings().LEGISLATION_GOV_UK_RETRY_DELAYS
        self.retry_delays = _parse_delays(configured) or (0.5, 1.0, 2.0, 4.0)

    async def _get(self, url: str, params: dict, *, timeout: float, client: httpx.AsyncClient | None) -> httpx.Response:
        headers = {"Accept": "application/atom+xml"}
        if client is not None:
            return await client.get(url, params=params, headers=headers)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            return await c.get(url, params=params, headers=headers)

    async def search(self, intent: EvidenceSearchIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> EvidenceSearchResponse:
        url = f"{self.base_url}/all/data.feed"
        params = {"title": intent.query, "results-count": intent.page_size}
        response = await self._get(url, params, timeout=timeout, client=client)
        for delay in self.retry_delays:
            if response.status_code != 202:
                break
            await asyncio.sleep(delay)
            response = await self._get(url, params, timeout=timeout, client=client)
        if response.status_code == 202:
            waited = sum(self.retry_delays)
            raise ValueError(
                f"legislation.gov.uk was still preparing the Atom feed after {waited:g}s; "
                "raise LEGISLATION_GOV_UK_RETRY_DELAYS or retry later"
            )
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
