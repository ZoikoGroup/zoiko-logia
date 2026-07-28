"""
Federal Register API adapter — read-only wrapper for looking up a single
published document by its document number (e.g. "2026-13925"). Fully
public, no API key required — unlike every other adapter in this package.

Nothing outside app/domains/reference_data/ should import this module
directly — everything goes through service.py, which gives every external
call the audit trail and caching the reference-data doctrine requires.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

_REQUEST_TIMEOUT_SECONDS = 15.0

_FIELDS = (
    "document_number", "title", "abstract", "action", "dates", "citation",
    "publication_date", "effective_on", "html_url", "cfr_references", "agencies",
)


class FederalRegisterAPIError(Exception):
    """Raised for any non-200 response (including a not-found document
    number) or transport failure — callers never see a raw httpx
    exception."""


async def get_document(document_number: str) -> dict:
    settings = get_settings()

    try:
        async with httpx.AsyncClient(
            base_url=settings.FEDERAL_REGISTER_API_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(
                f"/documents/{document_number}.json", params={"fields[]": _FIELDS}
            )
    except httpx.TimeoutException as exc:
        raise FederalRegisterAPIError(f"Federal Register API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise FederalRegisterAPIError(f"Federal Register API request failed: {exc}") from exc

    if response.status_code == 404:
        raise FederalRegisterAPIError(f"No Federal Register document found for number {document_number}")
    if response.status_code != 200:
        raise FederalRegisterAPIError(f"Federal Register API returned {response.status_code}: {response.text[:200]}")

    try:
        return response.json()
    except ValueError as exc:
        raise FederalRegisterAPIError(f"Unexpected Federal Register API response shape: {exc}") from exc
