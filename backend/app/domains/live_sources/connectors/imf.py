"""Official IMF DataMapper connector for current macroeconomic indicators."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


class IMFConnector(LiveSourceConnector):
    provider_key = "imf"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        try:
            indicator, iso3 = intent.indicator_code.split(":", 1)
        except ValueError as exc:
            raise ValueError("IMF indicator code must be INDICATOR:ISO3") from exc
        url = f"{self.base_url}/{indicator}/{iso3}"
        current_year = str(datetime.now(timezone.utc).year)
        if client is not None:
            response = await client.get(url, params={"periods": current_year})
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                response = await c.get(url, params={"periods": current_year})
        response.raise_for_status()
        body = response.json()
        values = ((body.get("values") or {}).get(indicator) or {}).get(iso3) or {}
        usable = [(str(year), value) for year, value in values.items() if value is not None]
        if not usable:
            raise ValueError(f"IMF API returned no observations for {intent.indicator_code}")
        current = next((item for item in usable if item[0] == current_year), None)
        period, value = current or max(usable, key=lambda item: int(item[0]) if item[0].isdigit() else -1)
        return NormalizedResponse(
            provider_key=self.provider_key, indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label, country_code=intent.country_code,
            country_label=intent.country_label, value=float(value), unit="%",
            observation_period=period, as_of=datetime.now(timezone.utc).isoformat(),
            source_url=f"https://www.imf.org/external/datamapper/{indicator}@WEO/{iso3}",
            citation_title=f"International Monetary Fund — {intent.country_label}, {intent.indicator_label}, {period}",
        )
