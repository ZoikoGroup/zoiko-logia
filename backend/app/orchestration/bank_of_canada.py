"""Canada's policy interest rate from the Bank of Canada's own Valet API.

Same reasoning as bank_of_england.py, one country over. FRED refuses any
question that does not name the United States, DBnomics carries no Canadian
policy rate, and the Bank of Canada publishes the overnight rate target on
Valet — keyless, official, and already returning a clean dated series.

The Canada scope guard lives in country_scope.py, shared with the UK, Irish,
Australian and US connectors: a policy rate is the classic confident-wrong-
number question, because "what is the policy rate" without a country reads as
generic while every connector here can only speak for one economy.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.country_scope import is_country_scoped
from app.orchestration.websearch import WebSource

PROVIDER = "Bank of Canada"

_BASE_DEFAULT = "https://www.bankofcanada.ca/valet"

_UA_DEFAULT = "ZoikoLogia Kriton ops@zoikogroup.com"

_COUNTRY = "CA"


def _user_agent() -> str:
    return os.getenv("BANK_OF_CANADA_USER_AGENT", _UA_DEFAULT).strip() or _UA_DEFAULT


def _base() -> str:
    base = os.getenv("BANK_OF_CANADA_API_BASE_URL", _BASE_DEFAULT).strip().rstrip("/")
    if "=" in base or not base.startswith(("https://", "http://")):
        return _BASE_DEFAULT
    return base


# Same vocabulary as the BoE connector, plus the Canadian-specific phrasings.
# "overnight rate" is how the Bank of Canada itself names it, and is included so
# a question quoted from a Bank of Canada release matches.
_HINT = re.compile(
    r"\b(?:policy\s+rate|interest\s+rate|overnight\s+rate|overnight\s+rate\s+target|"
    r"bank\s+rate|base\s+rate|monetary\s+policy\s+rate|cash\s+rate)\b",
    re.I,
)

# V39079 is the Bank of Canada's published target for the overnight rate,
# updated each business day. It is the Canadian counterpart of the BoE's
# IUDBEDR. FXUSDCAD is the Bank's own daily USD/CAD rate, published alongside
# it; the general FX connector (frankfurter.py) still leads for currency pairs
# because the ECB reference rate is authoritative for the majors, so this
# series is only used when the question is about the Canadian rate directly.
_SERIES = {
    "V39079": "Bank of Canada Policy Interest Rate",
}


@dataclass
class PolicyRateMatch:
    """One matched Canadian policy-rate series. The WebSource text and the
    structured evidence are both built from THIS object, so the prose and any
    chart cannot disagree about the rate."""

    series_id: str
    series_name: str
    points: list[tuple[str, float]]
    unit: str
    url: str
    latest_change: tuple[str, str, float] | None = field(default=None)
    warning: str | None = None


def _definition_for_query(query: str) -> str | None:
    if not _HINT.search(query or ""):
        return None
    if not is_country_scoped(query, _COUNTRY):
        return None
    return "V39079"


def _parse_observations(payload: dict) -> list[tuple[str, float]]:
    """[(iso date, value)] from a Valet observations payload, oldest first.

    Valet nests the value under the series id itself:
    ``{"d": "2026-09-24", "V39079": {"v": "2.25"}}``. Returns [] for anything
    that does not have that shape, so an error page with HTTP 200 is treated as
    no data rather than as a zero-valued rate.
    """
    series_id = None
    observations = payload.get("observations")
    if not isinstance(observations, list):
        return []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        if series_id is None:
            # The series id is the key that is not the date "d".
            for key in obs:
                if key != "d" and isinstance(obs.get(key), dict):
                    series_id = key
                    break
        if series_id is None:
            return []
        entry = obs.get(series_id) or {}
        raw_date = obs.get("d")
        raw_value = entry.get("v")
        if not raw_date or raw_value in (None, "", "NA"):
            continue
        try:
            parsed = datetime.strptime(str(raw_date), "%Y-%m-%d").date()
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        yield (parsed.isoformat(), value)


async def _find_policy_rate(query: str) -> PolicyRateMatch | None:
    series_id = _definition_for_query(query)
    if series_id is None:
        return None

    name = _SERIES[series_id]
    try:
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": _user_agent()}) as client:
            response = await client.get(
                f"{_base()}/observations/{series_id}/json", params={"recent": "1200"}
            )
            response.raise_for_status()
            payload = response.json()
            points = list(_parse_observations(payload))
    except Exception:
        return None
    if not points:
        return None
    points.sort(key=lambda point: point[0])

    latest_change: tuple[str, str, float] | None = None
    for earlier, later in zip(points, points[1:]):
        if earlier[1] != later[1]:
            latest_change = (earlier[0], later[0], later[1] - earlier[1])

    return PolicyRateMatch(
        series_id=series_id,
        series_name=name,
        points=points,
        unit="%",
        url="https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
        latest_change=latest_change,
    )


def _build_source(match: PolicyRateMatch) -> WebSource:
    latest_date, latest_value = match.points[-1]
    lines = [
        f"Bank of Canada {match.series_name} (series {match.series_id}), the official Canadian "
        f"policy rate published each business day. {latest_date}: {latest_value:g}%.",
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
        title=f"Bank of Canada — {match.series_name} ({latest_date})",
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
