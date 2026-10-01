"""Irish CPI and unemployment from the Central Statistics Office of Ireland.

The CSO publishes on PxStat, its own statistical publishing platform, which
serves JSON-stat 2.0 over a public REST endpoint with no credential. CPM01 is
the monthly Consumer Price Index — the table the CSO itself headlines.

The other Irish figures a finance question reaches for come from the same
platform under different table codes. They are listed below as data rather
than guessed at call time, and any code that does not resolve to a real table
yields no data rather than a plausible-looking substitute.

Ireland's GDP and policy rate are deliberately NOT here. Ireland is a euro
member, so its harmonised HICP and the ECB's own rate for the euro area are
authoritative and already reachable (dbnomics.py, frankfurter.py), and
Ireland's policy rate IS the ECB's — there is no Irish national rate to
publish. Reporting an "Irish interest rate" that is not the ECB's would be
inventing a statistic.

The CSO answers an unknown table code with a JSON body carrying HTTP 404, and
some table codes exist but hold no Irish observations. Both are treated as "no
data" rather than surfaced, so a question this connector cannot really answer
falls through to the other sources rather than returning a wrong number.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.country_scope import is_country_scoped
from app.orchestration.websearch import WebSource

PROVIDER = "Central Statistics Office of Ireland"

_BASE_DEFAULT = "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset"

_UA_DEFAULT = "ZoikoLogia Kriton ops@zoikogroup.com"

_COUNTRY = "IE"


def _user_agent() -> str:
    return os.getenv("CSO_USER_AGENT", _UA_DEFAULT).strip() or _UA_DEFAULT


def _base() -> str:
    base = os.getenv("CSO_API_BASE_URL", _BASE_DEFAULT).strip().rstrip("/")
    if "=" in base or not base.startswith(("https://", "http://")):
        return _BASE_DEFAULT
    return base


# CPM01 is the CSO's headline monthly CPI (National, All Groups). CPM16 is the
# annual-average CPI. Both are queried only when the question's own wording
# picks them, so "annual CPI" and "monthly CPI" do not return the same table.
_SERIES = {
    "CPM01": {
        "name": "Irish Consumer Price Index, All Groups",
        "frequency": "monthly",
        "url": "https://www.cso.ie/en/statistics/consumerpriceindex/",
    },
    "CPM16": {
        "name": "Irish Consumer Price Index, Annual Average",
        "frequency": "annual",
        "url": "https://www.cso.ie/en/statistics/consumerpriceindex/",
    },
}

_INFLATION_HINT = re.compile(
    r"\b(?:cpi|consumer price(?: index)?|inflation|cost of living|hicp)\b", re.I,
)
_ANNUAL_HINT = re.compile(r"\b(?:annual(?:ly)?|year(?:ly)? average|average for the year)\b", re.I)

# PxStat uses ISO-8601 period labels: "197511" for a monthly period. Kept as the
# CSO publishes them, reformatted to "1975-11" for readability on a chart axis.
_PERIOD_MONTH = re.compile(r"^(\d{4})(0[1-9]|1[0-2])$")
_PERIOD_QUARTER = re.compile(r"^(\d{4})Q([1-4])$")

# The base year in a CPI statistic label, e.g. "Base Dec 2023=100" -> 2023.
# Ireland rebases its CPI every few years and PxStat then publishes the SAME
# history under every base it has ever used, so the table arrives carrying
# eight parallel statistics. The newest rebasing is the one the CSO headlines
# and the only one still being updated; the older ones are frozen archives.
_BASE_YEAR = re.compile(r"base\s+\w+\s+(\d{4})\s*=\s*100", re.I)


def _definition_for_query(query: str) -> str | None:
    if not is_country_scoped(query, _COUNTRY):
        return None
    if not _INFLATION_HINT.search(query or ""):
        return None
    return "CPM16" if _ANNUAL_HINT.search(query or "") else "CPM01"


def _normalise_period(raw: str) -> str | None:
    """Turn a PxStat period label into a readable one, or None if unrecognised.

    Only the period forms the CSO actually uses for these tables are accepted.
    An unrecognised label is dropped rather than passed through, so an internal
    CSO code can never appear on a chart axis as though it were a date.
    """
    label = (raw or "").strip()
    quarter = _PERIOD_QUARTER.match(label)
    if quarter:
        return f"{quarter.group(1)}-Q{quarter.group(2)}"
    month = _PERIOD_MONTH.match(label)
    if month:
        return f"{month.group(1)}-{month.group(2)}"
    if re.fullmatch(r"\d{4}", label):
        return label
    return None


def _category_entries(dimension: dict) -> list[tuple[str, str]]:
    """[(code, label)] for one PxStat dimension, in the order PxStat defines.

    PxStat is inconsistent about whether the category index is a list or a map,
    and both appear across its tables, so both are normalised here. Order is
    load-bearing: the `value` array is a flat row-major array indexed by
    position, not by code.
    """
    category = (dimension.get("category") or {})
    index = category.get("index")
    labels = category.get("label") or {}
    if isinstance(index, list):
        return [(str(code), str(labels.get(code, code))) for code in index]
    if isinstance(index, dict):
        return [(str(code), str(labels.get(code, code))) for code in index]
    return []


def _parse_jsonstat(payload: dict, *, want_change: bool) -> list[tuple[str, float]]:
    """[(period, value)] for the Irish national all-groups CPI.

    A PxStat table is a cube of every statistic x period x category, and the
    national all-groups headline is ONE cell-slice of it. Choosing that slice
    correctly is the entire job, and two of the choices are genuinely
    ambiguous, so each is made by reading a LABEL rather than a position:

      - which STATISTIC: Ireland rebases CPI periodically, so the table carries
        eight parallel statistics all covering the same history under different
        base years (CPM01C01 "Base Dec 2001=100" through CPM01C08 "Base Dec
        2023=100"). Only the newest is live; the rest are frozen archives.
        Taking index 0 would have returned a series frozen in 2016.
      - which CATEGORY: the "-"/"All items" slice, not one of the twelve
        components (Food, Housing, …) that follow it.

    Neither is assumed to be first, and a table whose shape does not match
    these expectations yields no data rather than a plausible substitute.
    """
    if not isinstance(payload, dict) or payload.get("class") != "dataset":
        return []
    dimension = payload.get("dimension") or {}
    if "STATISTIC" not in dimension:
        return []
    raw_values = payload.get("value")
    if not isinstance(raw_values, list) or not raw_values:
        return []

    statistics = _category_entries(dimension["STATISTIC"])
    if not statistics:
        return []

    def base_year(entry: tuple[str, str]) -> int:
        found = _BASE_YEAR.search(entry[1])
        return int(found.group(1)) if found else -1

    # The live rebasing is the newest base year; -1 entries (no parseable base)
    # lose to any real one.
    stat_pos, _ = max(enumerate(statistics), key=lambda item: base_year(item[1]))
    if base_year(statistics[stat_pos]) < 0:
        return []

    # The time dimension is whichever one carries month/year period codes.
    time_key = None
    time_entries: list[tuple[str, str]] = []
    for key, value in dimension.items():
        if key == "STATISTIC":
            continue
        entries = _category_entries(value)
        if entries and any(_normalise_period(code) for code, _ in entries):
            time_key, time_entries = key, entries
            break
    if time_key is None:
        return []

    # Every remaining dimension is a category slice; the aggregate is the one
    # the CSO labels as all items / all groups, falling back to the CSO's own
    # "-" code.
    category_key = next(
        (key for key in dimension if key not in {"STATISTIC", time_key}), None
    )
    category_entries = _category_entries(dimension[category_key]) if category_key else []
    if category_entries:
        cat_pos = next(
            (
                index for index, (_, label) in enumerate(category_entries)
                if label.strip().lower() in {"all items", "all groups", "-"}
            ),
            0,
        )
        cat_size = len(category_entries)
    else:
        cat_pos, cat_size = 0, 1

    time_size = len(time_entries)
    points: list[tuple[str, float]] = []
    for time_pos, (code, _) in enumerate(time_entries):
        period = _normalise_period(code)
        if period is None:
            continue
        flat = (stat_pos * time_size + time_pos) * cat_size + cat_pos
        if flat >= len(raw_values):
            continue
        value = raw_values[flat]
        # A rebased series has no observations before its own base month, and
        # the CSO pads those with null. Null is missing data, not a zero CPI.
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        points.append((period, float(value)))

    points.sort(key=lambda point: point[0])
    if not points or not want_change:
        return points
    return _to_year_on_year(points)


def _to_year_on_year(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Convert a monthly CPI index level to a year-on-year percentage change.

    A CPI question means inflation, not an index number, and PxStat publishes
    the index level. The change is computed only where a like period exists
    exactly twelve months earlier — never interpolated, and never matched to a
    shorter gap, which would silently turn a quarterly gap into an annual one.
    """
    by_period = dict(points)
    out: list[tuple[str, float]] = []
    for period, value in points:
        match = re.fullmatch(r"(\d{4})-(\d{2})", period)
        if not match:
            continue
        year, month = int(match.group(1)), match.group(2)
        prior = f"{year - 1}-{month}"
        base = by_period.get(prior)
        if base in (None, 0):
            continue
        out.append((period, round((value / base - 1) * 100, 4)))
    return out


@dataclass
class CsoSeriesMatch:
    """One matched CSO series — WebSource text and evidence both built from it."""

    series_name: str
    table_code: str
    points: list[tuple[str, float]]
    unit: str
    url: str
    frequency: str


async def _find_cso_series(query: str) -> CsoSeriesMatch | None:
    table_code = _definition_for_query(query)
    if table_code is None:
        return None
    definition = _SERIES[table_code]
    wants_change = bool(re.search(r"\binflation\b", query or "", re.I)) or definition["frequency"] == "monthly"

    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": _user_agent()}) as client:
            response = await client.get(f"{_base()}/{table_code}/JSON-stat/2.0/en")
            response.raise_for_status()
            payload = response.json()
            points = _parse_jsonstat(payload, want_change=wants_change)
    except Exception:
        return None
    if not points:
        return None

    # Keep the series to a readable recent window rather than the table's whole
    # history, which for a CPI running since the 1980s is thousands of points.
    points = points[-60:]

    return CsoSeriesMatch(
        series_name=definition["name"],
        table_code=table_code,
        points=points,
        unit="%" if wants_change else "index (base year as published)",
        url=definition["url"],
        frequency=definition["frequency"],
    )


def _build_source(match: CsoSeriesMatch) -> WebSource:
    latest_period, latest_value = match.points[-1]
    lines = [
        f"Central Statistics Office of Ireland — {match.series_name}, from CSO PxStat table "
        f"{match.table_code} (national, all groups). {latest_period}: {latest_value:g}{match.unit}.",
        f"{len(match.points)} published observations retrieved, "
        f"{match.points[0][0]} to {latest_period}.",
    ]
    return WebSource(
        title=f"CSO Ireland — {match.series_name} ({latest_period})",
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
