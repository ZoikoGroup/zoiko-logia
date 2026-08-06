"""
UK Office for National Statistics (ONS) API adapter — read-only wrapper
around the two headline UK economic series this product needs: CPIH
(Consumer Prices Index including owner occupiers' housing costs, the UK's
official headline inflation measure) and monthly GDP.

Free, no API key required. Unlike BLS/FRED (a single flat series id), ONS's
v1 API is dataset -> edition -> version -> observations, with dataset-
specific dimension codes (geography, aggregate/industry classification) —
each series below carries its own confirmed-working dimension filters
rather than guessing a generic shape.

Nothing outside app/domains/reference_data/ should import this module
directly — see service.py for the audit-logged, cached entry point.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from app.core.config import get_settings

_REQUEST_TIMEOUT_SECONDS = 15.0

# (dataset_id, dimension filters) — confirmed live against the real API.
# "CP00" is CPIH's own code for the headline "All items" aggregate;
# "A--T" is the GDP dataset's own code for the whole-economy "Monthly GDP"
# series — neither is guessable from the dataset id alone, both were
# resolved against the dataset's own dimension-options endpoint.
_CPIH_DATASET = "cpih01"
_CPIH_DIMENSIONS = {"geography": "K02000001", "aggregate": "CP00"}
_GDP_DATASET = "gdp-to-four-decimal-places"
_GDP_DIMENSIONS = {"geography": "K02000001", "unofficialstandardindustrialclassification": "A--T"}


class ONSAPIError(Exception):
    """Safe wrapper for configuration, transport, and response failures."""


async def _get_json(url: str, params: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
    except httpx.TimeoutException as exc:
        raise ONSAPIError(f"ONS API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise ONSAPIError(f"ONS API request failed: {exc}") from exc

    if response.status_code != 200:
        raise ONSAPIError(f"ONS API returned status {response.status_code}: {response.text[:200]}")
    try:
        return response.json()
    except ValueError as exc:
        raise ONSAPIError("ONS API returned invalid JSON") from exc


async def _latest_version(dataset_id: str) -> int:
    base_url = get_settings().ONS_API_BASE_URL
    editions = await _get_json(f"{base_url}/datasets/{dataset_id}/editions", {})
    items = editions.get("items") or []
    if not items:
        raise ONSAPIError(f"ONS dataset {dataset_id} has no published editions")
    version_id = items[0].get("links", {}).get("latest_version", {}).get("id")
    if not version_id:
        raise ONSAPIError(f"ONS dataset {dataset_id} has no latest version link")
    return int(version_id)


async def _monthly_series(dataset_id: str, dimensions: dict) -> list[tuple[datetime, float]]:
    """Returns every (month, value) observation, sorted oldest to newest.
    ONS returns rows in no guaranteed order, so this module owns the sort
    rather than trusting the API's own response ordering."""
    base_url = get_settings().ONS_API_BASE_URL
    version = await _latest_version(dataset_id)
    params = {"time": "*", **dimensions}
    payload = await _get_json(
        f"{base_url}/datasets/{dataset_id}/editions/time-series/versions/{version}/observations", params,
    )
    observations = payload.get("observations") or []
    if not observations:
        raise ONSAPIError(f"ONS dataset {dataset_id} returned no observations for {dimensions}")

    parsed: list[tuple[datetime, float]] = []
    for obs in observations:
        label = (obs.get("dimensions") or {}).get("Time", {}).get("label", "")
        raw_value = obs.get("observation")
        try:
            month = datetime.strptime(label, "%b-%y")
            value = float(raw_value)
        except (ValueError, TypeError):
            continue
        parsed.append((month, value))
    if not parsed:
        raise ONSAPIError(f"ONS dataset {dataset_id} returned no parseable observations")
    parsed.sort(key=lambda pair: pair[0])
    return parsed


async def get_cpih_series() -> list[tuple[datetime, float]]:
    """UK headline CPIH index, oldest to newest. The 12-month percentage
    change between the latest and same-month-prior-year values is the
    standard UK inflation-rate figure — computed by the caller, same
    posture as bls_adapter.py leaving the year-over-year math to
    reference_data/service.py rather than this adapter."""
    return await _monthly_series(_CPIH_DATASET, _CPIH_DIMENSIONS)


async def get_gdp_index_series() -> list[tuple[datetime, float]]:
    """UK monthly GDP index (not a currency-denominated total — ONS
    publishes this series as an index number), oldest to newest."""
    return await _monthly_series(_GDP_DATASET, _GDP_DIMENSIONS)
