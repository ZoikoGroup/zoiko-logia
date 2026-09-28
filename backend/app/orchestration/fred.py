"""FRED economic-series retrieval for explicitly US statistics queries.

FRED is used only when a backend API key is configured, the query names the
United States, and a curated series can be selected deterministically.  This
keeps series selection auditable and prevents a broad search result from being
mistaken for the measure the user requested.  All failures are fail-soft so
DBnomics and the ordinary grounded-answer path remain available.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx

from app.orchestration.number_words import SPELLED_NUMBER_PATTERN, spelled_number_to_int
from app.orchestration.websearch import WebSource


_US_HINT = re.compile(r"(?<!\w)(?:US|U\.S\.|USA|United States|America(?:n)?)(?!\w)", re.I)
_YEAR_SPAN = re.compile(
    rf"\b(?:last|past|over)\s+(?P<count>\d+|{SPELLED_NUMBER_PATTERN})\s+years?\b",
    re.I,
)
_SINCE_YEAR = re.compile(r"\b(?:since|from)\s+(?P<start>(?:19|20)\d{2})(?:\s+(?:to|through|until|-|–)\s+(?P<end>(?:19|20)\d{2}|today|now|present))?\b", re.I)
_BETWEEN_YEARS = re.compile(r"\bbetween\s+(?P<start>(?:19|20)\d{2})\s+and\s+(?P<end>(?:19|20)\d{2})\b", re.I)
_YEAR_RANGE = re.compile(r"\b(?P<start>(?:19|20)\d{2})\s*[-–]\s*(?P<end>(?:19|20)\d{2})\b")


@dataclass(frozen=True)
class FredSeriesDefinition:
    series_id: str
    name: str
    unit: str
    frequency: str
    pattern: re.Pattern[str]


_SERIES = (
    FredSeriesDefinition(
        "CPIAUCSL", "US Consumer Price Index", "index", "monthly",
        re.compile(r"\b(?:CPI|consumer price(?: index)?|inflation)\b", re.I),
    ),
    FredSeriesDefinition(
        "UNRATE", "US Unemployment Rate", "%", "monthly",
        re.compile(r"\b(?:unemployment|jobless(?:ness)?|unemployment rate)\b", re.I),
    ),
    FredSeriesDefinition(
        "FEDFUNDS", "US Federal Funds Effective Rate", "%", "monthly",
        re.compile(r"\b(?:fed(?:eral)? funds|federal funds rate|policy rate)\b", re.I),
    ),
    FredSeriesDefinition(
        "DGS10", "US 10-Year Treasury Rate", "%", "daily",
        re.compile(r"\b(?:10[ -]?year treasury|ten[ -]?year treasury|DGS10)\b", re.I),
    ),
    FredSeriesDefinition(
        "A191RL1Q225SBEA", "US Real GDP Growth Rate", "% annualized", "quarterly",
        re.compile(r"\b(?:real\s+GDP\s+growth|GDP\s+growth|growth\s+(?:of|in)\s+(?:real\s+)?GDP)\b", re.I),
    ),
    FredSeriesDefinition(
        "GDPC1", "US Real Gross Domestic Product", "billions of chained 2017 USD", "quarterly",
        re.compile(r"\b(?:real\s+GDP|real\s+gross domestic product)\b", re.I),
    ),
    FredSeriesDefinition(
        "GDP", "US Nominal Gross Domestic Product", "billions of current USD", "quarterly",
        re.compile(r"\b(?:nominal\s+GDP|GDP|gross domestic product)\b", re.I),
    ),
    FredSeriesDefinition(
        "PAYEMS", "US Nonfarm Payroll Employment", "thousands of persons", "monthly",
        re.compile(r"\b(?:nonfarm payrolls?|payroll employment|PAYEMS)\b", re.I),
    ),
)
_IMPLICIT_US_SERIES = {"FEDFUNDS", "DGS10"}


@dataclass
class FredSeriesMatch:
    series_id: str
    series_name: str
    points: list[tuple[str, float]]
    unit: str
    frequency: str
    url: str
    requested_start: str | None = None
    requested_end: str | None = None
    coverage_complete: bool = True
    warning: str | None = None


def _fred_base() -> str:
    base = os.getenv("FRED_API_BASE_URL", "https://api.stlouisfed.org/fred").strip().rstrip("/")
    # A copied two-line example without its newline produces a deceptively
    # plausible value such as ".../fredFRED_API_KEY=...". Reject it instead
    # of issuing a request to an invalid endpoint and silently falling back.
    if "=" in base or not base.startswith(("https://", "http://")):
        return "https://api.stlouisfed.org/fred"
    return base


def _definition_for_query(query: str) -> FredSeriesDefinition | None:
    if not os.getenv("FRED_API_KEY"):
        return None
    definition = next((item for item in _SERIES if item.pattern.search(query)), None)
    if definition is None:
        return None
    if not _US_HINT.search(query) and definition.series_id not in _IMPLICIT_US_SERIES:
        return None
    return definition


def _requested_range(query: str, *, today: date | None = None) -> tuple[str | None, str | None]:
    today = today or datetime.now(timezone.utc).date()
    for pattern in (_BETWEEN_YEARS, _YEAR_RANGE, _SINCE_YEAR):
        match = pattern.search(query)
        if match:
            start = int(match.group("start"))
            raw_end = match.groupdict().get("end")
            if raw_end and raw_end.isdigit():
                return f"{start:04d}-01-01", f"{int(raw_end):04d}-12-31"
            return f"{start:04d}-01-01", today.isoformat()
    span_match = _YEAR_SPAN.search(query)
    if span_match:
        raw = span_match.group("count")
        years = int(raw) if raw.isdigit() else spelled_number_to_int(raw)
        if years:
            try:
                start = today.replace(year=today.year - years)
            except ValueError:
                start = today.replace(year=today.year - years, day=28)
            return start.isoformat(), today.isoformat()
    return None, None


def _observation_limit(query: str, frequency: str) -> int:
    """Keep enough points for the requested span without unbounded payloads."""
    years = None
    span_match = _YEAR_SPAN.search(query)
    if span_match:
        raw_count = span_match.group("count")
        years = int(raw_count) if raw_count.isdigit() else spelled_number_to_int(raw_count)
    requested_start, _ = _requested_range(query)
    if years is None and requested_start:
        years = max(1, datetime.now(timezone.utc).year - int(requested_start[:4]) + 1)
    per_year = {"daily": 260, "monthly": 12, "quarterly": 4}.get(frequency, 12)
    if years:
        return max(3, min(years * per_year, 1200))
    return {"daily": 90, "monthly": 24, "quarterly": 20}.get(frequency, 24)


async def _find_fred_series(query: str) -> FredSeriesMatch | None:
    definition = _definition_for_query(query)
    if definition is None:
        return None

    base = _fred_base()
    endpoint = f"{base}/series/observations"
    params = {
        "series_id": definition.series_id,
        "api_key": os.environ["FRED_API_KEY"],
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(_observation_limit(query, definition.frequency)),
    }
    requested_start, requested_end = _requested_range(query)
    if requested_start:
        params["observation_start"] = requested_start
    if requested_end:
        params["observation_end"] = requested_end
    try:
        # FRED occasionally takes longer than 10–12 seconds even for a small
        # observation window; use the same conservative ceiling as the live
        # integration probe while still failing soft for the request path.
        async with httpx.AsyncClient(timeout=20.0) as client:
            last_error: Exception | None = None
            observations = []
            for _attempt in range(2):
                try:
                    response = await client.get(endpoint, params=params)
                    response.raise_for_status()
                    observations = response.json().get("observations", [])
                    last_error = None
                    break
                except Exception as exc:  # bounded one-retry official-data path
                    last_error = exc
            if last_error is not None:
                raise last_error
    except Exception:
        return None

    points: list[tuple[str, float]] = []
    for observation in reversed(observations):
        observation_date = str(observation.get("date") or "").strip()
        value = observation.get("value")
        if not observation_date or value in (None, "", "."):
            continue
        try:
            points.append((observation_date, float(value)))
        except (TypeError, ValueError):
            continue
    if not points:
        return None

    coverage_complete = True
    warning = None
    if requested_start:
        try:
            requested_date = date.fromisoformat(requested_start)
            first_date = date.fromisoformat(points[0][0])
            tolerance_days = {"daily": 7, "monthly": 35, "quarterly": 100}.get(definition.frequency, 35)
            coverage_complete = (first_date - requested_date).days <= tolerance_days
        except ValueError:
            coverage_complete = points[0][0] <= requested_start
        if not coverage_complete:
            warning = f"Requested coverage starts at {requested_start}, but the first retrieved observation is {points[0][0]}."

    return FredSeriesMatch(
        series_id=definition.series_id,
        series_name=definition.name,
        points=points,
        unit=definition.unit,
        frequency=definition.frequency,
        url=f"https://fred.stlouisfed.org/series/{definition.series_id}",
        requested_start=requested_start,
        requested_end=requested_end,
        coverage_complete=coverage_complete,
        warning=warning,
    )


def _build_source(match: FredSeriesMatch) -> WebSource:
    values = ", ".join(f"{period}: {value:g}" for period, value in match.points)
    return WebSource(
        title=f"FRED — {match.series_name}",
        url=match.url,
        snippet=(
            f"Official economic data from FRED. Series {match.series_id}: "
            f"{match.series_name}. Values ({match.unit}) — {values}."
            f"{f' Coverage warning: {match.warning}' if match.warning else ''}"
        ),
        provider="Federal Reserve Bank of St. Louis (FRED)",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        freshness="historical",
    )


async def fetch_fred_stats(query: str) -> list[WebSource]:
    match = await _find_fred_series(query)
    return [_build_source(match)] if match else []
