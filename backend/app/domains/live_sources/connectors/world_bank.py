"""
World Bank Open Data connector — https://api.worldbank.org/v2. Fully
keyless, no signup, stable/versioned indicator codes. Chosen as the MVP
connector over FRED/RBI/exchangerate-host because it needs zero credential
setup and covers the GDP/inflation/unemployment slice of "dynamic economic
data" cleanly; it does NOT cover repo rate or daily FX — that's an
intentional scope boundary for a second connector, not an oversight.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


class WorldBankConnector(LiveSourceConnector):
    provider_key = "world_bank"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        # World Bank's own mrnev=1 ("most recent non-empty value") param
        # started returning a bare 500-style "Request Error" HTML page from
        # their server sometime this session — confirmed by reproducing the
        # exact same request with and without mrnev=1 directly against the
        # live API: identical URL minus that one param returns normal JSON.
        # The API returns observations in descending-date order by default
        # (confirmed: per_page=5 came back 2025, 2024, 2023...), so fetching
        # a handful of recent periods and picking the first non-null value
        # client-side reproduces mrnev's own behavior without depending on
        # whatever is currently broken server-side for that parameter.
        url = f"{self.base_url}/country/{intent.country_code}/indicator/{intent.indicator_code}"
        params = {"format": "json", "per_page": "6"}

        if client is not None:
            response = await client.get(url, params=params)
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                response = await c.get(url, params=params)
        response.raise_for_status()
        body = response.json()

        if not isinstance(body, list) or len(body) < 2 or not body[1]:
            raise ValueError(f"World Bank API returned no observations for {intent.indicator_code}/{intent.country_code}")

        observation = next((obs for obs in body[1] if obs.get("value") is not None), None)
        if observation is None:
            raise ValueError(f"World Bank API has no non-empty value for {intent.indicator_code}/{intent.country_code}")
        value = observation["value"]

        country_label = (observation.get("country") or {}).get("value", intent.country_label)
        period = observation.get("date", "unknown")

        return NormalizedResponse(
            provider_key=self.provider_key,
            indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label,
            country_code=intent.country_code,
            country_label=country_label,
            value=value,
            unit="",
            observation_period=str(period),
            as_of=datetime.now(timezone.utc).isoformat(),
            source_url=f"{self.base_url}/country/{intent.country_code}/indicator/{intent.indicator_code}",
            citation_title=f"World Bank — {country_label}, {intent.indicator_label}, {period}",
        )
