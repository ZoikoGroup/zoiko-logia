"""Statutory corporate income tax rates for the ten supported countries.

Before this module, "what is the German corporate tax rate" had no structured
answer at all: GOV.UK covered the UK only, and Germany, France, India and China
fell through to web search with no figure to check against. This connector
closes that gap from a primary publisher — the OECD Tax Database's statutory
corporate income tax dataset — which covers all ten countries with one consistent
definition, keyless, via DBnomics.

Three things about this data decide the whole design:

  1. TWO measures, and they are not interchangeable. The dataset publishes the
     statutory rate levied by CENTRAL government and a COMBINED rate that adds
     sub-central levies. For most of the ten the two are close; for Germany they
     are 15.825% and 30.133%, because the German trade tax (Gewerbesteuer, ~14.3
     points) is levied by the Länder and municipalities. Canada's federal rate is
     15% against a 26% combined rate for the same reason. Quoting only the
     central figure would be wrong for exactly the two countries where the
     question is most often asked, so both are always reported, each labelled
     with the level of government it covers.

  2. The value is annual and belongs to a calendar year. A statutory rate is not
     a live reading, so the year is on the face of the answer, and a rate whose
     latest published year is more than OECD_TAX_MAX_AGE_YEARS behind the
     current year is not reported at all — the same expiry rule govuk.py applies
     to UK rate pages. Verified live: the central series runs to 2026 for the US,
     UK, Ireland, Canada, Australia, Germany, France and Japan, and to 2025 for
     India and China.

  3. A company question is not a country question. "What is Apple's tax rate"
     contains no country at all, and the unscoped default below would otherwise
     answer it with the United States' federal rate. Any question naming a
     ticker or a well-known company is refused outright.

Sources: OECD, "Corporate income tax (CIT) - statutory and targeted small
business rates" (DSD_TAX_CIT@DF_CIT), served by DBnomics.
https://db.nomics.world/OECD/DSD_TAX_CIT@DF_CIT
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.country_scope import display_name, is_country_scoped, named_countries
from app.orchestration.websearch import WebSource

PROVIDER = "OECD Tax Database"

_DATASET = "OECD/DSD_TAX_CIT@DF_CIT"
_DATASET_NAME = "Corporate income tax (CIT) - statutory and targeted small business rates"

# REF_AREA.FREQ.MEASURE.TARGETING.UNIT.SECTOR plus the three "not applicable"
# dimensions OECD leaves as _Z. S1311 is central government, S13 general
# government; CIT is the rate itself, CIT_C the combined rate.
_CENTRAL_SERIES = "{iso3}.A.CIT.ST.PT_INC_TAX.S1311._Z._Z._Z"
_COMBINED_SERIES = "{iso3}.A.CIT_C.ST.PT_INC_TAX.S13._Z._Z._Z"

_MAX_POINTS = 20
_DEFAULT_MAX_AGE_YEARS = 1

# The ten supported countries, ISO2 -> the dataset's REF_AREA code.
_ISO3: dict[str, str] = {
    "US": "USA", "GB": "GBR", "IE": "IRL", "CA": "CAN", "AU": "AUS",
    "DE": "DEU", "FR": "FRA", "JP": "JPN", "IN": "IND", "CN": "CHN",
}

# Rate questions only. "How is corporate tax calculated" and "corporate tax
# reform in France" contain "corporate tax" but not a rate, and are not answered
# with a single percentage.
_RATE_HINT = re.compile(
    r"\b(?:corporate|corporation|company)\s+(?:income\s+)?tax\s+rate\b"
    r"|\bstatutory\s+(?:corporate\s+)?tax\s+rate\b"
    r"|\b(?:combined|all[\s-]?in|total)\s+(?:corporate\s+)?tax\s+rate\b"
    r"|\bCIT\s+rate\b",
    re.I,
)
# A question that asks for the all-in burden wants the combined figure as its
# headline rather than the central-government rate.
_COMBINED_HINT = re.compile(
    r"\bcombined\b|\ball[\s-]?in\b"
    r"|\bincluding\s+(?:sub[\s-]?national|state|regional|local|provincial|Länder"
    r"|trade\s+tax(?:es)?|Gewerbesteuer|municipal)\b"
    r"|\btotal\s+(?:tax\s+)?(?:rate|burden)\b|\beffective\s+rate\b",
    re.I,
)

_HEADLINE_LABELS = {
    "central": "statutory corporate income tax rate, central government",
    "combined": "combined statutory corporate income tax rate including sub-central taxes, general government",
}


def _dbnomics_base() -> str:
    return os.getenv("DBNOMICS_API_BASE_URL", "https://api.db.nomics.world/v22").strip().rstrip("/")


def _max_age_years() -> int:
    try:
        value = int(os.getenv("OECD_TAX_MAX_AGE_YEARS", str(_DEFAULT_MAX_AGE_YEARS)))
    except ValueError:
        return _DEFAULT_MAX_AGE_YEARS
    return value if 0 <= value <= 10 else _DEFAULT_MAX_AGE_YEARS


def _names_a_company(query: str) -> bool:
    """Whether the question is about a company rather than a country's tax law.

    Imported lazily for the same reason service.py does it: orchestration
    imports this domain package, so a module-level import would close the loop
    at startup.

    The tax vocabulary is stripped before the text is read as a ticker, because
    the dataset's own measure name is the collision: CIT is a plausible ticker
    string, so "What is the CIT rate in France?" was refused as a question about
    a listed company. What survives the strip is the rest of the sentence, where
    a company name would actually be.
    """
    from app.domains.market_data.identity import find_ticker, known_ticker_for_name

    text = _COMBINED_HINT.sub(" ", _RATE_HINT.sub(" ", query or ""))
    return bool(find_ticker(text) or known_ticker_for_name(text)[0])


def _country_for_query(query: str) -> str | None:
    """The one supported country this question is about, or None.

    Naming two of the supported countries is refused: a comparative question
    ("UK and German corporate tax rate") has no defensible single answer, and the
    cross-country paths ask it one country at a time. Naming none falls back to
    the United States, and every source built from that default names the country
    on its face, so a defaulted answer is never read as a requested one.
    """
    named = named_countries(query or "")
    if len(named) > 1:
        return None
    if named:
        return named[0]
    if is_country_scoped(query or "", "US"):
        return "US"
    return None


def _year_of(period: str) -> int | None:
    text = str(period or "")[:4]
    return int(text) if text.isdigit() and len(text) == 4 else None


def _is_current(period: str, *, now: datetime | None = None) -> bool:
    """Whether a published year is recent enough to state as the rate in force.

    Also refuses a year that has not happened. A statutory rate is stated as
    being in force for a calendar year, so a future-dated observation cannot
    describe the present, and OECD has no reason to publish one — treating it as
    the newest value would let a data glitch report a rate for a year that has
    not arrived.
    """
    year = _year_of(period)
    if year is None:
        return False
    current = (now or datetime.now(timezone.utc)).year
    return current - _max_age_years() <= year <= current


async def _fetch_points(client: httpx.AsyncClient, series_code: str) -> list[tuple[str, float]]:
    """(period, value) pairs for one OECD tax series, oldest first."""
    try:
        response = await client.get(
            f"{_dbnomics_base()}/series/{_DATASET}/{series_code}",
            params={"observations": "1"},
        )
        if response.status_code != 200:
            return []
        docs = response.json().get("series", {}).get("docs", [])
    except Exception:
        return []
    if not docs:
        return []
    doc = docs[0]
    points: list[tuple[str, float]] = []
    for period, value in zip(doc.get("period") or [], doc.get("value") or []):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            # OECD publishes "null" for a year it has not filled in yet; that is
            # a missing observation, not a zero rate.
            continue
        if _year_of(period) is None:
            continue
        points.append((str(period), float(value)))
    points.sort(key=lambda point: point[0])
    return points[-_MAX_POINTS:]


@dataclass
class OecdTaxMatch:
    """One country's statutory rate, on both measures, with their years."""

    country: str
    headline: str
    rate: float
    year: str
    points: list[tuple[str, float]]
    other_rate: float | None
    other_year: str
    other_points: list[tuple[str, float]]
    url: str
    other_url: str = ""


def _series_url(iso3: str, measure: str) -> str:
    """The API URL for one measure, so the cited source is the one quoted.

    Pointing every answer at the combined series regardless of the headline
    meant a central-government answer cited a page that did not contain it:
    the reader follows the link to a 30.133% figure for a question that asked
    for 15.825%.
    """
    template = _COMBINED_SERIES if measure == "combined" else _CENTRAL_SERIES
    return f"{_dbnomics_base()}/series/{_DATASET}/{template.format(iso3=iso3)}"


async def _find_oecd_tax_rate(
    query: str, *, client: httpx.AsyncClient | None = None,
) -> OecdTaxMatch | None:
    """The statutory corporate tax rate this question asks for, or None."""
    if not _RATE_HINT.search(query or ""):
        return None
    if _names_a_company(query):
        return None
    country = _country_for_query(query)
    iso3 = _ISO3.get(country or "")
    if not iso3:
        return None

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=12.0)
    try:
        central = await _fetch_points(http, _CENTRAL_SERIES.format(iso3=iso3))
        combined = await _fetch_points(http, _COMBINED_SERIES.format(iso3=iso3))
    finally:
        if owns_client:
            await http.aclose()

    # Expiry, applied per measure: a rate that cannot be shown to be current is
    # not reported, so a stale central figure is never quietly paired with a
    # current combined one.
    series = {
        "central": [(period, value) for period, value in central if _is_current(period)],
        "combined": [(period, value) for period, value in combined if _is_current(period)],
    }
    series = {key: points for key, points in series.items() if points}
    if not series:
        return None

    want = "combined" if _COMBINED_HINT.search(query or "") else "central"
    headline = want if want in series else next(iter(series))
    other = "central" if headline == "combined" else "combined"
    other_points = series.get(other, [])

    return OecdTaxMatch(
        country=country,
        headline=headline,
        rate=series[headline][-1][1],
        year=series[headline][-1][0],
        points=series[headline],
        other_rate=other_points[-1][1] if other_points else None,
        other_year=other_points[-1][0] if other_points else "",
        other_points=other_points,
        url=_series_url(_ISO3[country], headline),
        other_url=_series_url(_ISO3[country], other) if other_points else "",
    )


def _build_source(match: OecdTaxMatch) -> WebSource:
    country = display_name(match.country)
    headline_label = _HEADLINE_LABELS[match.headline]
    other_label = _HEADLINE_LABELS["central" if match.headline == "combined" else "combined"]

    lines = [
        f"OECD Tax Database — {_DATASET_NAME} (served via DBnomics). "
        f"{country}: {headline_label}, {match.year} = {match.rate:g}%.",
    ]
    if match.other_rate is not None:
        other_measure = "central" if match.headline == "combined" else "combined"
        other_series = (
            _COMBINED_SERIES if other_measure == "combined" else _CENTRAL_SERIES
        ).format(iso3=_ISO3[match.country])
        lines.append(
            f"On the other measure, {other_label}, {match.other_year} = {match.other_rate:g}% "
            f"(series {other_series}). "
            "The two differ where sub-central governments levy their own tax on "
            "companies (state, provincial, Länder or municipal), so a question "
            "about 'the corporate tax rate' has two correct answers unless the "
            "level of government is stated — name the one being quoted."
        )
    lines.append(
        "This is the statutory rate in force for the stated calendar year, not a "
        "live reading: tax rates are set by law, and the year is the period the "
        "figure belongs to."
    )
    if match.points:
        lines.append(
            "Annual values — "
            + ", ".join(f"{period}: {value:g}%" for period, value in match.points[-6:])
            + "."
        )

    return WebSource(
        title=f"OECD Tax Database — {country} corporate income tax rate ({match.year})"[:200],
        url=match.url,
        snippet=" ".join(lines),
        provider=PROVIDER,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        freshness="annual",
        series=list(match.points),
        observation=LiveObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            indicator=f"{country} {headline_label}",
            value=f"{match.rate:g}", unit="percent",
            period=match.year, provider=PROVIDER, source_url=match.url,
            freshness="annual",
        ),
    )
