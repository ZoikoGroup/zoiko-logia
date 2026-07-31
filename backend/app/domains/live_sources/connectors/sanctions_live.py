"""Ask-Kriton adapter for exact-name candidate lookup in cached sanctions snapshots."""
from __future__ import annotations

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.sanctions_service import find_exact_candidates
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


class SanctionsLiveConnector(LiveSourceConnector):
    def __init__(self, provider_key: str, display_name: str, landing_url: str) -> None:
        self.provider_key, self.display_name, self.landing_url = provider_key, display_name, landing_url

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        name = intent.company_query or ""
        snapshot, matches = await find_exact_candidates(self.provider_key, name)
        if not matches:
            value = f"No exact-name candidate was found for {name}. This is not sanctions clearance; identifiers and fuzzy aliases require human review."
            record_id = f"no-exact-match-{snapshot.content_sha256[:12]}"
        else:
            top = matches[0]
            value = (f"Potential exact-name candidate: {top.primary_name}; type: {top.entity_type}; "
                     f"programs: {', '.join(top.programs) or 'not stated'}. Human review is required.")
            record_id = top.record_id
        return NormalizedResponse(
            provider_key=self.provider_key, indicator_code=record_id, indicator_label=f"{self.display_name} name screening",
            country_code=intent.country_code, country_label=intent.country_label, value=value, unit="",
            observation_period=snapshot.fetched_at, as_of=snapshot.fetched_at, source_url=self.landing_url,
            citation_title=f"{self.display_name} — official sanctions snapshot", company_query=name,
        )
