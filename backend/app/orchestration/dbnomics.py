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

import os
import re
from datetime import date

import httpx

from app.orchestration.websearch import WebSource

# Live-computed source, no persistent catalog row — see WEBSEARCH_GOVERNED_
# SOURCE_ID's docstring in websearch.py for why this bypasses the licence
# gate instead of needing a seeded Source row.
DBNOMICS_GOVERNED_SOURCE_ID = "src-kriton-dbnomics-live"

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

_STOPWORDS = {"the", "and", "for", "with", "what", "show", "give", "rate", "data",
              "value", "latest", "current", "chart", "graph", "over", "years", "year"}

# Real gap (2026-08-05): "What is the current US unemployment rate?" matched
# and confidently returned a completely wrong-country series — "Argentina –
# Female – 25 to 34 years – ... – Unemployment" — because _keywords()'s
# 4-letter minimum silently dropped "US" entirely, leaving "unemployment" as
# the ONLY search term with no geography constraint at all. Any country's
# unemployment series then scored the same (1 keyword match), and whichever
# happened to be evaluated first won — a live, safety-relevant bug for a
# finance bot, since the actual number is wildly different by country. Maps
# how a user names a country/region to how DBnomics series names actually
# spell it, so a named country becomes a HARD filter (see fetch_stats)
# rather than a keyword that's too short to even be extracted.
_COUNTRY_HINTS: dict[str, list[str]] = {
    "us": ["united states", "usa", "u.s."],
    "usa": ["united states", "usa", "u.s."],
    "america": ["united states", "usa", "u.s."],
    "united states": ["united states", "usa", "u.s."],
    "uk": ["united kingdom", "u.k.", "great britain"],
    "britain": ["united kingdom", "u.k.", "great britain"],
    "united kingdom": ["united kingdom", "u.k.", "great britain"],
    "eu": ["euro area", "european union", "eurozone"],
    "eurozone": ["euro area", "european union", "eurozone"],
    "euro area": ["euro area", "european union", "eurozone"],
    "india": ["india"],
    "china": ["china"],
    "japan": ["japan"],
    "canada": ["canada"],
    "australia": ["australia"],
    "germany": ["germany"],
    "france": ["france"],
    "uae": ["united arab emirates", "uae"],
}


def _dbnomics_base() -> str:
    return os.getenv("DBNOMICS_API_BASE_URL", "https://api.db.nomics.world/v22").rstrip("/")


# Real gap (2026-08-05): same failure mode as the country codes above —
# "GDP" is only 3 letters, so "What is India's GDP growth rate?" silently
# lost the ONE word that actually names the statistic, leaving just "india
# growth" as the search — no wonder it matched an unrelated India trade-
# flow dataset instead of anything about GDP. These short economic
# abbreviations bypass the general 4-letter minimum the same way country
# codes do.
_SHORT_STAT_TERMS = {"gdp", "cpi", "gni", "gnp"}


def _keywords(query: str) -> list[str]:
    words = re.findall(r"[A-Za-z]{2,}", query.lower())
    return [
        w for w in words
        if w not in _STOPWORDS and (len(w) >= 4 or w in _SHORT_STAT_TERMS)
    ]


def _country_hint(query: str) -> list[str] | None:
    """Longest-key match so "united states" wins over a bare "us" substring
    hit elsewhere in the sentence. Returns the accepted DBnomics series-name
    spellings for that country/region, or None if the query names none."""
    lowered = query.lower()
    best: tuple[str, list[str]] | None = None
    for key, names in _COUNTRY_HINTS.items():
        if re.search(rf"\b{re.escape(key)}\b", lowered) and (best is None or len(key) > len(best[0])):
            best = (key, names)
    return best[1] if best else None


def _real_points(series: dict) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for p, v in zip(series.get("period", []), series.get("value", [])):
        if isinstance(v, (int, float)):
            out.append((p, float(v)))
    return out


_CURRENT_STAT_QUERY = re.compile(r"\b(current|currently|latest|today|now|most recent)\b", re.I)


def _observation_year_month(period: str) -> tuple[int, int] | None:
    """Parse the common DBnomics annual, quarterly and monthly period forms."""
    match = re.fullmatch(r"((?:19|20)\d{2})(?:-(?:(\d{2})|Q([1-4])))?", str(period))
    if match is None:
        return None
    year = int(match.group(1))
    if match.group(2):
        month = int(match.group(2))
        if not 1 <= month <= 12:
            return None
    elif match.group(3):
        month = int(match.group(3)) * 3
    else:
        month = 12
    return year, month


def _is_fresh_for_current_question(period: str, *, today: date | None = None) -> bool:
    """A source older than 24 months cannot answer a request for a current value.

    The deliberately generous window accommodates annual official series while
    still rejecting clearly stale feeds. Unparseable periods fail closed.
    """
    parsed = _observation_year_month(period)
    if parsed is None:
        return False
    current = today or date.today()
    age_months = (current.year - parsed[0]) * 12 + current.month - parsed[1]
    return 0 <= age_months <= 24


_US_NAMES = ["united states", "usa", "u.s."]

# Common OECD/policy-microdata qualifiers that mean "this is a specific
# sub-metric ABOUT the headline statistic's context, not the statistic
# itself" — e.g. "net replacement RATE in unemployment" is a benefits
# generosity measure, not the unemployment rate. Filters both candidate
# datasets and candidate series; a query that actually asks about one of
# these narrower concepts still gets it, since this only excludes names —
# it never touches what the user typed.
_NARROWER_METRIC_HINTS = re.compile(
    r"\breplacement rate|tax rate|participation tax|by field of study|"
    r"tertiary.educated|educational attainment|"
    # Real gap (2026-08-06): "What is Japan's current inflation rate?"
    # picked OECD's "Economic statistics ROPI-adjusted for inflation -
    # Regions" as the top dataset purely because its own description
    # mentions "inflation" as a methodology note (ROPI = regionally
    # price-index-adjusted), then confidently served an EMPLOYMENT series
    # from within it (~38 million persons) captioned as Japan's inflation
    # rate. "adjusted for inflation" names a methodology applied to some
    # OTHER metric, never the inflation rate itself — same shape as the
    # replacement-rate/tax-rate gaps above.
    r"\bROPI\b|adjusted for inflation",
    re.I,
)


async def fetch_stats(query: str) -> list[WebSource]:
    """Return one WebSource with a matching economic series' recent values when
    the question is a statistics query and a confident match is found; else [].

    Real gap (2026-08-05): DBnomics' own free-text dataset search is
    unreliable for exactly the most common queries — "inflation united
    states" doesn't return a real CPI dataset in its top 3 results at all,
    just an unrelated EIA energy-outlook dataset that happens to mention
    "Inflation Reduction Act" and an OECD regional-statistics dataset. US
    inflation and US GDP already have dedicated, curated, working
    mechanisms (BLS CPI / BEA NIPA, wired directly in orchestration/
    service.py) — defer to those rather than risk surfacing DBnomics' wrong
    match alongside (or instead of) the correct one. Only skips when the
    query is US-implicit or explicitly names the US; a genuinely
    non-US inflation/GDP question (nothing else covers those) still goes
    through DBnomics as normal.
    """
    if not _STAT_HINTS.search(query):
        return []
    kws = _keywords(query)
    if not kws:
        return []
    country_names = _country_hint(query)
    if country_names is None or country_names == _US_NAMES:
        from app.domains.reference_data.service import is_inflation_query, is_gdp_query

        if is_inflation_query(query) or is_gdp_query(query):
            return []
    # DBnomics full-text search does an AND over the query terms, so natural-
    # language filler ("over the years", "what is…") makes it return nothing.
    # Search with just the extracted keywords instead — plus the country's
    # canonical spelling (dropped from `kws` by the 4-letter minimum for
    # short codes like "US"), so the dataset search itself is geography-
    # aware, not just the candidate filter below.
    kw_query = " ".join(kws + ([country_names[0]] if country_names else []))

    base = _dbnomics_base()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1) Find the most relevant dataset for the question. DBnomics'
            # own search is dominated, for terms like "unemployment", by
            # OECD policy/benefits microdata that mentions the term only as
            # context ("Net replacement rates IN unemployment", "tax rate
            # for those claiming unemployment benefits") rather than being
            # about the plain headline rate — skip any dataset whose OWN
            # name signals it's a different, narrower metric than what was
            # actually asked for, rather than digging into a dataset that's
            # fundamentally the wrong one.
            sr = await client.get(f"{base}/search", params={"q": kw_query, "limit": 3})
            sr.raise_for_status()
            datasets = [
                d for d in sr.json().get("results", {}).get("docs", [])
                if not _NARROWER_METRIC_HINTS.search(str(d.get("name") or ""))
            ]
            if not datasets:
                return []
            top = datasets[0]
            provider, dataset = top.get("provider_code"), top.get("code")
            if not provider or not dataset:
                return []

            # 2) Pull candidate series in that dataset, text-filtered by keywords.
            fr = await client.get(
                f"{base}/series/{provider}/{dataset}",
                params={"q": kw_query, "observations": "1", "limit": 40},
            )
            fr.raise_for_status()
            candidates = fr.json().get("series", {}).get("docs", [])
    except Exception:
        return []

    # 3) Pick the series with real values whose name best matches the keywords.
    # A named country/region is a HARD filter, not just another scored
    # keyword — mismatching it is exactly the wrong-country-statistic
    # failure mode this whole function exists to prevent (see _COUNTRY_
    # HINTS' comment above), so a candidate that doesn't mention the named
    # country is excluded outright rather than merely scored lower.
    best: dict | None = None
    best_score = 0
    best_points: list[tuple[str, float]] = []
    for s in candidates:
        points = _real_points(s)
        if not points:
            continue
        if _CURRENT_STAT_QUERY.search(query) and not _is_fresh_for_current_question(points[-1][0]):
            continue
        name = str(s.get("series_name") or "").lower()
        if country_names is not None and not any(c in name for c in country_names):
            continue
        if _NARROWER_METRIC_HINTS.search(name):
            continue
        score = sum(1 for kw in kws if kw in name)
        # Real gap (2026-08-06): "What is Japan's current inflation rate?"
        # ties on keyword overlap between the genuine headline figure
        # ("Japan – CPI > All items > Total") and dozens of narrow COICOP
        # sub-category breakdowns ("Food and non-alcoholic beverages",
        # "Clothing and footwear", ...) that ALSO contain every one of the
        # query's keywords in their own name — the tie was broken only by
        # incidental API result ORDER, silently serving one arbitrary
        # category's contribution captioned as the whole country's rate.
        # Every one of these candidates' names ends in "> Total > Total"
        # regardless of category (that "Total" is a different dimension —
        # e.g. total across regions — not "all items"), so only "all
        # items" itself reliably identifies the genuine headline series. A
        # plain, unqualified query never asked for one specific category,
        # so it's preferred whenever nothing else distinguishes candidates.
        if "all items" in name:
            score += 0.5
        if re.search(r"\b(?:annual growth rate|inflation rate)\b", name):
            score += 1.0
        if "contribution to annual inflation" in name:
            score -= 1.0
        if score > best_score:
            best, best_score, best_points = s, score, points

    # Require at least one keyword overlap — otherwise it's likely the wrong
    # series (e.g. a different country), so fall back to SearXNG instead.
    if best is None or best_score < 1:
        return []

    series_name = str(best.get("series_name") or "series").replace("�", "·").strip()
    tail = best_points[-6:]
    values_txt = ", ".join(f"{p}: {v:g}" for p, v in tail)
    series_code = best.get("series_code", "")
    url = f"{base}/series/{best.get('provider_code')}/{best.get('dataset_code')}/{series_code}"
    provider_name = top.get("provider_name") or best.get("provider_code")
    snippet = (
        f"Official data via DBnomics ({provider_name} — {top.get('name', dataset)}). "
        f"Series: {series_name}. Recent values — {values_txt}."
    )
    return [
        WebSource(
            title=f"DBnomics — {series_name}"[:200],
            url=url,
            snippet=snippet,
        )
    ]
