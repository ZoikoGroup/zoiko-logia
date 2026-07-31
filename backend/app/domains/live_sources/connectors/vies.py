"""European Commission VIES VAT-number validation connector."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


class VIESConnector(LiveSourceConnector):
    provider_key = "vies"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        vat_number = (intent.company_query or "").replace(" ", "").upper()
        if len(vat_number) < 4 or not vat_number[:2].isalpha():
            raise ValueError("VIES validation requires an EU VAT number with its two-letter country prefix")
        payload = {"countryCode": vat_number[:2], "vatNumber": vat_number[2:]}
        url = f"{self.base_url}/check-vat-number"
        if client is not None:
            response = await client.post(url, json=payload)
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                response = await c.post(url, json=payload)
        response.raise_for_status()
        body = response.json()
        if "valid" not in body:
            raise ValueError("VIES returned no validation status")
        request_date = str(body.get("requestDate") or datetime.now(timezone.utc).date())
        status = "Valid" if body["valid"] is True else "Invalid"
        return NormalizedResponse(
            provider_key=self.provider_key, indicator_code="vat_validation",
            indicator_label="EU VAT number validation", country_code=vat_number[:2],
            country_label=intent.country_label, value=status, unit="",
            observation_period=request_date, as_of=datetime.now(timezone.utc).isoformat(),
            source_url="https://ec.europa.eu/taxation_customs/vies/",
            citation_title=f"European Commission VIES — VAT validation, {request_date}",
            company_query=vat_number,
        )
