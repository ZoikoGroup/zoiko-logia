"""
DBnomics economic-statistics retrieval for Ask Kriton™.

DBnomics (https://db.nomics.world) is a free, keyless aggregator of ~90 official
statistics providers (World Bank, IMF, OECD, Eurostat, ECB, ILO, national banks…).
When a question is about an economic statistic (inflation, GDP, unemployment,
interest rate, tax-to-GDP…), this finds the best-matching data series and returns
its recent real values as a WebSource — the SAME shape SearXNG results use — so it
merges straight into the existing grounded answer pipeline with no other change.

Two design choices, both for data-honesty (this is a finance bot):
  - It returns data ONLY when it finds a series that (a) has real numeric values
    and (b) whose exact name overlaps the question's keywords. Otherwise it returns
    [] and the bot falls back to its normal web-grounded answer.
  - The source it returns carries the series' EXACT name (e.g. "Annual · India ·
    Consumer prices") so the reader can see precisely which series a number came
    from — never a vague "inflation" that might be a sub-index.

Fails soft on any non-stat question or network/parse error → returns [].
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

import httpx

from app.orchestration.websearch import WebSource
from app.domains.calculations.schemas import LiveObservation

# Only fire on questions that actually look like an economic statistic — avoids
# firing on definitional/how-to questions SearXNG should answer instead.
_STAT_HINTS = re.compile(
    r"\b(inflation|cpi|consumer price|gdp|gross domestic|gni|gnp|unemployment|"
    r"employment rate|labou?r force|interest rate|policy rate|population|"
    r"poverty|wage|wages|debt|deficit|trade balance|exports?|imports?|"
    r"tax[- ]to[- ]gdp|tax revenue|effective tax rate|economic growth|"
    r"growth rate|exchange reserves|money supply|statistics?)\b",
    re.I,
)

# Longest run of values carried into a source snippet / chart window.
_MAX_POINTS = 20

_STOPWORDS = {
    "the", "and", "for", "with", "what", "show", "give", "rate", "data",
    "value", "values", "latest", "current", "chart", "graph", "over", "years", "year",
    "distribution", "spread", "histogram", "figures", "last", "past", "few", "quarters",
    # Chart-type words, comparison verbs and anything else the user says ABOUT
    # the request rather than about the statistic. DBnomics' full-text search
    # ANDs its terms, so a single presentation word that appears in no series
    # name zeroes the whole result set: "compare gdp india line" returned 0
    # datasets where "gdp india" returned 3, and "compare gdp in india" found
    # no series while "gdp in india" resolved fine. "chart"/"graph" were
    # already above; the words that actually name the chart were not.
    "line", "bar", "pie", "donut", "doughnut", "scatter", "plot", "area",
    "trend", "trends", "table", "visualize", "visualise", "display",
    "compare", "compares", "compared", "comparison", "versus", "against",
    "between", "across", "using", "draw", "create", "make", "please",
    "about", "would", "like", "want", "need",
}

# Terms under four characters that must NOT be discarded. The old
# [A-Za-z]{4,} filter silently dropped every one of these, which broke the
# connector in two ways: "gdp" vanished from "what is India's gdp rate", leaving
# only a misspelled country to search on; and "us" vanished from "us
# unemployment rate", leaving no country anchor at all — DBnomics then returned
# an OECD education series for ARGENTINA that matched purely because
# "Unemployment" appeared in its 15-dimension name.
_SHORT_KEEP = {
    # indicators
    "cpi", "gdp", "ppi", "gni", "gnp", "fdi", "vat", "gst", "tds", "epf", "esi",
    # countries / blocs
    "us", "usa", "uk", "eu", "uae", "prc",
}

# Also the general country-name detector (_country_in_query/countries_in_query
# below) — not CPI-specific despite the name, so adding a country here makes
# it resolvable by every precise per-country lookup (CPI, unemployment, …).
_CPI_COUNTRIES = {
    "india": "India",
    "us": "United States",
    "u.s.": "United States",
    "usa": "United States",
    "united states": "United States",
    "america": "United States",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "germany": "Germany",
    "france": "France",
    "canada": "Canada",
    "japan": "Japan",
}

_CPI_COUNTRY_CODES = {
    "India": "IN",
    "United States": "US",
    "United Kingdom": "GB",
    "Germany": "DE",
    "France": "FR",
    "Canada": "CA",
    "Japan": "JP",
}

# Country anchoring. A statistic is meaningless without knowing whose it is, so
# when the question names a country the chosen series MUST be that country's.
# Aliases resolve to ISO3 directly (rather than to the display labels above), so
# this pair of tables serves the deterministic World Bank lookup below.
_COUNTRY_ALIASES: dict[str, str] = {
    "us": "united states", "usa": "united states", "america": "united states",
    "american": "united states", "states": "united states",
    "uk": "united kingdom", "britain": "united kingdom", "british": "united kingdom",
    "england": "united kingdom", "kingdom": "united kingdom",
    "india": "india", "indian": "india",
    "china": "china", "chinese": "china", "prc": "china",
    "japan": "japan", "japanese": "japan",
    "germany": "germany", "german": "germany",
    "france": "france", "french": "france",
    "canada": "canada", "canadian": "canada",
    "australia": "australia", "australian": "australia",
    "uae": "united arab emirates", "emirates": "united arab emirates",
    "singapore": "singapore", "brazil": "brazil", "brazilian": "brazil",
    "italy": "italy", "spain": "spain", "mexico": "mexico",
    "indonesia": "indonesia", "nigeria": "nigeria", "pakistan": "pakistan",
    "bangladesh": "bangladesh", "russia": "russia", "korea": "korea",
    "greece": "greece", "greek": "greece",
}

# ISO-3 codes, because many DBnomics series carry the country only in the code
# (e.g. ".../ARG.F.Y25T34..."), not in the display name.
_ISO3: dict[str, str] = {
    "united states": "USA", "united kingdom": "GBR", "india": "IND",
    "china": "CHN", "japan": "JPN", "germany": "DEU", "france": "FRA",
    "canada": "CAN", "australia": "AUS", "united arab emirates": "ARE",
    "singapore": "SGP", "brazil": "BRA", "italy": "ITA", "spain": "ESP",
    "mexico": "MEX", "indonesia": "IDN", "nigeria": "NGA", "pakistan": "PAK",
    "bangladesh": "BGD", "russia": "RUS", "korea": "KOR", "greece": "GRC",
}

# OECD MEI's harmonised-unemployment-rate series code uses ISO3, unlike CPI's
# ISO2 — a different provider/dataset entirely, so a separate code map.
# India omitted: not an OECD member, no series exists there — better to
# return no data honestly than force a lookup that 404s.
_UNEMPLOYMENT_COUNTRY_CODES = {
    "United States": "USA",
    "United Kingdom": "GBR",
    "Germany": "DEU",
    "France": "FRA",
    "Canada": "CAN",
    "Japan": "JPN",
}

_UNEMPLOYMENT_HINTS = re.compile(r"\b(unemployment|jobless(?:ness)?|labou?r force)\b", re.I)

# IMF WEO is country-keyed by ISO3 and, unlike OECD/MEI, covers India — so
# this is a third code map rather than a reuse of either existing one.
_GDP_COUNTRY_CODES = {
    "India": "IND",
    "United States": "USA",
    "United Kingdom": "GBR",
    "Germany": "DEU",
    "France": "FRA",
    "Canada": "CAN",
    "Japan": "JPN",
}

_GDP_HINTS = re.compile(r"\b(gdp|gross domestic product|economic growth)\b", re.I)
_GDP_GROWTH_HINTS = re.compile(r"\b(growth|rate|percent(?:age)?\s+change|expansion)\b", re.I)

# WEO is published as dated release datasets (WEO:2024-10, WEO:2025-04, …)
# rather than one rolling series, so the release has to be resolved at call
# time. Pinning one would silently go stale the way the retired Groq model
# ids in .env.example did; this falls back to a known-good release only if
# discovery fails outright.
_WEO_FALLBACK_RELEASE = "WEO:2025-04"
_weo_release_cache: str | None = None


def _detect_countries(query: str) -> list[str]:
    """Return every named country once, in the order mentioned."""
    matches: list[tuple[int, str]] = []
    for alias, canonical in _COUNTRY_ALIASES.items():
        match = re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", query, re.I)
        if match:
            matches.append((match.start(), canonical))
    countries: list[str] = []
    for _, country in sorted(matches):
        if country not in countries:
            countries.append(country)
    return countries


# ── Deterministic headline-indicator lookup ─────────────────────────────────
# DBnomics full-text search does not find headline macro indicators. Asking it
# for "india gdp" returns a CHELEM trade dataset, an OECD education-expenditure
# dataset and an IMF balance sheet — not one GDP series among them; "us
# unemployment" returns OECD social expenditure for AUSTRALIA, because "us"
# matched "US dollars". No amount of re-scoring fixes that: the right series is
# never in the candidate set.
#
# World Bank WDI series IDs are stable and fully predictable, so the common
# indicators are looked up directly instead: WB/WDI/A-{INDICATOR}-{ISO3}.
# Keyword search is kept below as the fallback for anything not in this table.
_WDI_INDICATORS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\b(gdp growth|economic growth|growth rate of gdp)\b", re.I),
     "NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)"),
    (re.compile(r"\bgdp per capita|per capita income\b", re.I),
     "NY.GDP.PCAP.CD", "GDP per capita (current US$)"),
    (re.compile(r"\btax[- ]to[- ]gdp|tax revenue\b", re.I),
     "GC.TAX.TOTL.GD.ZS", "Tax revenue (% of GDP)"),
    # Must come before the generic "gdp" rule below: "government debt as a
    # percentage of GDP" contains the literal word "gdp", so with the generic
    # rule first it always won (returning GDP growth data for a debt
    # question) and this specific pattern was dead code — never reachable.
    (re.compile(r"\b(government debt|public debt|central government debt)\b", re.I),
     "GC.DOD.TOTL.GD.ZS", "Central government debt, total (% of GDP)"),
    (re.compile(r"\b(gdp|gross domestic product)\b", re.I),
     "NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)"),
    (re.compile(r"\b(inflation|cpi|consumer price)\b", re.I),
     "FP.CPI.TOTL.ZG", "Inflation, consumer prices (annual %)"),
    (re.compile(r"\bunemploy\w*\b", re.I),
     "SL.UEM.TOTL.ZS", "Unemployment, total (% of labour force)"),
    (re.compile(r"\b(population)\b", re.I),
     "SP.POP.TOTL", "Population, total"),
    (re.compile(r"\b(real interest rate)\b", re.I),
     "FR.INR.RINR", "Real interest rate (%)"),
    (re.compile(r"\b(exports?)\b", re.I),
     "NE.EXP.GNFS.ZS", "Exports of goods and services (% of GDP)"),
    (re.compile(r"\b(imports?)\b", re.I),
     "NE.IMP.GNFS.ZS", "Imports of goods and services (% of GDP)"),
)


async def _fetch_wdi(client: httpx.AsyncClient, indicator: str, iso3: str) -> dict | None:
    """One World Bank WDI series by exact ID, or None."""
    sid = f"WB/WDI/A-{indicator}-{iso3}"
    try:
        r = await client.get(f"{_dbnomics_base()}/series/{sid}", params={"observations": "1"})
        if r.status_code != 200:
            return None
        docs = r.json().get("series", {}).get("docs", [])
        return docs[0] if docs else None
    except Exception:
        return None


async def _fetch_world_bank(
    client: httpx.AsyncClient, indicator: str, iso3: str
) -> list[tuple[str, float]]:
    """Fetch current WDI observations from the publisher before its mirrors."""
    try:
        response = await client.get(
            f"https://api.worldbank.org/v2/country/{iso3}/indicator/{indicator}",
            params={"format": "json", "per_page": 100},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
            return []
        return sorted(
            (str(row["date"]), float(row["value"]))
            for row in payload[1]
            if isinstance(row, dict)
            and re.fullmatch(r"\d{4}", str(row.get("date", "")))
            and isinstance(row.get("value"), (int, float))
            and not isinstance(row.get("value"), bool)
        )
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return []


def _wdi_match(query: str) -> tuple[str, str] | None:
    """(indicator_code, human_label) for the first headline indicator the
    question names. Order matters: the more specific patterns come first, so
    "GDP per capita" is not swallowed by the plain "gdp" rule."""
    for pattern, code, label in _WDI_INDICATORS:
        if pattern.search(query):
            return code, label
    return None


def _dbnomics_base() -> str:
    return os.getenv("DBNOMICS_API_BASE_URL", "https://api.db.nomics.world/v22").rstrip("/")


def _keywords(query: str) -> list[str]:
    return [
        w for w in re.findall(r"[A-Za-z]{3,}", query.lower())
        if w not in _STOPWORDS and (len(w) >= 4 or w in _SHORT_KEEP)
    ]


def _real_points(series: dict) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for p, v in zip(series.get("period", []), series.get("value", [])):
        if isinstance(v, (int, float)):
            out.append((p, float(v)))
    return out


async def _wdi_sources(query: str) -> list[WebSource] | None:
    """Deterministic World Bank sources for a named indicator plus a named
    country, or None when the question does not name both — None meaning "not
    applicable", so the targeted resolvers and full-text search below still get
    their turn. An empty list is a real answer: the countries were named and
    resolvable, but the data is not there."""
    countries = _detect_countries(query)
    indicator = _wdi_match(query)
    if indicator is None or not countries:
        return None
    code, label = indicator
    if any(not _ISO3.get(named_country) for named_country in countries):
        return None

    async with httpx.AsyncClient(timeout=8.0) as client:
        async def source_for(named_country: str) -> WebSource | None:
            country_iso3 = _ISO3[named_country]
            points = await _fetch_world_bank(client, code, country_iso3)
            if points:
                provider = "World Bank (WDI)"
                url = f"https://data.worldbank.org/indicator/{code}?locations={country_iso3}"
            else:
                doc = await _fetch_wdi(client, code, country_iso3)
                points = _real_points(doc) if doc else []
                provider = "World Bank (WDI) via DBnomics"
                url = f"{_dbnomics_base()}/series/WB/WDI/A-{code}-{country_iso3}"
            if not points:
                return None
            tail = points[-_MAX_POINTS:]
            values_txt = ", ".join(f"{p}: {v:g}" for p, v in tail)
            return WebSource(
                title=f"{label} — {named_country.title()}",
                url=url,
                snippet=(f"{provider}. {label} for {named_country.title()}. "
                         f"Latest available year: {tail[-1][0]}. Values — {values_txt}."),
                provider=provider,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                freshness="historical",
                observation=LiveObservation(
                    observation_id=f"obs_{uuid.uuid4().hex}", indicator=label,
                    value=str(tail[-1][1]),
                    unit="percent" if "%" in label else "provider-defined",
                    period=str(tail[-1][0]), provider=provider, source_url=url,
                    freshness="historical",
                ),
                series=tail,
            )

        sources = await asyncio.gather(*(source_for(c) for c in countries))
    # A comparison with one missing country must not masquerade as complete.
    if all(sources):
        return [source for source in sources if source is not None]
    if len(countries) > 1:
        return []
    return None


@dataclass
class SeriesMatch:
    """The full result of a DBnomics series lookup — WebSource text (via
    fetch_stats) and structured evidence (via evidence.py) are both built from
    this SAME object, so they can never disagree about the underlying numbers."""

    series_name: str
    points: list[tuple[str, float]] = field(default_factory=list)
    url: str = ""
    provider_name: str = ""
    dataset_name: str = ""


def _country_in_query(query: str) -> str | None:
    lowered = query.lower()
    for alias in sorted(_CPI_COUNTRIES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return _CPI_COUNTRIES[alias]
    return None


def countries_in_query(query: str) -> list[str]:
    """Return distinct canonical country labels in their query order."""
    lowered = query.lower()
    matches: list[tuple[int, str]] = []
    for alias in sorted(_CPI_COUNTRIES, key=len, reverse=True):
        match = re.search(rf"\b{re.escape(alias)}\b", lowered)
        if match:
            matches.append((match.start(), _CPI_COUNTRIES[alias]))
    ordered: list[str] = []
    for _, country in sorted(matches):
        if country not in ordered:
            ordered.append(country)
    return ordered


async def _find_cpi_series(query: str, window: int = 12) -> SeriesMatch | None:
    """Resolve common CPI prompts against IMF/CPI's explicit all-items
    series instead of trusting full-text dataset ranking. This prevents terms
    such as "distribution" from selecting an unrelated tax-distribution
    dataset that merely mentions the requested country.

    `window` is only widened by the two-series correlation path (see
    _find_series_for_phrase) — different providers publish on different
    lags, so trimming each side to its own last 12 points independently can
    leave zero overlapping periods once _find_two_series intersects them."""
    country = _country_in_query(query)
    if not country:
        return None
    # Country + CPI/inflation is specific enough to bypass generic full-text
    # ranking. Generic ranking previously failed outright for US/France and
    # matched an unrelated tax dataset for "India inflation". IMF/CPI's
    # explicit country/all-items dimensions are the safer common source for
    # cross-country comparison.
    if not re.search(r"\b(cpi|inflation|consumer prices?)\b", query, re.I):
        return None

    wants_quarterly = bool(re.search(r"\bquarter", query, re.I))
    wants_annual = bool(re.search(r"\b(annual|yearly|by year)\b", query, re.I))
    wants_change = bool(re.search(r"\binflation\b|percentage change|change in cpi", query, re.I))
    frequency_code = "Q" if wants_quarterly else ("A" if wants_annual else "M")
    indicator_code = "PCPI_PC_CP_A_PT" if wants_change else "PCPI_IX"
    country_code = _CPI_COUNTRY_CODES[country]
    requested_series_code = f"{frequency_code}.{country_code}.{indicator_code}"

    base = _dbnomics_base()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base}/series/IMF/CPI/{requested_series_code}",
                params={"observations": "1"},
            )
            response.raise_for_status()
            candidates = response.json().get("series", {}).get("docs", [])
    except Exception:
        return None

    preferred_frequency = "Quarterly" if wants_quarterly else ("Annual" if wants_annual else "Monthly")

    ranked: list[tuple[int, dict, list[tuple[str, float]]]] = []
    for candidate in candidates:
        name = str(candidate.get("series_name") or "")
        lowered = name.lower()
        points = _real_points(candidate)
        if country.lower() not in lowered or "all items" not in lowered or not points:
            continue
        score = 10
        if name.startswith(preferred_frequency):
            score += 6
        has_change = "percentage change" in lowered
        if has_change == wants_change:
            score += 5
        if "harmonized" not in lowered:
            score += 1
        if "previous year" in lowered:
            score += 1
        ranked.append((score, candidate, points))

    if not ranked:
        return None
    _, best, points = max(ranked, key=lambda item: item[0])
    # One shared window for both the grounding excerpt and visualization.
    # Twelve points are sufficient for a meaningful histogram/trend while
    # remaining small enough for the narrative model to inspect in full.
    points = points[-window:]
    series_name = str(best.get("series_name") or "series").replace("�", "·").strip()
    series_code = best.get("series_code", "")
    return SeriesMatch(
        series_name=series_name,
        points=points,
        url=f"{base}/series/IMF/CPI/{series_code}",
        provider_name="International Monetary Fund",
        dataset_name="Consumer Price Index (CPI)",
    )


async def _find_unemployment_series(query: str, window: int = 12) -> SeriesMatch | None:
    """Resolve unemployment-rate prompts against OECD/MEI's explicit
    harmonised-unemployment-rate series (Total > All persons, seasonally
    adjusted) instead of trusting full-text dataset ranking — the same
    data-honesty rationale as _find_cpi_series. Generic ranking previously
    matched a completely unrelated Argentina education/demographics dataset
    for "UK unemployment", since the plain word "unemployment" appears in
    hundreds of narrowly-segmented (age/sex/education) series across many
    countries with no reliable way to text-rank the right one."""
    country = _country_in_query(query)
    if not country or not _UNEMPLOYMENT_HINTS.search(query):
        return None
    country_code = _UNEMPLOYMENT_COUNTRY_CODES.get(country)
    if not country_code:
        return None

    base = _dbnomics_base()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base}/series/OECD/MEI/{country_code}.LRHUTTTT.STSA.M",
                params={"observations": "1"},
            )
            response.raise_for_status()
            candidates = response.json().get("series", {}).get("docs", [])
    except Exception:
        return None

    points: list[tuple[str, float]] = []
    series_name = ""
    series_code = ""
    for candidate in candidates:
        pts = _real_points(candidate)
        if not pts:
            continue
        points = pts
        series_name = str(candidate.get("series_name") or "series").replace("�", "·").strip()
        series_code = candidate.get("series_code", "")
        break
    if not points:
        return None

    points = points[-window:]
    return SeriesMatch(
        series_name=series_name,
        points=points,
        url=f"{base}/series/OECD/MEI/{series_code}",
        provider_name="OECD",
        dataset_name="Main Economic Indicators — Harmonised Unemployment Rate",
    )


async def _latest_weo_release(client: httpx.AsyncClient) -> str:
    """Newest IMF WEO release code on DBnomics, cached per process."""
    global _weo_release_cache
    if _weo_release_cache is not None:
        return _weo_release_cache
    try:
        codes: list[str] = []
        offset = 0
        while True:
            response = await client.get(
                f"{_dbnomics_base()}/datasets/IMF",
                params={"offset": offset, "limit": 100},
            )
            response.raise_for_status()
            payload = response.json().get("datasets", {})
            docs = payload.get("docs", [])
            if not docs:
                break
            codes += [str(d.get("code") or "") for d in docs]
            offset += len(docs)
            if offset >= payload.get("num_found", 0):
                break
        releases = sorted(c for c in codes if c.startswith("WEO:"))
        _weo_release_cache = releases[-1] if releases else _WEO_FALLBACK_RELEASE
    except Exception:
        _weo_release_cache = _WEO_FALLBACK_RELEASE
    return _weo_release_cache


async def _find_gdp_series(query: str, window: int = 12) -> SeriesMatch | None:
    """Resolve GDP prompts against IMF WEO's explicit national-accounts
    indicators instead of trusting full-text dataset ranking — the same
    rationale as _find_cpi_series and _find_unemployment_series. Generic
    ranking for "gdp india" matched CEPII's *trade balance as a share of
    GDP*, a completely different statistic that happens to carry "GDP" in
    its name.

    WEO carries IMF PROJECTIONS as well as outturns — the 2025-04 release
    runs to 2030 — and DBnomics exposes no observation-status flag to tell
    them apart. Charting a forecast as though it were history is precisely
    the kind of unverifiable claim this pipeline refuses to make elsewhere,
    so everything from the current year onward is dropped: WEO's own
    current-year figure is an estimate too, not an outturn.
    """
    country = _country_in_query(query)
    if not country or not _GDP_HINTS.search(query):
        return None
    country_code = _GDP_COUNTRY_CODES.get(country)
    if not country_code:
        return None

    # NGDP_RPCH is real GDP growth (percent change); NGDPD is GDP at current
    # prices in USD. "GDP rate"/"GDP growth" means the former, a bare "GDP"
    # the latter.
    wants_growth = bool(_GDP_GROWTH_HINTS.search(query))
    indicator = "NGDP_RPCH" if wants_growth else "NGDPD"

    base = _dbnomics_base()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            release = await _latest_weo_release(client)
            response = await client.get(
                f"{base}/series/IMF/{release}/{country_code}.{indicator}",
                params={"observations": "1"},
            )
            response.raise_for_status()
            candidates = response.json().get("series", {}).get("docs", [])
    except Exception:
        return None

    if not candidates:
        return None
    best = candidates[0]
    # Cut against the RELEASE year, not the calendar year. WEO:2025-04 was
    # published in April 2025, so its 2025 value is a projection even though
    # 2025 is now in the past — using the calendar year would have let one
    # forecast through while the series was still labelled "outturns only".
    # Whichever of the two is earlier is the last year that can be an outturn.
    release_year = int(release.split(":", 1)[-1][:4]) if release.split(":", 1)[-1][:4].isdigit() else 0
    cutoff = min(datetime.now(timezone.utc).year, release_year or 9999)
    points = [
        (period, value)
        for period, value in _real_points(best)
        if period[:4].isdigit() and int(period[:4]) < cutoff
    ]
    if not points:
        return None

    series_name = str(best.get("series_name") or "series").replace("�", "·").strip()
    series_code = best.get("series_code", "")
    return SeriesMatch(
        series_name=series_name,
        points=points[-window:],
        url=f"{base}/series/IMF/{release}/{series_code}",
        provider_name="International Monetary Fund",
        dataset_name=f"World Economic Outlook ({release.split(':', 1)[-1]} release), outturns only",
    )


async def _find_best_series(query: str) -> SeriesMatch | None:
    """One HTTP round-trip to DBnomics, returning the best-matching series (or
    None). The sole source of truth both fetch_stats() and the structured
    evidence path build from."""
    if not _STAT_HINTS.search(query):
        return None
    # A correlation-shaped query ("correlation between X and Y") names TWO
    # subjects — defer entirely to _find_two_series so this single-series
    # path never fires on half of a correlation question and populates
    # evidence with one confused, mixed-keyword series instead.
    if _split_correlation_subjects(query) is not None:
        return None
    # A named-country CPI/inflation request must never fall through to broad
    # full-text search: that is how "Canada inflation" matched an energy
    # projection mentioning the US Inflation Reduction Act. No exact CPI
    # series is safer than an unrelated numeric series.
    if _country_in_query(query) and re.search(r"\b(cpi|inflation|consumer prices?)\b", query, re.I):
        return await _find_cpi_series(query)
    # Same rationale for unemployment — see _find_unemployment_series'
    # docstring for the specific false-positive (Argentina demographics) this
    # replaces.
    if _country_in_query(query) and _UNEMPLOYMENT_HINTS.search(query):
        return await _find_unemployment_series(query)
    # And for GDP — generic ranking resolved "gdp india" to CEPII's trade
    # balance/GDP ratio. See _find_gdp_series' docstring.
    if _country_in_query(query) and _GDP_HINTS.search(query):
        return await _find_gdp_series(query)
    return await _find_generic_series(query)


async def _find_generic_series(text: str) -> SeriesMatch | None:
    """Full-text DBnomics search over arbitrary text (a whole query, or a
    single subject phrase split out of a two-subject correlation query — see
    _find_series_for_phrase). Split out of _find_best_series so the same
    matching logic can be reused per-phrase rather than only over a whole
    query, without duplicating it."""
    kws = _keywords(text)
    if not kws:
        return None
    # DBnomics full-text search does an AND over the query terms, so natural-
    # language filler ("over the years", "what is…") makes it return nothing.
    # Search with just the extracted keywords instead.
    kw_query = " ".join(kws)

    base = _dbnomics_base()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1) Find the most relevant dataset for the question.
            sr = await client.get(f"{base}/search", params={"q": kw_query, "limit": 3})
            sr.raise_for_status()
            datasets = sr.json().get("results", {}).get("docs", [])
            if not datasets:
                return None
            top = datasets[0]
            provider, dataset = top.get("provider_code"), top.get("code")
            if not provider or not dataset:
                return None

            # 2) Pull candidate series in that dataset, text-filtered by keywords.
            fr = await client.get(
                f"{base}/series/{provider}/{dataset}",
                params={"q": kw_query, "observations": "1", "limit": 40},
            )
            fr.raise_for_status()
            candidates = fr.json().get("series", {}).get("docs", [])
    except Exception:
        return None

    # 3) Pick the series with real values whose name best matches the keywords.
    best: dict | None = None
    best_score = 0
    best_points: list[tuple[str, float]] = []
    for s in candidates:
        points = _real_points(s)
        if not points:
            continue
        name = str(s.get("series_name") or "").lower()
        score = sum(1 for kw in kws if kw in name)
        if score > best_score:
            best, best_score, best_points = s, score, points

    # Require at least one keyword overlap — otherwise it's likely the wrong
    # series (e.g. a different country), so fall back to SearXNG instead.
    if best is None or best_score < 1:
        return None

    series_name = str(best.get("series_name") or "series").replace("�", "·").strip()
    series_code = best.get("series_code", "")
    url = f"{base}/series/{best.get('provider_code')}/{best.get('dataset_code')}/{series_code}"
    provider_name = str(top.get("provider_name") or best.get("provider_code") or "")
    dataset_name = str(top.get("name") or dataset or "")
    return SeriesMatch(
        series_name=series_name,
        points=best_points,
        url=url,
        provider_name=provider_name,
        dataset_name=dataset_name,
    )


# Two named subjects joined by correlation wording ("correlation between X
# and Y", "is X correlated with Y") — deliberately narrower than
# intent_classifier.py's _RELATIONSHIP_HINTS ("relationship between") so a
# statistical-correlation question and an entity-relationship-graph question
# never collide on the same phrasing.
# "and" / "vs" / "versus" are interchangeable subject separators throughout —
# "correlation between X and Y" and "correlation between X vs Y" are the same
# request, just phrased differently.
_AND_OR_VS = r"(?:and|vs\.?|versus)"

_CORRELATION_SPLIT_PATTERNS = (
    re.compile(rf"correlation (?:between|of)\s+(?P<a>.+?)\s+{_AND_OR_VS}\s+(?P<b>.+?)[\?\.]?\s*$", re.I),
    re.compile(r"(?:is\s+)?(?P<a>.+?)\s+correlated with\s+(?P<b>.+?)[\?\.]?\s*$", re.I),
    re.compile(r"correlate\s+(?P<a>.+?)\s+with\s+(?P<b>.+?)[\?\.]?\s*$", re.I),
    # "relationship between X and Y" is ambiguous with an entity-relationship
    # graph request (intent_classifier.py's _RELATIONSHIP_HINTS) — this
    # pattern lets a correlation query still resolve to real paired data when
    # intent_classifier.py's own disambiguation (are both named subjects
    # real economic-statistic terms?) has already decided it's CORRELATION,
    # not a fallback used blindly.
    re.compile(rf"relationship between\s+(?P<a>.+?)\s+{_AND_OR_VS}\s+(?P<b>.+?)[\?\.]?\s*$", re.I),
    re.compile(
        rf"compare\s+(?P<a>.+?)\s+{_AND_OR_VS}\s+(?P<b>.+?)"
        r"(?:\s+(?:using|as|with|in)\s+(?:an?\s+)?.*)?[\?\.]?\s*$",
        re.I,
    ),
    re.compile(
        rf"(?:create|show|plot|make).*?scatter plot\s+(?:comparing|of)\s+"
        rf"(?P<a>.+?)\s+{_AND_OR_VS}\s+(?P<b>.+?)[\?\.]?\s*$",
        re.I,
    ),
    # "show a scatter plot for A vs B" — no "correlation"/"compare" verb of
    # its own, just "for ... vs ..." carrying the whole request.
    re.compile(r"(?:scatter plot|chart|graph)\s+(?:for|of)\s+(?P<a>.+?)\s+vs\.?\s+(?P<b>.+?)[\?\.]?\s*$", re.I),
)


# A subject phrase captured by the split patterns above can still carry the
# query's time window and its presentation instruction, because those clauses
# sit AFTER the second subject and the patterns' optional trailing group only
# recognises a `using|as|with|in ...` tail. "Compare US inflation and
# unemployment over the last 5 years and display the result as a scatter plot"
# splits into "US inflation" / "unemployment over the last 5 years and display
# the result" — the second phrase resolves to nothing, so the whole pair is
# dropped and an answerable question returns the no-verified-data message.
# Neither clause narrows WHICH series is meant (the window is applied later,
# by _find_two_series' own intersection), so both are noise here.
_SUBJECT_NOISE_TAIL = re.compile(
    r"\s+(?:"
    r"(?:over|in|for|during|across)\s+the\s+(?:last|past|previous|next)\b"
    r"|(?:over|in|for)\s+the\s+(?:coming|recent)\b"
    r"|(?:and\s+)?(?:display|show|plot|render|draw|visuali[sz]e|present|graph|chart)\b"
    r"|as\s+(?:an?\s+)?[\w\s-]*?\b(?:chart|plot|graph|diagram|visuali[sz]ation|table)\b"
    r"|using\s+(?:an?\s+)?[\w\s-]*?\b(?:chart|plot|graph|diagram)\b"
    r"|\b(?:last|past|previous)\s+\d+\s+(?:years?|months?|quarters?|decades?)\b"
    r"|since\s+\d{4}\b"
    r").*$",
    re.I,
)


def _strip_subject_noise(phrase: str) -> str:
    """Drop a trailing time-window/presentation clause from one captured
    subject phrase. Returns the phrase unchanged when it carries neither, so
    a genuinely two-word subject ("India CPI") is never truncated."""
    return _SUBJECT_NOISE_TAIL.sub("", phrase).strip(" ,.;:-")


def _propagate_country(a: str, b: str) -> tuple[str, str]:
    """Carry an explicit country from whichever subject names it onto the one
    that doesn't. "Compare US inflation and unemployment" states the country
    once but means it for both sides, and the targeted per-country lookups
    (_find_cpi_series, _find_unemployment_series) both bail out entirely when
    no country is present. Worse than bailing, the generic full-text fallback
    then resolves a bare "unemployment" to an unrelated Argentina
    demographics series — so this is a correctness fix, not just a
    match-rate one. Only fills a gap; never overrides a country the phrase
    already names (a genuine cross-country comparison keeps both)."""
    country_a, country_b = _country_in_query(a), _country_in_query(b)
    if country_a and not country_b:
        return a, f"{country_a} {b}"
    if country_b and not country_a:
        return f"{country_b} {a}", b
    return a, b


def _split_correlation_subjects(query: str) -> tuple[str, str] | None:
    """Split a correlation-shaped query into its two named subject phrases
    (e.g. "India CPI" / "UK inflation"), or None if the query doesn't name
    two distinct subjects this way."""
    for pattern in _CORRELATION_SPLIT_PATTERNS:
        m = pattern.search(query)
        if m:
            a = _strip_subject_noise(m.group("a").strip())
            b = _strip_subject_noise(m.group("b").strip())
            if a and b:
                # Comparison prompts often state the measure only once:
                # "compare Germany and France inflation". Inherit that
                # explicit statistic onto the country-only side so both
                # targeted lookups resolve the same concept.
                combined = f"{a} {b}"
                metric_match = re.search(r"\b(cpi|inflation|consumer prices?)\b", combined, re.I)
                if metric_match:
                    metric = metric_match.group(1)
                    if not _STAT_HINTS.search(a):
                        a = f"{a} {metric}"
                    if not _STAT_HINTS.search(b):
                        b = f"{b} {metric}"
                return _propagate_country(a, b)
    return None


async def _find_series_for_phrase(phrase: str, window: int = 12) -> SeriesMatch | None:
    """Resolve ONE named subject phrase to a real DBnomics series — the same
    CPI-targeted-then-generic search _find_best_series applies to a whole
    query, scoped to a single phrase so each side of a correlation query can
    be looked up independently."""
    if _country_in_query(phrase) and re.search(r"\b(cpi|inflation|consumer prices?)\b", phrase, re.I):
        return await _find_cpi_series(phrase, window=window)
    if _country_in_query(phrase) and _UNEMPLOYMENT_HINTS.search(phrase):
        return await _find_unemployment_series(phrase, window=window)
    if _country_in_query(phrase) and _GDP_HINTS.search(phrase):
        return await _find_gdp_series(phrase, window=window)
    return await _find_generic_series(phrase)


# Two independent providers publish on different lags (IMF's CPI is far more
# current than OECD's harmonised-unemployment release) — asking each side for
# only its own last 12 points before intersecting can leave zero overlap even
# though both series are real and both cover the requested country. Widening
# the window before the intersection (never after) is what actually fixes
# this; _find_generic_series is unaffected since it never pre-trims.
_CORRELATION_LOOKUP_WINDOW = 60


async def _find_two_series(query: str) -> tuple[SeriesMatch, SeriesMatch] | None:
    """Resolve a correlation-shaped query to two REAL, independently-fetched
    series, realigned to only the periods both actually report — never an
    interpolated or assumed value. Returns None (not a fabricated pairing)
    unless both subjects resolve AND share at least 3 common periods, the
    same minimum a meaningful trend/histogram already requires elsewhere."""
    subjects = _split_correlation_subjects(query)
    if subjects is None:
        return None
    phrase_a, phrase_b = subjects
    match_a, match_b = await asyncio.gather(
        _find_series_for_phrase(phrase_a, window=_CORRELATION_LOOKUP_WINDOW),
        _find_series_for_phrase(phrase_b, window=_CORRELATION_LOOKUP_WINDOW),
    )
    if match_a is None or match_b is None:
        return None

    values_a = dict(match_a.points)
    values_b = dict(match_b.points)
    common_periods = sorted(set(values_a) & set(values_b))[-12:]
    if len(common_periods) < 3:
        return None

    return (
        replace(match_a, points=[(p, values_a[p]) for p in common_periods]),
        replace(match_b, points=[(p, values_b[p]) for p in common_periods]),
    )


def _build_source(match: SeriesMatch) -> WebSource:
    # Include the complete normalized evidence window. live_data.py builds
    # charts from this same `match.points` list, so prose and visual values
    # are guaranteed to cover exactly the same observations.
    values_txt = ", ".join(f"{p}: {v:g}" for p, v in match.points)
    snippet = (
        f"Official data via DBnomics ({match.provider_name} — {match.dataset_name}). "
        f"Series: {match.series_name}. Recent values — {values_txt}."
    )
    return WebSource(
        title=f"DBnomics — {match.series_name}"[:200],
        url=match.url,
        snippet=snippet,
        provider=match.provider_name or "DBnomics",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        freshness="historical",
        # The same points, structured, so live_data.build_forced_chart can chart
        # a real fetched series instead of trusting the model to re-parse its
        # own prose back into numbers. Proven and correlated lookups stay
        # prose-only on purpose: two series over one axis have no single value
        # per period to plot.
        series=list(match.points),
    )


def _build_pair_source(match_a: SeriesMatch, match_b: SeriesMatch) -> WebSource:
    pairs_txt = ", ".join(
        f"{p}: {va:g}/{vb:g}" for (p, va), (_, vb) in zip(match_a.points, match_b.points)
    )
    snippet = (
        f"Official data via DBnomics. Series A: {match_a.series_name} "
        f"({match_a.provider_name} — {match_a.dataset_name}). Series B: {match_b.series_name} "
        f"({match_b.provider_name} — {match_b.dataset_name}). "
        f"Paired values (period: A/B) — {pairs_txt}."
    )
    return WebSource(
        title=f"DBnomics — {match_a.series_name} vs {match_b.series_name}"[:200],
        url=match_a.url,
        snippet=snippet,
        provider="DBnomics",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        freshness="historical",
    )


async def fetch_stats(query: str) -> list[WebSource]:
    """Return WebSources with matching economic series' recent values when
    the question is a statistics query and a confident match is found; else [].

    A named indicator plus a named country resolves deterministically to an
    exact World Bank series (_wdi_sources). Anything else falls through to the
    targeted CPI/unemployment/GDP resolvers and then to full-text search."""
    if not _STAT_HINTS.search(query):
        return []
    wdi = await _wdi_sources(query)
    if wdi is not None:
        return wdi
    match = await _find_best_series(query)
    return [_build_source(match)] if match else []


async def fetch_correlation_stats(query: str) -> list[WebSource]:
    """Return one WebSource with both series' paired values when the question
    names two real, independently-resolvable subjects; else []."""
    pair = await _find_two_series(query)
    return [_build_pair_source(*pair)] if pair else []
