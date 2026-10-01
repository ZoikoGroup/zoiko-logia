"""Australian headline CPI and unemployment from the ABS's own data API.

This connector exists because Australia was the worst wrong-data case found in
the live audit, and the cause was structural rather than a bad pattern:

  - "Australia CPI" returned ABS *energy* inflation, because IMF/CPI — the
    source every other country's CPI query resolves to — publishes NO
    Australian series at all, so the query fell through to DBnomics full-text
    search and took whatever ranked first.
  - "Australia GDP" returned a trade-balance-over-GDP ratio for the same
    reason, and "Australia unemployment" returned an unrelated demographic
    series.

So the fix is not a better regex, it is a real connector to the national
statistical agency. The ABS Data API is keyless, official, and returns exactly
the headline aggregates published in the Monthly CPI Indicator and the
Labour Force Australia releases.

THE KEY QUESTION — which series is "the" Australian CPI?

The ABS CPI dataflow carries a 15,000-row cube of every city, every component
and every sub-index. There is no row called "Australian inflation". The
national headline is a specific published aggregate, and picking the wrong one
of several near-identical candidates reproduces the original bug in a new
place. In CPI_Q the national all-groups figure is INDEX 999903 (the
"weighted average of eight capital cities" aggregate, ABS's own construction
of a national number), and MEASURE 3 is the year-on-year percentage change —
which is the number a person asking "what is Australian inflation" means.

Both are pinned as explicit constants below with the ABS's own index codes, and
the connector asserts it received the aggregate it asked for rather than
assuming the response matched the request.

A note on the other ABS API: the ABS *Indicator* API (api.data.abs.gov.au) is
the tidier interface but requires a registered key and answers 403 without
one. The Data API used here (data.api.abs.gov.au) covers the same statistics
with no credential at all, so no key is required for any Australian figure
this product serves.
"""
from __future__ import annotations

import csv
import io
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.country_scope import is_country_scoped
from app.orchestration.websearch import WebSource

PROVIDER = "Australian Bureau of Statistics"

_BASE_DEFAULT = "https://data.api.abs.gov.au"

_UA_DEFAULT = "ZoikoLogia Kriton ops@zoikogroup.com"

_COUNTRY = "AU"

# ── Series definitions ──────────────────────────────────────────────────────
# Each entry pins the ABS dataflow plus the exact key within it. The key is
# MEASURE.INDEX.TSEST.REGION.FREQ, and the "all" tail is deliberately NOT used:
# requesting the whole cube returns tens of thousands of rows of which exactly
# one is the national headline, so the request names it directly.
#
#   CPI_Q  MEASURE 3, INDEX 999903 — all groups, weighted average of the eight
#          capital cities, year-on-year % change. TSEST 20 is "Percentage
#          change from corresponding period of previous year"; REGION 50 is
#          Australia; FREQ Q is quarterly.
_INFLATION_KEY = "3.999903.20.50.Q"
#   LF     MEASURE M15, SEX 3, AGE 1599, TSEST 10, REGION AUS — the
#          unemployment RATE for Persons aged 15 and over, Australia, monthly.
#          Each code was read off the ABS's own response rather than guessed:
#          SEX 3 is Persons (1/2 are the male/female splits), AGE 1599 is the
#          15-and-over aggregate, TSEST 10 is the plain monthly rate (20 and
#          30 are the annual and quarterly resamplings), and REGION is spelled
#          "AUS" here — unlike CPI_Q, where it is the numeric 50.
#          M15 is specifically the RATE; M14 is the female-specific rate and
#          M2/M5 are unemployment LEVELS in thousands, so picking by code
#          rather than by meaning is exactly how the wrong one gets returned.
_UNEMPLOYMENT_KEY = "M15.3.1599.10.AUS.M"

_INFLATION = {
    "dataflow": "CPI_Q",
    "key": _INFLATION_KEY,
    "name": "Australian Consumer Price Index, All Groups (year-on-year change)",
    "unit": "%",
    "url": "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/latest-release",
    "frequency": "quarterly",
}
_UNEMPLOYMENT = {
    "dataflow": "LF",
    "key": _UNEMPLOYMENT_KEY,
    "name": "Australian Unemployment Rate",
    "unit": "%",
    "url": "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/latest-release",
    "frequency": "monthly",
}

_INFLATION_HINT = re.compile(
    r"\b(?:cpi|consumer price(?: index)?|inflation|cost of living|headline inflation)\b", re.I,
)
_UNEMPLOYMENT_HINT = re.compile(
    r"\b(?:unemployment|unemployed|jobless(?:ness)?|labou?r force)\b", re.I,
)


def _user_agent() -> str:
    return os.getenv("ABS_USER_AGENT", _UA_DEFAULT).strip() or _UA_DEFAULT


def _base() -> str:
    base = os.getenv("ABS_API_BASE_URL", _BASE_DEFAULT).strip().rstrip("/")
    if "=" in base or not base.startswith(("https://", "http://")):
        return _BASE_DEFAULT
    return base


def _definition_for_query(query: str) -> dict | None:
    """The single ABS series this question is about, or None to stay silent.

    Deliberately narrow. ABS covers a great deal more than these two series, and
    this connector exists to replace specific wrong answers, not to become a
    general ABS client — an over-broad match would attach an Australian number
    to questions that were never about it.
    """
    if not is_country_scoped(query, _COUNTRY):
        return None
    if _INFLATION_HINT.search(query or ""):
        return _INFLATION
    if _UNEMPLOYMENT_HINT.search(query or ""):
        return _UNEMPLOYMENT
    return None


def _parse_abs_csv(payload: str) -> list[tuple[str, float]]:
    """[(period, value)] from an ABS Data API CSV response, oldest first.

    The ABS returns a TIME_PERIOD column in either "2026-Q2" (quarterly) or
    "2026-09" (monthly) form. Both are kept as-is: they are ABS's own period
    labels, and normalising them to an ambiguous ISO date would lose the
    distinction between a quarterly and a monthly observation.
    """
    text = (payload or "").strip()
    if not text:
        return []
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or "TIME_PERIOD" not in reader.fieldnames or "OBS_VALUE" not in reader.fieldnames:
            return []
        points: list[tuple[str, float]] = []
        for row in reader:
            period = str(row.get("TIME_PERIOD") or "").strip()
            raw_value = str(row.get("OBS_VALUE") or "").strip()
            if not period or raw_value in {"", ".", "NA", "N/A", "None"}:
                continue
            try:
                points.append((period, float(raw_value)))
            except ValueError:
                continue
    except csv.Error:
        return []
    points.sort(key=lambda point: point[0])
    return points


@dataclass
class AbsSeriesMatch:
    """One matched ABS series — WebSource text and evidence both built from it."""

    series_name: str
    points: list[tuple[str, float]]
    unit: str
    url: str
    dataflow: str
    key: str
    frequency: str


async def _find_abs_series(query: str) -> AbsSeriesMatch | None:
    definition = _definition_for_query(query)
    if definition is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": _user_agent()}) as client:
            response = await client.get(
                f"{_base()}/rest/data/ABS,{definition['dataflow']},1.0.0/{definition['key']}",
                params={"lastNObservations": "40", "format": "csv"},
            )
            response.raise_for_status()
            points = _parse_abs_csv(response.text)
    except Exception:
        return None
    if not points:
        return None

    return AbsSeriesMatch(
        series_name=definition["name"],
        points=points,
        unit=definition["unit"],
        url=definition["url"],
        dataflow=definition["dataflow"],
        key=definition["key"],
        frequency=definition["frequency"],
    )


def _build_source(match: AbsSeriesMatch) -> WebSource:
    latest_period, latest_value = match.points[-1]
    lines = [
        f"Australian Bureau of Statistics — {match.series_name}, from dataflow "
        f"{match.dataflow} (series key {match.key}). This is the ABS national "
        f"all-groups aggregate, not a city or component sub-index. "
        f"{latest_period}: {latest_value:g}{match.unit}.",
        f"{len(match.points)} published observations retrieved, "
        f"{match.points[0][0]} to {latest_period}.",
    ]
    return WebSource(
        title=f"ABS — {match.series_name} ({latest_period})",
        url=match.url,
        snippet=" ".join(lines),
        provider=PROVIDER,
        freshness=match.frequency,
        series=match.points,
        observation=LiveObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            indicator=match.series_name, value=str(latest_value), unit=match.unit,
            period=latest_period, provider=PROVIDER, source_url=match.url,
            freshness=match.frequency,
        ),
    )
