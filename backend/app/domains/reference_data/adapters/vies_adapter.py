"""
EU VIES (VAT Information Exchange System) adapter — read-only wrapper
around the European Commission's public VAT-number validation API. Free,
no API key required.

Identifier-driven: only a complete, correctly-shaped EU VAT number
(2-letter country code + digits) is ever checked — this is a validation
lookup, never a company-name search.

Nothing outside app/domains/reference_data/ should import this module
directly — see service.py for the audit-logged, cached entry point.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

_CHECK_VAT_PATH = "/check-vat-number"
_REQUEST_TIMEOUT_SECONDS = 15.0

_EU_COUNTRY_CODES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK", "XI",
}


class VIESAPIError(Exception):
    """Safe wrapper for configuration, transport, and response failures."""


async def check_vat_number(country_code: str, vat_number: str) -> dict:
    country_code = country_code.upper()
    if country_code not in _EU_COUNTRY_CODES:
        raise VIESAPIError(f"{country_code} is not a recognized EU VAT country code")

    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            base_url=settings.VIES_API_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(
                _CHECK_VAT_PATH, json={"countryCode": country_code, "vatNumber": vat_number},
            )
    except httpx.TimeoutException as exc:
        raise VIESAPIError(f"VIES API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise VIESAPIError(f"VIES API request failed: {exc}") from exc

    if response.status_code != 200:
        raise VIESAPIError(f"VIES API returned status {response.status_code}: {response.text[:200]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise VIESAPIError("VIES API returned invalid JSON") from exc

    return {
        "country_code": body.get("countryCode", country_code),
        "vat_number": body.get("vatNumber", vat_number),
        "valid": bool(body.get("valid")),
        "name": body.get("name") or "",
        "address": body.get("address") or "",
        "request_date": body.get("requestDate", ""),
    }
