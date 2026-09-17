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
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

import httpx

from app.orchestration.websearch import WebSource

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

_STOPWORDS = {
    "the", "and", "for", "with", "what", "show", "give", "rate", "data",
    "value", "values", "latest", "current", "chart", "graph", "over", "years", "year",
    "distribution", "spread", "histogram", "figures", "last", "past", "few", "quarters",
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


def _dbnomics_base() -> str:
    return os.getenv("DBNOMICS_API_BASE_URL", "https://api.db.nomics.world/v22").rstrip("/")


def _keywords(query: str) -> list[str]:
    return [
        w for w in re.findall(r"[A-Za-z]{3,}", query.lower())
        if w not in _STOPWORDS and (len(w) >= 4 or w in {"cpi", "gdp", "gni", "gnp"})
    ]


def _real_points(series: dict) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for p, v in zip(series.get("period", []), series.get("value", [])):
        if isinstance(v, (int, float)):
            out.append((p, float(v)))
    return out


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


def _split_correlation_subjects(query: str) -> tuple[str, str] | None:
    """Split a correlation-shaped query into its two named subject phrases
    (e.g. "India CPI" / "UK inflation"), or None if the query doesn't name
    two distinct subjects this way."""
    for pattern in _CORRELATION_SPLIT_PATTERNS:
        m = pattern.search(query)
        if m:
            a, b = m.group("a").strip(), m.group("b").strip()
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
                return a, b
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
    """Return one WebSource with a matching economic series' recent values when
    the question is a statistics query and a confident match is found; else []."""
    match = await _find_best_series(query)
    return [_build_source(match)] if match else []


async def fetch_correlation_stats(query: str) -> list[WebSource]:
    """Return one WebSource with both series' paired values when the question
    names two real, independently-resolvable subjects; else []."""
    pair = await _find_two_series(query)
    return [_build_pair_source(*pair)] if pair else []
