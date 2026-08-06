"""
Regulations.gov (api.regulations.gov) adapter — read-only wrapper around the
public federal rulemaking-docket API. Free, keyed via REGULATIONS_GOV_API_KEY
(app/core/config.py / backend/.env).

Identifier-driven, same posture as congress_adapter.py: only a complete,
correctly-formatted docket ID (e.g. "IRS-2014-0019") resolves to a real
docket — this is never a free-text regulatory search that could surface an
unrelated docket as if it were the one asked about.

Nothing outside app/domains/reference_data/ should import this module
directly — see service.py for the audit-logged, cached entry point.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

_REQUEST_TIMEOUT_SECONDS = 15.0


class RegulationsGovAPIError(Exception):
    """Safe wrapper for configuration, transport, and response failures."""


async def get_docket(docket_id: str) -> dict:
    settings = get_settings()
    if not settings.REGULATIONS_GOV_API_KEY:
        raise RegulationsGovAPIError("Regulations.gov API key is not configured")

    try:
        async with httpx.AsyncClient(
            base_url=settings.REGULATIONS_GOV_API_BASE_URL,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(
                f"/dockets/{docket_id}", params={"api_key": settings.REGULATIONS_GOV_API_KEY}
            )
    except httpx.TimeoutException as exc:
        raise RegulationsGovAPIError(f"Regulations.gov API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise RegulationsGovAPIError(f"Regulations.gov API request failed: {exc}") from exc

    if response.status_code == 404:
        raise RegulationsGovAPIError("Regulations.gov did not find the requested docket")
    if response.status_code in {401, 403}:
        raise RegulationsGovAPIError("Regulations.gov API authentication failed")
    if response.status_code == 429:
        raise RegulationsGovAPIError("Regulations.gov API rate limit exceeded")
    if response.status_code != 200:
        raise RegulationsGovAPIError(f"Regulations.gov API returned status {response.status_code}")

    try:
        payload = response.json()
        data = payload["data"]
        if not isinstance(data, dict):
            raise KeyError("data")
    except (ValueError, KeyError) as exc:
        raise RegulationsGovAPIError("Unexpected Regulations.gov docket response shape") from exc

    attributes = data.get("attributes") or {}
    return {
        "docket_id": data.get("id", docket_id),
        "title": attributes.get("title", ""),
        "agency_id": attributes.get("agencyId", ""),
        "docket_type": attributes.get("docketType", ""),
        "abstract": attributes.get("dkAbstract", ""),
        "rin": attributes.get("rin", ""),
        "modify_date": attributes.get("modifyDate", ""),
        "keywords": attributes.get("keywords") or [],
    }
