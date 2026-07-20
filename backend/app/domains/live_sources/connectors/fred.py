"""
FRED (Federal Reserve Economic Data, St. Louis Fed) connector —
https://api.stlouisfed.org/fred. Needs a free API key — see the "API Key
Setup" instructions this was implemented alongside. Confirmed reachable
this session: a request with no api_key returns a clean 400
("Variable api_key is not set"), confirming the auth mechanism
(query-param api_key) — full data-shape behavior not yet exercised with a
real key, since none was available at implementation time.

sort_order=desc&limit=1 asks FRED to return only the single most recent
observation server-side (FRED's equivalent of World Bank's mrnev=1),
avoiding fetching the whole series history.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


class FREDConnector(LiveSourceConnector):
    provider_key = "fred"

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def fetch(self, intent: LiveDataIntent, *, timeout: float) -> NormalizedResponse:
        if not self.api_key:
            raise ValueError(
                "FRED_API_KEY is not configured — register a free key at "
                "https://fredaccount.stlouisfed.org/apikeys and add it to backend/.env"
            )

        params = {
            "series_id": intent.indicator_code,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": "1",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{self.base_url}/series/observations", params=params)
            response.raise_for_status()
            body = response.json()

        observations = body.get("observations") or []
        if not observations:
            raise ValueError(f"FRED API returned no observations for series {intent.indicator_code}")

        latest = observations[0]
        value = latest.get("value")
        if value is None or value == ".":  # FRED uses "." to mark a missing value
            raise ValueError(f"FRED API has no non-empty value for series {intent.indicator_code}")

        date = latest.get("date", "unknown")

        return NormalizedResponse(
            provider_key=self.provider_key,
            indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label,
            country_code=intent.country_code,
            country_label=intent.country_label,
            value=float(value),
            unit="%",
            observation_period=date,
            as_of=datetime.now(timezone.utc).isoformat(),
            source_url=f"https://fred.stlouisfed.org/series/{intent.indicator_code}",
            citation_title=f"FRED — {intent.indicator_label}, {date}",
        )
