"""Official ECB Data Portal SDMX connector."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


class ECBConnector(LiveSourceConnector):
    provider_key = "ecb"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        try:
            flow, key = intent.indicator_code.split(":", 1)
        except ValueError as exc:
            raise ValueError("ECB indicator code must be FLOW:SERIES_KEY") from exc
        url = f"{self.base_url}/data/{flow}/{key}"
        params = {"format": "csvdata", "lastNObservations": "1", "detail": "dataonly"}
        if client is not None:
            response = await client.get(url, params=params, headers={"Accept": "text/csv"})
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                response = await c.get(url, params=params, headers={"Accept": "text/csv"})
        response.raise_for_status()
        rows = list(csv.DictReader(StringIO(response.text)))
        if not rows:
            raise ValueError(f"ECB API returned no observations for {intent.indicator_code}")
        row = rows[-1]
        raw_value = row.get("OBS_VALUE")
        period = row.get("TIME_PERIOD")
        if raw_value in (None, "") or not period:
            raise ValueError("ECB API returned an incomplete observation")
        unit = row.get("UNIT") or row.get("UNIT_MEASURE") or "%"
        return NormalizedResponse(
            provider_key=self.provider_key, indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label, country_code=intent.country_code,
            country_label=intent.country_label, value=float(raw_value), unit=unit,
            observation_period=period, as_of=datetime.now(timezone.utc).isoformat(),
            source_url=f"https://data.ecb.europa.eu/data/datasets/{flow}/{key}",
            citation_title=f"European Central Bank — {intent.indicator_label}, {period}",
        )
