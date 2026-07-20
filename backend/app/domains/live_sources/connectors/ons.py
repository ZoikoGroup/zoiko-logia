"""
ONS (Office for National Statistics) connector — https://api.beta.ons.gov.uk/v1.
Fully keyless. Supports three indicators, each an index/rate value (not
always a plain percentage — see per-indicator notes below):
  - CP00: CPIH "Overall Index" (dataset cpih01) — an index value
    (base 2015=100), NOT the 12-month percentage inflation rate. The
    %-rate series lives in a different ONS dataset that hasn't been
    located yet — do not relabel this as "the inflation rate" upstream.
  - A--T: Monthly GDP (dataset gdp-to-four-decimal-places) — an index
    value (seasonally adjusted, base 2016=100), not a currency figure.
  - UNEMPLOYMENT_RATE: unemployment rate, 16+, all adults, seasonally
    adjusted (dataset labour-market) — a genuine percentage.

Unlike World Bank's single-call fetch, ONS requires two requests:
1. GET /datasets/{id} to resolve links.latest_version.href — ONS increments
   dataset versions/editions over time and has no stable "latest" URL
   alias (the edition segment itself varies per dataset, e.g. "time-series"
   for cpih01/GDP vs "PWT24" for labour-market — resolved dynamically here,
   never hardcoded).
2. GET {latest_version_href}/observations?time=*&geography=...&<dims> —
   returns all time periods; there's no mrnev-equivalent server-side "give
   me only the most recent" param, so the most-recent value is picked
   client-side.

Two different time-label formats are in play: cpih01/GDP use "Mon-YY"
(e.g. "Jan-26"); labour-market uses rolling 3-month windows (e.g.
"oct-dec-2022") — sorted by (year, end-month) since ONS's convention
labels a rolling window by its completion year. This is the most fragile
part of this connector — flagged for a dedicated look if unemployment
figures ever look off by ~a year.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse

_UK_GEOGRAPHY_CODE = "K02000001"

_MONTH_INDEX = {
    name: i for i, name in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
    )
}

# Per-indicator dataset + extra query dimensions. Confirmed against the live
# API this session — see this module's docstring and
# app/domains/live_sources/classifier.py for how each indicator_code is
# reached.
_INDICATOR_CONFIG: dict[str, dict] = {
    "CP00": {
        "dataset_id": "cpih01",
        "extra_params": {"aggregate": "CP00"},
        "time_format": "mon-yy",
    },
    "A--T": {
        "dataset_id": "gdp-to-four-decimal-places",
        "extra_params": {"unofficialstandardindustrialclassification": "A--T"},
        "time_format": "mon-yy",
    },
    "UNEMPLOYMENT_RATE": {
        "dataset_id": "labour-market",
        "extra_params": {
            "unitofmeasure": "rates",
            "economicactivity": "unemployed",
            "agegroups": "16+",
            "sex": "all-adults",
            "seasonaladjustment": "seasonal-adjustment",
        },
        "time_format": "rolling-3-month",
    },
}


def _mon_yy_sort_key(period_id: str) -> datetime:
    return datetime.strptime(period_id, "%b-%y")


def _rolling_3_month_sort_key(period_id: str) -> tuple[int, int]:
    # e.g. "oct-dec-2022" -> end month "dec", year "2022". ONS labels a
    # rolling window by its completion year, so no special-case handling
    # is needed for windows that cross a calendar year boundary (e.g.
    # "nov-jan-2022" = Nov 2021-Jan 2022, sorted as (2022, January)).
    parts = period_id.split("-")
    end_month, year = parts[-2], int(parts[-1])
    return (year, _MONTH_INDEX.get(end_month, 0))


class ONSConnector(LiveSourceConnector):
    provider_key = "ons"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float) -> NormalizedResponse:
        config = _INDICATOR_CONFIG.get(intent.indicator_code)
        if config is None:
            raise ValueError(f"ONS connector has no dataset mapping for indicator {intent.indicator_code}")

        dataset_id = config["dataset_id"]

        async with httpx.AsyncClient(timeout=timeout) as client:
            dataset_response = await client.get(f"{self.base_url}/datasets/{dataset_id}")
            dataset_response.raise_for_status()
            # links.latest_version.href points at the version metadata
            # resource itself, not its /observations sub-resource — the
            # actual data query needs that suffix appended.
            latest_version_href = dataset_response.json()["links"]["latest_version"]["href"]
            observations_url = f"{latest_version_href}/observations"

            observations_response = await client.get(
                observations_url,
                params={"time": "*", "geography": _UK_GEOGRAPHY_CODE, **config["extra_params"]},
            )
            observations_response.raise_for_status()
            body = observations_response.json()

        observations = body.get("observations") or []
        if not observations:
            raise ValueError(f"ONS API returned no observations for {dataset_id}/{intent.indicator_code}")

        sort_key = _mon_yy_sort_key if config["time_format"] == "mon-yy" else _rolling_3_month_sort_key
        latest = max(observations, key=lambda obs: sort_key(obs["dimensions"]["Time"]["id"]))
        value = latest.get("observation")
        if value is None:
            raise ValueError(f"ONS API has no non-empty observation for {dataset_id}/{intent.indicator_code}")

        period_label = latest["dimensions"]["Time"].get("label") or latest["dimensions"]["Time"]["id"]
        unit = body.get("unit_of_measure", "")

        return NormalizedResponse(
            provider_key=self.provider_key,
            indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label,
            country_code=intent.country_code,
            country_label=intent.country_label,
            value=value,
            unit=unit,
            observation_period=period_label,
            as_of=datetime.now(timezone.utc).isoformat(),
            source_url=latest_version_href,
            citation_title=f"ONS — {intent.country_label}, {intent.indicator_label}, {period_label} ({unit})",
        )
