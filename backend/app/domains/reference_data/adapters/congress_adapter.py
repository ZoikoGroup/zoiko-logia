"""Congress.gov API adapter for explicit US bill lookups.

The public API is not a free-text legal research service. This adapter only
accepts a concrete congress, bill type, and bill number, then retrieves the
official bill record and its latest available CRS summary. Callers must not
guess missing identifiers.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

_REQUEST_TIMEOUT_SECONDS = 15.0
_ALLOWED_BILL_TYPES = {"hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres"}


class CongressAPIError(Exception):
    """Safe wrapper for configuration, transport, and response failures."""


def normalize_bill_payload(detail_payload: dict, summaries_payload: dict) -> dict:
    """Normalize the two official response objects into one stable record."""
    bill = detail_payload.get("bill")
    if not isinstance(bill, dict):
        raise CongressAPIError("Unexpected Congress.gov bill response shape")

    summaries = summaries_payload.get("summaries", [])
    if not isinstance(summaries, list):
        raise CongressAPIError("Unexpected Congress.gov summaries response shape")
    summaries = [item for item in summaries if isinstance(item, dict)]
    summaries.sort(key=lambda item: item.get("updateDate", ""), reverse=True)
    latest_summary = summaries[0] if summaries else {}

    laws = bill.get("laws") or []
    return {
        "congress": bill.get("congress"),
        "bill_type": bill.get("type"),
        "bill_number": bill.get("number"),
        "title": bill.get("title", ""),
        "introduced_date": bill.get("introducedDate", ""),
        "latest_action": bill.get("latestAction") or {},
        "constitutional_authority_statement_text": bill.get("constitutionalAuthorityStatementText", ""),
        "policy_area": (bill.get("policyArea") or {}).get("name", ""),
        "summary": latest_summary.get("text", ""),
        "summary_date": latest_summary.get("updateDate", ""),
        "laws": laws if isinstance(laws, list) else [],
        "official_url": bill.get("url", ""),
    }


async def _get_json(path: str) -> dict:
    settings = get_settings()
    if not settings.CONGRESS_API_KEY:
        raise CongressAPIError("Congress.gov API key is not configured")

    try:
        async with httpx.AsyncClient(
            base_url=settings.CONGRESS_API_BASE_URL,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(path, params={"api_key": settings.CONGRESS_API_KEY, "format": "json"})
    except httpx.TimeoutException as exc:
        raise CongressAPIError(f"Congress.gov API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise CongressAPIError(f"Congress.gov API request failed: {exc}") from exc

    if response.status_code == 404:
        raise CongressAPIError("Congress.gov did not find the requested bill")
    if response.status_code in {401, 403}:
        raise CongressAPIError("Congress.gov API authentication failed")
    if response.status_code == 429:
        raise CongressAPIError("Congress.gov API rate limit exceeded")
    if response.status_code != 200:
        raise CongressAPIError(f"Congress.gov API returned status {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise CongressAPIError("Congress.gov returned invalid JSON") from exc


async def get_bill(congress: int, bill_type: str, bill_number: int) -> dict:
    normalized_type = bill_type.lower()
    if congress < 1 or bill_number < 1 or normalized_type not in _ALLOWED_BILL_TYPES:
        raise CongressAPIError("Invalid Congress.gov bill identifier")

    path = f"/bill/{congress}/{normalized_type}/{bill_number}"
    detail = await _get_json(path)
    summaries = await _get_json(f"{path}/summaries")
    return normalize_bill_payload(detail, summaries)
