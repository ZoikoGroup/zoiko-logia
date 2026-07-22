"""
Frankfurter connector — fully keyless, ECB-sourced daily FX rates.
indicator_code on the intent is "{FROM}_{TO}" (e.g. "USD_GBP") — see
live_sources/classifier.py's detect_fx_intent().

Note: the historical api.frankfurter.app host now 301-redirects to
api.frankfurter.dev/v1 (confirmed live) — the default base URL points at
the new host directly, and follow_redirects=True is set defensively in
case of a future redirect (httpx does not follow redirects by default).
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


class FrankfurterConnector(LiveSourceConnector):
    provider_key = "frankfurter"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        from_code, _, to_code = intent.indicator_code.partition("_")
        if not from_code or not to_code:
            raise ValueError(f"Frankfurter connector got a malformed currency pair: {intent.indicator_code!r}")

        if client is not None:
            response = await client.get(
                f"{self.base_url}/latest", params={"from": from_code, "to": to_code}
            )
        else:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
                response = await c.get(
                    f"{self.base_url}/latest", params={"from": from_code, "to": to_code}
                )
        response.raise_for_status()
        body = response.json()

        rate = (body.get("rates") or {}).get(to_code)
        if rate is None:
            raise ValueError(f"Frankfurter API returned no rate for {from_code}->{to_code}")

        date = body.get("date", "unknown")

        return NormalizedResponse(
            provider_key=self.provider_key,
            indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label,
            country_code=intent.country_code,
            country_label=intent.country_label,
            value=rate,
            unit=to_code,
            observation_period=date,
            as_of=datetime.now(timezone.utc).isoformat(),
            source_url=f"{self.base_url}/latest?from={from_code}&to={to_code}",
            citation_title=f"Frankfurter (ECB) — {from_code}/{to_code} exchange rate, {date}",
        )
