"""UK Bank Rate from the Bank of England's own statistical database.

DBnomics and FRED between them cover the US and most of the world, and
Frankfurter covers currency — but the one rate a UK finance product is asked
for most, the Bank Rate, came back empty from every one of them. It is
published by the Bank of England in its own IADB database, keyless, and
already returns a clean dated series.

Worth stating plainly why this is a separate module rather than another row in
fred.py: FRED is a Federal Reserve publication and its connector refuses any
question that does not name the United States. That guard is correct there and
would be wrong here, so a UK policy rate has to arrive through its own door.

The IADB answers an unknown SeriesCodes with an HTML error page and HTTP 200,
so a response is accepted only if it parses as the CSV it claims to be. A
Bank Rate history is also read-only in the sense that matters here — a change
in Bank Rate moves real discounting and financing figures — so a series is
never silently truncated: if the request asked for a window and the response
does not cover it, that gap is carried on the source.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.number_words import SPELLED_NUMBER_PATTERN, spelled_number_to_int
from app.orchestration.uk_scope import is_uk_scoped
from app.orchestration.websearch import WebSource

PROVIDER = "Bank of England"

_BASE_DEFAULT = "https://www.bankofengland.co.uk/boeapps/database"

# The BoE's CDN (Akamai) answers httpx's default User-Agent with a 403
# "Access Denied" page, so an identifying one is required to get a response at
# all. Unlike the SEC this is not an access-policy identifier, so a working
# default ships in the code and the env var only exists to override the
# contact details.
_UA_DEFAULT = "ZoikoLogia Kriton ops@zoikogroup.com"


def _user_agent() -> str:
    return os.getenv("BOE_USER_AGENT", _UA_DEFAULT).strip() or _UA_DEFAULT

# "Bank Rate" is the name of the UK policy rate since March 2024. Before that
# it was "Bank Base Rate" / "Base Rate", and users still ask for both, so the
# gate has to cover the older names or the most common phrasing silently fails.
_HINT = re.compile(
    r"\b(?:bank\s+rate|base\s+rate|policy\s+rate|interest\s+rate|discount\s+rate)\b", re.I,
)
# Whether this question may be answered with a UK-only series. The country list
# lives in uk_scope.py because govuk.py needs the identical decision.
_YEAR_SPAN = re.compile(
    rf"\b(?:last|past|over)\s+(?P<count>\d+|{SPELLED_NUMBER_PATTERN})\s+years?\b", re.I,
)

# IUDBEDR is the Bank of England's official Bank Rate series, published each
# business morning. IADB returns 200 with an HTML error page for an unknown
# code, which is why _series_titles() validates the response below.
_SERIES = {
    "IUDBEDR": "UK Bank Rate",
}


def _base() -> str:
    base = os.getenv("BOE_API_BASE_URL", _BASE_DEFAULT).strip().rstrip("/")
    if "=" in base or not base.startswith(("https://", "http://")):
        return _BASE_DEFAULT
    return base


def _definition_for_query(query: str) -> str | None:
    if not _HINT.search(query or ""):
        return None
    # "US bank rate" and "India base rate" both contain the literal words this
    # connector matches on, so without the scope check it would return the UK
    # Bank Rate to someone who had explicitly asked about the Fed or the
    # Reserve Bank of India — a confidently-formatted wrong number about
    # monetary policy, which is worse than no answer.
    if not is_uk_scoped(query):
        return None
    return "IUDBEDR"


def _requested_start(query: str, *, today: date | None = None) -> str | None:
    today = today or datetime.now(timezone.utc).date()
    match = _YEAR_SPAN.search(query)
    if not match:
        return None
    raw = match.group("count")
    years = int(raw) if raw.isdigit() else spelled_number_to_int(raw)
    if not years:
        return None
    try:
        start = today.replace(year=today.year - years)
    except ValueError:
        start = today.replace(year=today.year - years, day=28)
    return start.strftime("%d/%b/%Y")


def _parse_csv(payload: str, series_id: str) -> list[tuple[str, float]]:
    """[(iso date, value)] from the IADB CSV payload, oldest first.

    Returns [] for anything that is not the CSV it should be. IADB answers an
    unknown SeriesCodes with an HTML page and HTTP 200, so a body that does not
    start with the expected header is treated as no data at all.
    """
    lines = [line for line in (payload or "").splitlines() if line.strip()]
    if not lines or not lines[0].upper().startswith("DATE,"):
        return []
    points: list[tuple[str, float]] = []
    for line in lines[1:]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        raw_date, raw_value = parts[0], parts[1]
        try:
            parsed = datetime.strptime(raw_date, "%d %b %Y").date()
        except ValueError:
            continue
        if raw_value in {"", ".", "NA", "N/A"}:
            # A rate-free day (weekend, bank holiday) is missing data, not a
            # zero, and must never become a point on a chart at y=0.
            continue
        try:
            value = float(raw_value)
        except ValueError:
            continue
        points.append((parsed.isoformat(), value))
    points.sort(key=lambda point: point[0])
    return points


@dataclass(frozen=True)
class SeriesDefinition:
    series_id: str
    name: str
    unit: str = "%"


@dataclass
class BankRateMatch:
    """One matched Bank Rate series — the WebSource text and the structured
    evidence are both built from THIS object, so the prose and any chart
    cannot disagree about the rate."""

    series_id: str
    series_name: str
    points: list[tuple[str, float]]
    unit: str
    url: str
    warning: str | None = None
    latest_change: tuple[str, str, float] | None = field(default=None)


async def _find_bank_rate(query: str) -> BankRateMatch | None:
    series_id = _definition_for_query(query)
    if series_id is None:
        return None

    definition = SeriesDefinition(series_id, _SERIES[series_id])
    base = _base()
    params = {
        "csv.x": "yes", "SeriesCodes": series_id, "CSVF": "TN",
        "UsingCodes": "Y", "VPD": "Y", "VFD": "N", "Dateto": "now",
    }
    start = _requested_start(query)
    if start:
        params["Datefrom"] = start
    else:
        params["Datefrom"] = (datetime.now(timezone.utc).date() - timedelta(days=365)).strftime("%d/%b/%Y")

    try:
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": _user_agent()}) as client:
            response = await client.get(f"{base}/_iadb-fromshowcolumns.asp", params=params)
            response.raise_for_status()
            points = _parse_csv(response.text, series_id)
    except Exception:
        return None
    if not points:
        return None

    # A rate change is the fact people are actually asking for, and it is not
    # visible in the point series alone — the Bank Rate can sit at one value
    # for a year and then move twice in a quarter. Find the most recent move.
    latest_change: tuple[str, str, float] | None = None
    for earlier, later in zip(points, points[1:]):
        if earlier[1] != later[1]:
            latest_change = (earlier[0], later[0], later[1] - earlier[1])

    return BankRateMatch(
        series_id=series_id, series_name=definition.name, points=points,
        unit=definition.unit,
        url=f"{base}/bank-rate",
        latest_change=latest_change,
    )


def _build_source(match: BankRateMatch) -> WebSource:
    latest_date, latest_value = match.points[-1]
    lines = [
        f"Bank of England {match.series_name} (series {match.series_id}), the official United Kingdom "
        f"policy rate published each business morning. {latest_date}: {latest_value:g}{match.unit}.",
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
        title=f"Bank of England — {match.series_name} ({latest_date})",
        url=match.url,
        snippet=" ".join(lines),
        provider=PROVIDER,
        freshness="daily",
        series=match.points,
        observation=LiveObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            indicator=match.series_name, value=str(latest_value), unit=match.unit,
            period=latest_date, provider=PROVIDER, source_url=match.url,
            freshness="daily",
        ),
    )
