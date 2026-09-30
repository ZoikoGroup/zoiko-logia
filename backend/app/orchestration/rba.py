"""Australia's cash rate target from the Reserve Bank of Australia's own tables.

The RBA publishes F1 "Interest Rates and Yields – Money Market" as a CSV at a
stable URL, keyless and official, and F1 is the table the RBA itself quotes
when it describes the cash rate. That makes it the Australian counterpart of
bank_of_england.py's IUDBEDR and bank_of_canada.py's V39079.

Worth noting what this is NOT: it is not a market series. The cash rate target
is a decision the RBA Board makes and holds, so the published table is a step
function — the same value repeated for weeks at a time. The connector
deliberately reports the date of the last CHANGE alongside the current level,
because a flat line on a chart is the correct picture of a policy rate and the
date is the fact people are actually asking for.

The CSV is a wide table whose columns are fixed by the RBA, and the first
column is the series date. The parser below reads by column NAME ("Cash Rate
Target") rather than by position, so an RBA reordering or adding a column
cannot silently shift every value by one — the failure mode that turns a
policy rate into a bond yield without any error being raised.
"""
from __future__ import annotations

import csv
import io
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.country_scope import is_country_scoped
from app.orchestration.websearch import WebSource

PROVIDER = "Reserve Bank of Australia"

_CSV_DEFAULT = "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv"
_PAGE_DEFAULT = "https://www.rba.gov.au/statistics/cash-rate/"

_UA_DEFAULT = "ZoikoLogia Kriton ops@zoikogroup.com"

_COUNTRY = "AU"

# The column holding the Board-decided target, not the observed overnight cash
# rate. Both are in F1 and they differ — the target is the policy decision.
_TARGET_COLUMN = "Cash Rate Target"

_HINT = re.compile(
    r"\b(?:cash\s+rate|cash\s+rate\s+target|policy\s+rate|interest\s+rate|"
    r"monetary\s+policy\s+rate|base\s+rate|official\s+rate)\b",
    re.I,
)


def _user_agent() -> str:
    return os.getenv("RBA_USER_AGENT", _UA_DEFAULT).strip() or _UA_DEFAULT


def _csv_url() -> str:
    url = os.getenv("RBA_CASH_RATE_CSV_URL", _CSV_DEFAULT).strip()
    if not url.startswith(("https://", "http://")):
        return _CSV_DEFAULT
    return url


def _definition_for_query(query: str) -> bool:
    return bool(_HINT.search(query or "")) and is_country_scoped(query, _COUNTRY)


def _parse_cash_rate(payload: str) -> list[tuple[str, float]]:
    """[(iso date, value)] from the F1 CSV payload, oldest first.

    The RBA's CSV is not a plain header-plus-data file. Its first six rows are
    a metadata preamble:

        row 0  the table title, alone in one cell
        row 1  "Title" + the column NAMES          <- the real header
        row 2  "Description" + prose per column
        row 3  "Frequency"  + Daily/as announced…
        row 4  "Type"
        row 5  "Units"
        row 6  blank
        row 7+ data: "25-Sep-2026", 4.35, …

    Handing that to a naive DictReader yields a single column named after the
    table and no cash rate at all, which is how this connector originally
    returned nothing. So the header is located by finding the "Title" row and
    the value column is located BY NAME within it, never by position — an RBA
    reordering or added column then cannot silently turn the cash rate into a
    bond yield with no error raised.

    Returns [] unless that header and column are both found, so a maintenance
    page or error body served with HTTP 200 is treated as no data.
    """
    text = (payload or "").lstrip("﻿")
    if not text.strip():
        return []
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return []

    header_index: int | None = None
    value_index: int | None = None
    for index, row in enumerate(rows[:10]):
        if not row or row[0].strip() != "Title":
            continue
        try:
            value_index = row.index(_TARGET_COLUMN)
        except ValueError:
            continue
        header_index = index
        break
    if header_index is None or value_index is None:
        return []

    points: list[tuple[str, float]] = []
    for row in rows[header_index + 1:]:
        if not row or len(row) <= value_index:
            continue
        raw_date = row[0].strip()
        raw_value = row[value_index].strip()
        if raw_date in {"", "Series", "Description", "Frequency", "Type", "Units"}:
            continue
        if raw_value in {"", ".", "NA", "N/A", "None"}:
            # A dated row with no value is a publication gap, not a zero rate —
            # the RBA publishes the current day's row before the Board
            # announces. It must never become a point on a chart at y=0.
            continue
        try:
            parsed = datetime.strptime(raw_date, "%d-%b-%Y").date()
            value = float(raw_value)
        except ValueError:
            continue
        points.append((parsed.isoformat(), value))

    points.sort(key=lambda point: point[0])
    return points


@dataclass
class CashRateMatch:
    """One matched cash-rate series — the WebSource text and the structured
    evidence are both built from THIS object."""

    series_name: str
    points: list[tuple[str, float]]
    unit: str
    url: str
    latest_change: tuple[str, str, float] | None = field(default=None)
    warning: str | None = None


async def _find_cash_rate(query: str) -> CashRateMatch | None:
    if not _definition_for_query(query):
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": _user_agent()}) as client:
            response = await client.get(_csv_url())
            response.raise_for_status()
            points = _parse_cash_rate(response.text)
    except Exception:
        return None
    if not points:
        return None

    latest_change: tuple[str, str, float] | None = None
    for earlier, later in zip(points, points[1:]):
        if earlier[1] != later[1]:
            latest_change = (earlier[0], later[0], later[1] - earlier[1])

    return CashRateMatch(
        series_name="RBA Cash Rate Target",
        points=points,
        unit="%",
        url=_PAGE_DEFAULT,
        latest_change=latest_change,
    )


def _build_source(match: CashRateMatch) -> WebSource:
    latest_date, latest_value = match.points[-1]
    lines = [
        f"Reserve Bank of Australia {match.series_name}, the official Australian policy rate "
        f"decided by the RBA Board, from RBA statistical table F1. "
        f"{latest_date}: {latest_value:g}%.",
    ]
    if match.latest_change:
        held_from, changed_on, delta = match.latest_change
        direction = "up" if delta > 0 else "down"
        lines.append(
            f"Most recent change: held at the previous rate from {held_from} and "
            f"moved {direction} {abs(delta):g} percentage points on {changed_on}."
        )
    lines.append(
        f"{len(match.points)} published observations retrieved, "
        f"{match.points[0][0]} to {latest_date}."
    )
    if match.warning:
        lines.append(match.warning)
    return WebSource(
        title=f"Reserve Bank of Australia — {match.series_name} ({latest_date})",
        url=match.url,
        snippet=" ".join(lines),
        provider=PROVIDER,
        freshness="daily",
        series=match.points,
        observation=LiveObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            indicator=match.series_name, value=str(latest_value), unit="%",
            period=latest_date, provider=PROVIDER, source_url=match.url,
            freshness="daily",
        ),
    )
