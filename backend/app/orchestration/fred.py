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

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.number_words import SPELLED_NUMBER_PATTERN, spelled_number_to_int
from app.orchestration.websearch import WebSource


# Bare "US" is matched CASE-SENSITIVELY (written (?-i:US) inside an otherwise
# re.I pattern), exactly as in country_scope.py. "us" is also the ordinary
# English pronoun, and a case-insensitive match meant "the company told us
# about GDP" was answered with US nominal GDP — a real FRED series, correctly
# formatted, for a country the question never named. "US" in capitals is the
# conventional spelling of the country, so requiring capitals for the bare form
# costs no real query; the long forms below are never English words and stay
# case-insensitive.
_US_HINT = re.compile(r"(?<!\w)(?:(?-i:US)|U\.S\.|USA|United States|America(?:n)?)(?!\w)", re.I)
_YEAR_SPAN = re.compile(
    rf"\b(?:last|past|over)\s+(?P<count>\d+|{SPELLED_NUMBER_PATTERN})\s+years?\b",
    re.I,
)
_SINCE_YEAR = re.compile(r"\b(?:since|from)\s+(?P<start>(?:19|20)\d{2})(?:\s+(?:to|through|until|-|–)\s+(?P<end>(?:19|20)\d{2}|today|now|present))?\b", re.I)
_BETWEEN_YEARS = re.compile(r"\bbetween\s+(?P<start>(?:19|20)\d{2})\s+and\s+(?P<end>(?:19|20)\d{2})\b", re.I)
_YEAR_RANGE = re.compile(r"\b(?P<start>(?:19|20)\d{2})\s*[-–]\s*(?P<end>(?:19|20)\d{2})\b")

# Series published as currency LEVELS. Used to answer a percentage-of-GDP
# question they cannot answer — see _definition_for_query.
_LEVEL_ONLY_SERIES = frozenset({"BOPGSTB", "IEABC"})

# "…as a percentage of GDP", "…as a share of GDP", "…% of GDP", "…as a ratio
# to GDP". Deliberately narrow: it must fire on an explicit unit request, not on
# any mention of GDP, or it would take the US trade balance away from ordinary
# level questions that happen to mention GDP.
_RATIO_ASK = re.compile(
    r"(?:as\s+(?:a\s+)?(?:percent(?:age)?|share|ratio)\s+(?:of|to)\s+gdp"
    r"|%\s*of\s*(?:gdp|gross\s+domestic\s+product)"
    r"|(?:percent(?:age)?|share)\s+of\s+(?:gdp|gross\s+domestic\s+product)"
    r"|relative\s+to\s+(?:gdp|gross\s+domestic\s+product))",
    re.I,
)


# ── US policy rate: which instrument? ──────────────────────────────────────
# "policy rate" is not one statistic. The FOMC sets a target RANGE and the
# overnight market settles at the effective rate; FRED publishes all of them
# under different ids (DFEDTARU/DFEDTARL for the bounds, FEDFUNDS for the
# realised overnight rate). FEDFUNDS is the right series to serve for a bare
# "policy rate" - it is the rate that actually transacted and the one every
# other country's connector reports as its policy rate - but answering with it
# silently would let a reader believe they were told the FOMC target.
#
# So the bare phrasing is answered, and the instrument is named rather than
# implied. A query that already names an instrument ("federal funds rate",
# "target rate", "upper bound") gets no caveat, because there is nothing
# ambiguous left to disclose.
_POLICY_RATE_BARE = re.compile(
    r"\b(?:policy\s+(?:rate|interest\s+rate)|benchmark\s+rate|key\s+rate)\b", re.I)
_POLICY_RATE_INSTRUMENT_NAMED = re.compile(
    r"\b(?:federal\s+funds?|fed\s+funds?|target\s+rate|target\s+range|"
    r"upper\s+bound|lower\s+bound|effective\s+rate|overnight\s+rate|discount\s+rate)\b",
    re.I)
_POLICY_RATE_INSTRUMENT_NOTE = (
    "Instrument note: the US has no single 'policy rate'. This is the "
    "effective federal funds rate (FRED FEDFUNDS), the realised overnight rate. "
    "The FOMC's policy decision is a target RANGE for the federal funds rate "
    "(DFEDTARL lower bound / DFEDTARU upper bound), which is a different "
    "quantity. Name the instrument to get that one instead."
)


@dataclass(frozen=True)
class FredSeriesDefinition:
    series_id: str
    name: str
    unit: str
    frequency: str
    pattern: re.Pattern[str]


# Selection is positional: _definition_for_query takes the FIRST pattern that
# matches, so order here is precedence, not presentation. The two orderings
# that are load-bearing:
#   - T10YIE and PCEPILFE precede CPIAUCSL, because "10-year breakeven
#     inflation" and "core inflation" both contain the bare word "inflation"
#     that CPIAUCSL matches. Listed after, they would be unreachable.
#   - T10Y2Y precedes DGS2/DGS10, because "10-year Treasury minus 2-year
#     Treasury" contains both of their phrases.
#
# A191RL1A225NBEA (annual real GDP growth) is deliberately absent: it matches
# the same questions as the quarterly A191RL1Q225SBEA below and would sit
# behind it forever, while GDPC1 already covers real GDP levels.
_SERIES = (
    FredSeriesDefinition(
        "T10YIE", "US 10-Year Breakeven Inflation Rate", "%", "daily",
        re.compile(r"\b(?:breakeven inflation|breakeven\s+rate|market[- ]based inflation expectation)\b", re.I),
    ),
    FredSeriesDefinition(
        "PCEPILFE", "US Core PCE Price Index", "index 2017=100", "monthly",
        re.compile(r"\b(?:core pce|pce excluding food and energy|core inflation|excluding food and energy)\b", re.I),
    ),
    FredSeriesDefinition(
        "CPIAUCSL", "US Consumer Price Index", "index", "monthly",
        re.compile(r"\b(?:CPI|consumer price(?: index)?|inflation)\b", re.I),
    ),
    FredSeriesDefinition(
        "T10Y2Y", "US Treasury Yield Curve (10-Year minus 2-Year)", "%", "daily",
        re.compile(r"\b(?:yield curve|2s10s|10[- ]year (?:treasury )?minus|term spread)\b", re.I),
    ),
    FredSeriesDefinition(
        "DGS10", "US 10-Year Treasury Rate", "%", "daily",
        re.compile(r"\b(?:10[ -]?year treasury|ten[ -]?year treasury|DGS10)\b", re.I),
    ),
    FredSeriesDefinition(
        "DGS2", "US 2-Year Treasury Rate", "%", "daily",
        re.compile(r"\b(?:2[ -]?year treasury|two[ -]?year treasury|DGS2)\b", re.I),
    ),
    FredSeriesDefinition(
        "DGS30", "US 30-Year Treasury Rate", "%", "daily",
        re.compile(r"\b(?:30[ -]?year treasury|thirty[ -]?year treasury|DGS30)\b", re.I),
    ),
    FredSeriesDefinition(
        "MORTGAGE30US", "US 30-Year Fixed Mortgage Rate", "%", "weekly",
        re.compile(r"\b(?:30[ -]?year (?:fixed )?mortgage|mortgage rate|mortgage rates)\b", re.I),
    ),
    FredSeriesDefinition(
        "BAMLH0A0HYM2", "US High Yield Bond Spread (ICE BofA OAS)", "%", "daily",
        re.compile(r"\b(?:high[- ]yield spread|high[- ]yield (?:bond |option[- ]adjusted )?spread|hy spread|credit spread)\b", re.I),
    ),
    FredSeriesDefinition(
        "UNRATE", "US Unemployment Rate", "%", "monthly",
        re.compile(r"\b(?:unemployment|jobless(?:ness)?|unemployment rate)\b", re.I),
    ),
    FredSeriesDefinition(
        "FEDFUNDS", "US Federal Funds Effective Rate", "%", "monthly",
        # "policy interest rate" is the wording used by the other countries'
        # connectors (dbnomics._POLICY_RATE_HINTS) and by the Bank of Canada and
        # RBA paths, so the US route has to recognise it too — otherwise
        # "United States policy interest rate" matched nothing here, fell through
        # every US series, and got no authoritative answer at all while the
        # identical question for Canada, Germany or Japan resolved.
        re.compile(
            r"\b(?:fed(?:eral)? funds|federal funds rate|"
            r"policy\s+(?:interest\s+)?rate)\b",
            re.I,
        ),
    ),
    FredSeriesDefinition(
        "INDPRO", "US Industrial Production", "index 2017=100", "monthly",
        re.compile(r"\b(?:industrial production|manufacturing output|factory output)\b", re.I),
    ),
    FredSeriesDefinition(
        "RSXFS", "US Advance Retail Sales", "millions of dollars", "monthly",
        re.compile(r"\b(retail sales|advance retail|consumer spending)\b", re.I),
    ),
    # ── Fiscal and external accounts ──────────────────────────────────────
    # These five sit ABOVE the GDP definition on purpose, and that ordering is
    # the whole fix for a confirmed wrong-data bug. "US government debt to GDP"
    # contains the literal word "GDP", so the catch-all GDP pattern below used
    # to match first and answer a debt-to-GDP question with the GDP *level* —
    # a real FRED number, correctly formatted, for an entirely different
    # quantity. The same trap caught "US government revenue as a share of GDP"
    # and "US trade balance as a percentage of GDP". Fiscal and external
    # questions name their own indicator first; GDP is the last resort.
    # Ordering between the two debt series is load-bearing. A question asking
    # for the *size* of the debt ("how much is the US government debt") wants
    # the dollar level; one asking for it *as a share of GDP* wants the ratio.
    # The level pattern therefore has to be tested first — it is the more
    # specific phrasing, and the ratio's bare "government debt" alternative
    # would otherwise swallow it and answer "how much is it?" with a
    # percentage.
    FredSeriesDefinition(
        "GFDEBTN", "US Total Public Debt Outstanding", "millions of dollars", "quarterly",
        re.compile(
            r"\b(?:how much|what is|size of|level of|total|amount of|value of)\s+"
            r"(?:is\s+|are\s+)?(?:the\s+)?(?:us\s+|american\s+)?"
            r"(?:government|federal|national|public)\s+debt\b(?!\s*(?:to|as|of|relative))",
            re.I,
        ),
    ),
    FredSeriesDefinition(
        "GFDEGDQ188S", "US Federal Debt as a Percentage of GDP", "% of GDP", "quarterly",
        re.compile(
            r"\b(?:government|federal|national|public)?\s*debt(?:\s+(?:to|as (?:a )?(?:share|percent(?:age)?))\s*(?:of\s*)?gdp)?\b"
            r"|\bdebt[- ]to[- ]gdp\b|\bfederal debt\b|\bgross federal debt\b|\bnational debt\b",
            re.I,
        ),
    ),
    FredSeriesDefinition(
        "FYFSGDA188S", "US Federal Surplus or Deficit as a Percentage of GDP", "% of GDP", "annual",
        re.compile(
            r"\b(?:budget|fiscal)\s+(?:deficit|surplus)\b|\bdeficit(?:\s+(?:to|as (?:a )?(?:share|percent(?:age)?))\s*(?:of\s*)?gdp)?\b"
            r"|\bfederal deficit\b",
            re.I,
        ),
    ),
    FredSeriesDefinition(
        "FYFRGDA188S", "US Federal Receipts as a Percentage of GDP", "% of GDP", "annual",
        re.compile(
            r"\b(?:government|federal)\s+(?:revenue|receipts|income)\b"
            r"|\btax\s+(?:revenue|receipts|burden|to[- ]gdp)\b",
            re.I,
        ),
    ),
    FredSeriesDefinition(
        "BOPGSTB", "US Trade Balance (Goods and Services)", "millions of dollars", "monthly",
        re.compile(
            r"\btrade\s+(?:balance|deficit|surplus)\b|\b(?:goods and services\s+)?trade\s+gap\b"
            r"|\b(?:import|export)\s+(?:gap|deficit|surplus)\b",
            re.I,
        ),
    ),
    FredSeriesDefinition(
        "IEABC", "US Current Account Balance", "millions of dollars", "quarterly",
        re.compile(r"\bcurrent account\b", re.I),
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
        # The trailing lookahead is load-bearing. A bare "GDP" alternative matches
        # "US GDP per capita" too, and the total (~$30 trillion, billions of USD)
        # is then reported as the per-capita figure — wrong by three orders of
        # magnitude, confidently formatted, with a real FRED URL attached. With
        # this guard the definition declines per-capita phrasings and the DBnomics
        # NGDPDPC resolver (dbnomics._find_gdp_series) answers them instead.
        re.compile(
            r"\b(?:nominal\s+GDP|GDP|gross domestic product)\b"
            r"(?!\s*(?:per\s+capita|per\s+head|income\s+per|per\s+person))",
            re.I,
        ),
    ),
    FredSeriesDefinition(
        "PAYEMS", "US Nonfarm Payroll Employment", "thousands of persons", "monthly",
        re.compile(r"\b(?:nonfarm payrolls?|payroll employment|PAYEMS)\b", re.I),
    ),
)
# Series whose subject matter is unambiguously US, so the question does not have
# to say so — the pre-existing FEDFUNDS/DGS10 pair, extended to the rest of the
# Treasury curve. Plain-English "Treasury" names the US market specifically, so
# these resolve on their own.
#
# Everything else added above REQUIRES an explicit country hint, because the
# underlying concept is not American-only: "retail sales", "industrial
# production", "breakeven inflation" and "30-year mortgage rate" are all things
# India, the UK and the Eurozone genuinely publish. A period lookup returns a
# confidently-formatted US number with no country on it, and that is worse than
# silence. Widening this set is how "India retail sales" silently becomes
# US Advance Retail Sales.
_IMPLICIT_US_SERIES = {"FEDFUNDS", "DGS10", "DGS2", "DGS30", "T10Y2Y"}


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
    instrument_note: str | None = None


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
    # A ratio question must not be answered with a level. FRED's US trade
    # balance (BOPGSTB) and current account (IEABC) are both published in
    # millions of dollars, but their patterns match the same words the
    # percentage-of-GDP phrasings use. "US current account balance as a
    # percentage of GDP" therefore returned -246,023 with the unit
    # "millions of dollars" — the right statistic, the wrong unit, and a number
    # roughly a thousand times too large for the question asked. The other nine
    # countries answer the identical question from WDI BN.CAB.XOKA.GD.ZS in
    # percent, so the same question produced two different units depending only
    # on which country was asked about.
    #
    # Declining here is safe and cheap: the WDI path answers in percent, so the
    # question still gets a real, correctly-united answer — it just stops being
    # FRED's. A level-only series is still served when no ratio is asked for,
    # which is the common case ("what is the US trade balance").
    if definition.series_id in _LEVEL_ONLY_SERIES and _RATIO_ASK.search(query):
        return None
    # A different supported country is affirmative: "Canadian policy rate"
    # names Canada, and FRED holds US series only. This guard is checked even
    # for the implicit-US series, because FEDFUNDS matches the bare words
    # "policy rate". Without this, a Canadian policy-rate question was answered
    # with the US federal funds rate — a real number, correctly formatted, for
    # the wrong economy, which is exactly the failure mode this whole codebase
    # is built to prevent.
    from app.orchestration.country_scope import named_countries, names_another_country
    named = named_countries(query)
    if any(code != "US" for code in named):
        return None
    # The same argument applies to countries this product does not serve. The
    # supported-country check above cannot see them, so it left every one of
    # them looking like "no country named" — the default-US path — and
    # "What is the Luxembourg policy rate?" was answered with the US federal
    # funds rate. Every series in _SERIES is a US concept, so a question naming
    # any other country is a question FRED cannot answer, whichever country it
    # is. Erring toward refusal is the safe direction: the web path either finds
    # the right economy or admits it did not.
    if names_another_country(query):
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
    per_year = {"daily": 260, "weekly": 52, "monthly": 12, "quarterly": 4}.get(frequency, 12)
    if years:
        return max(3, min(years * per_year, 1200))
    return {"daily": 90, "weekly": 52, "monthly": 24, "quarterly": 20}.get(frequency, 24)


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
    # Sort by date rather than trusting the response order. FRED is asked for
    # sort_order=desc, so `reversed()` was correct for the real feed - but a
    # connector that picks its "latest" observation from an assumed order will
    # one day report the OLDEST value as the current one, which is precisely the
    # stale-as-fresh failure this module must not have. Sorting costs nothing and
    # removes the assumption.
    dated: list[tuple[str, float]] = []
    for observation in observations:
        observation_date = str(observation.get("date") or "").strip()
        value = observation.get("value")
        if not observation_date or value in (None, "", "."):
            continue
        try:
            dated.append((observation_date, float(value)))
        except (TypeError, ValueError):
            continue
    dated.sort(key=lambda item: item[0])
    points = dated
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

    instrument_note = None
    if (
        definition.series_id == "FEDFUNDS"
        and _POLICY_RATE_BARE.search(query)
        and not _POLICY_RATE_INSTRUMENT_NAMED.search(query)
    ):
        instrument_note = _POLICY_RATE_INSTRUMENT_NOTE

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
        instrument_note=instrument_note,
    )


def _build_source(match: FredSeriesMatch) -> WebSource:
    values = ", ".join(f"{period}: {value:g}" for period, value in match.points)
    latest_period, latest_value = match.points[-1]
    provider_name = "Federal Reserve Bank of St. Louis (FRED)"
    caveat = ""
    if match.instrument_note:
        caveat += f" {match.instrument_note}"
    if match.warning:
        caveat += f" Coverage warning: {match.warning}"
    return WebSource(
        title=f"FRED — {match.series_name}",
        url=match.url,
        snippet=(
            f"Official economic data from FRED. Series {match.series_id}: "
            f"{match.series_name}. Values ({match.unit}) — {values}."
            f"{caveat}"
        ),
        provider=provider_name,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        freshness="historical",
        observation=LiveObservation(
            observation_id=f"fred:{match.series_id}",
            indicator=match.series_id,
            value=f"{latest_value:g}",
            unit=match.unit,
            period=latest_period,
            provider=provider_name,
            source_url=match.url,
            freshness="historical",
        ),
        series=list(match.points),
    )


async def fetch_fred_stats(query: str) -> list[WebSource]:
    match = await _find_fred_series(query)
    return [_build_source(match)] if match else []
