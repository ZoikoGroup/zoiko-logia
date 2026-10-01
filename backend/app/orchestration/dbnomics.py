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
    # These four were missing, and the gate runs BEFORE every resolver, so a
    # question naming one of them returned [] without anything being looked up:
    #   - "government revenue" mattered most. "US government revenue as
    #     percentage of GDP" passed the gate only because it happened to
    #     contain the word "GDP", and then fell through to the generic WDI
    #     "gdp" rule below — so a revenue question was answered with GDP
    #     GROWTH for every one of the five countries that have no dedicated
    #     revenue route. "Germany government revenue" (no "GDP" in it) was
    #     rejected outright and returned NO_SOURCE.
    #   - "current account" was rejected outright for all ten countries, even
    #     though the deterministic WDI indicator for it already existed
    #     (BN.CAB.XOKA.GD.ZS) and was correctly ordered ahead of the GDP rule.
    r"government revenue|general government revenue|current account|"
    r"fiscal balance|budget balance|budget surplus|"
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
    "indian": "India",
    # Capitals-only: see _CASE_SENSITIVE_ALIASES. Without this, "IN GDP growth"
    # and "IN inflation rate" named no country, while the same question with
    # any of the eight other ISO codes resolved.
    "in": "India",
    "us": "United States",
    "u.s.": "United States",
    "usa": "United States",
    "united states": "United States",
    "america": "United States",
    "american": "United States",
    "uk": "United Kingdom",
    # GB is the actual ISO 3166-1 alpha-2 code; UK is the colloquial form.
    "gb": "United Kingdom",
    "united kingdom": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "germany": "Germany",
    "german": "Germany",
    "deutschland": "Germany",
    "france": "France",
    "french": "France",
    "canada": "Canada",
    "canadian": "Canada",
    "japan": "Japan",
    "japanese": "Japan",
    "ireland": "Ireland",
    "irish": "Ireland",
    # Bare ISO-2 codes. Every one of these is matched CASE-SENSITIVELY — see
    # _CASE_SENSITIVE_ALIASES below for why case is the only thing separating a
    # country from an ordinary word. "FR GDP growth" and "JP GDP growth" name
    # France and Japan; "fr" and "jp" in lower case do not, and must not.
    #
    # Before this, "DE GDP growth rate" named no country at all, and the generic
    # full-text search — which accepts any country's series when it has no claim
    # to check — answered with ISTAT. Correctly formatted Italian GDP growth for
    # a question that asked about Germany. The country check could not catch it
    # because there was no recognised country to check against.
    "de": "Germany",
    "fr": "France",
    "jp": "Japan",
    "cn": "China",
    "ca": "Canada",
    "ie": "Ireland",
    # "AU" was missing here entirely while country_scope.py already recognised it,
    # so the two country tables disagreed about which questions named which
    # economy: "AU GDP growth rate" was scoped for the country-only connectors
    # and simultaneously had no country claim to check a DBnomics series against.
    # A bare code that is also an ordinary word ("au" is the French preposition
    # for "at/in the") stays capitals-only, exactly as "us" does.
    "au": "Australia",
    # Australia is here DELIBERATELY even though IMF/CPI publishes no AU
    # series. Listing it is what stops "Australia CPI" falling through to
    # generic full-text search, which is what returned ABS *energy* inflation
    # instead of headline CPI. With Australia recognised, _find_cpi_series
    # simply finds no IMF series and returns None — an honest gap that the ABS
    # connector (abs_australia.py) then fills from the statistical agency
    # itself. Silence beats a confidently wrong number from a neighbour series.
    "australia": "Australia",
    "australian": "Australia",
    # China publishes an IMF/CPI series ("M.CN.PCPI_..." verified live), so it
    # is recognised here rather than left to full-text search.
    "china": "China",
    "chinese": "China",
    "prc": "China",
}

# Aliases matched CASE-SENSITIVELY rather than with re.I, because the alias is
# also an ordinary English word. "us" is the pronoun, so "the company told us
# about GDP" resolved to the United States; and because a second named country
# then looks like a multi-country question whose negative wins, "give us the
# France inflation figure" named the US *and* France, which makes every
# country-scoped connector refuse it and returns NO_SOURCE for a question that
# only ever mentioned one country. Case is the only thing separating the two,
# and "US" in capitals is the conventional spelling of the country.
#
# Only "us" qualifies: it is the one alias here that is a real English word.
# "in" and "cn" are absent from every alias table in this module entirely (the
# first is an ordinary word, the second hopelessly ambiguous), and "prc" is an
# IMF publisher code with no English meaning.
# "in" and "gb" were absent from this table entirely, which meant "GB GDP growth"
# and "IN GDP growth" named no country at all. GB is the real ISO 3166-1 alpha-2
# code for the United Kingdom (UK is the colloquial form) and IN is India's, so
# both are ordinary identifiers a caller may emit. The reason "in" was kept out -
# it is an ordinary English preposition - is answered by matching capitals only,
# exactly as is already done for us, de, au, ca, fr, jp, ie and cn. Lowercase "in"
# and lowercase "gb" are still refused; capitals are unambiguous.
_CASE_SENSITIVE_ALIASES = frozenset(
    {"us", "de", "fr", "jp", "cn", "ca", "ie", "au", "gb", "in"}
)

_CPI_COUNTRY_CODES = {
    "India": "IN",
    "United States": "US",
    "United Kingdom": "GB",
    "Germany": "DE",
    "France": "FR",
    "Canada": "CA",
    "Japan": "JP",
    "Ireland": "IE",
    "China": "CN",
    # Australia absent on purpose — see _CPI_COUNTRIES above.
}

# Country anchoring. A statistic is meaningless without knowing whose it is, so
# when the question names a country the chosen series MUST be that country's.
# Aliases resolve to ISO3 directly (rather than to the display labels above), so
# this pair of tables serves the deterministic World Bank lookup below.
_COUNTRY_ALIASES: dict[str, str] = {
    "us": "united states", "usa": "united states", "america": "united states",
    "american": "united states", "states": "united states",
    "uk": "united kingdom", "gb": "united kingdom", "britain": "united kingdom",
    "british": "united kingdom",
    "england": "united kingdom", "kingdom": "united kingdom",
    "india": "india", "indian": "india", "in": "india",
    "china": "china", "chinese": "china", "prc": "china",
    "japan": "japan", "japanese": "japan",
    "germany": "germany", "german": "germany",
    "france": "france", "french": "france",
    "canada": "canada", "canadian": "canada",
    "australia": "australia", "australian": "australia",
    # "eire" is the official Irish-language name on the CSO's own publications;
    # without it a question phrased from a CSO table header would resolve to no
    # country at all and fall through to generic full-text search.
    "ireland": "ireland", "irish": "ireland", "eire": "ireland",
    "uae": "united arab emirates", "emirates": "united arab emirates",
    "singapore": "singapore", "brazil": "brazil", "brazilian": "brazil",
    "italy": "italy", "spain": "spain", "mexico": "mexico",
    "indonesia": "indonesia", "nigeria": "nigeria", "pakistan": "pakistan",
    "bangladesh": "bangladesh", "russia": "russia", "korea": "korea",
    "greece": "greece", "greek": "greece",
    "south africa": "south africa", "south african": "south africa",
    "netherlands": "netherlands", "dutch": "netherlands", "holland": "netherlands",
    "switzerland": "switzerland", "swiss": "switzerland",
    "sweden": "sweden", "swedish": "sweden",
    "norway": "norway", "norwegian": "norway",
    "denmark": "denmark", "danish": "denmark",
    "finland": "finland", "finnish": "finland",
    "ireland": "ireland", "irish": "ireland",
    "belgium": "belgium", "belgian": "belgium",
    "austria": "austria", "austrian": "austria",
    "portugal": "portugal", "portuguese": "portugal",
    "poland": "poland", "polish": "poland",
    "turkey": "turkey", "turkiye": "turkey", "turkish": "turkey",
    "argentina": "argentina", "argentine": "argentina", "argentinian": "argentina",
    "chile": "chile", "chilean": "chile",
    "colombia": "colombia", "colombian": "colombia",
    "peru": "peru", "peruvian": "peru",
    "egypt": "egypt", "egyptian": "egypt",
    "kenya": "kenya", "kenyan": "kenya",
    "ghana": "ghana", "ghanaian": "ghana",
    "morocco": "morocco", "moroccan": "morocco",
    "saudi arabia": "saudi arabia", "saudi": "saudi arabia",
    "qatar": "qatar", "qatari": "qatar",
    "kuwait": "kuwait", "kuwaiti": "kuwait",
    "israel": "israel", "israeli": "israel",
    "vietnam": "vietnam", "vietnamese": "vietnam",
    "thailand": "thailand", "thai": "thailand",
    "malaysia": "malaysia", "malaysian": "malaysia",
    "philippines": "philippines", "filipino": "philippines",
    "sri lanka": "sri lanka", "sri lankan": "sri lanka",
    "nepal": "nepal", "nepalese": "nepal", "nepali": "nepal",
    "new zealand": "new zealand",
    "hong kong": "hong kong",
    "ukraine": "ukraine", "ukrainian": "ukraine",
    "czech republic": "czech republic", "czechia": "czech republic", "czech": "czech republic",
    "hungary": "hungary", "hungarian": "hungary",
    "romania": "romania", "romanian": "romania",
}

# ISO-3 codes, because many DBnomics series carry the country only in the code
# (e.g. ".../ARG.F.Y25T34..."), not in the display name.
_ISO3: dict[str, str] = {
    "united states": "USA", "united kingdom": "GBR", "india": "IND",
    "china": "CHN", "japan": "JPN", "germany": "DEU", "france": "FRA",
    "canada": "CAN", "australia": "AUS", "ireland": "IRL",
    "united arab emirates": "ARE",
    "singapore": "SGP", "brazil": "BRA", "italy": "ITA", "spain": "ESP",
    "mexico": "MEX", "indonesia": "IDN", "nigeria": "NGA", "pakistan": "PAK",
    "bangladesh": "BGD", "russia": "RUS", "korea": "KOR", "greece": "GRC",
    "south africa": "ZAF",
    "netherlands": "NLD",
    "switzerland": "CHE",
    "sweden": "SWE",
    "norway": "NOR",
    "denmark": "DNK",
    "finland": "FIN",
    "ireland": "IRL",
    "belgium": "BEL",
    "austria": "AUT",
    "portugal": "PRT",
    "poland": "POL",
    "turkey": "TUR",
    "argentina": "ARG",
    "chile": "CHL",
    "colombia": "COL",
    "peru": "PER",
    "egypt": "EGY",
    "kenya": "KEN",
    "ghana": "GHA",
    "morocco": "MAR",
    "saudi arabia": "SAU",
    "qatar": "QAT",
    "kuwait": "KWT",
    "israel": "ISR",
    "vietnam": "VNM",
    "thailand": "THA",
    "malaysia": "MYS",
    "philippines": "PHL",
    "sri lanka": "LKA",
    "nepal": "NPL",
    "new zealand": "NZL",
    "hong kong": "HKG",
    "ukraine": "UKR",
    "czech republic": "CZE",
    "hungary": "HUN",
    "romania": "ROU",
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
    "Ireland": "IRL",
    "Australia": "AUS",
}

def _detect_country(query: str) -> str | None:
    """Canonical country named in the question, or None. Multi-word names are
    checked first so "united states" is not resolved twice via "states"."""
    q = query.lower()
    for phrase in ("united states", "united kingdom", "united arab emirates", "south africa",
                   "saudi arabia", "sri lanka", "new zealand", "hong kong", "czech republic"):
        if phrase in q:
            return phrase
    for token in re.findall(r"[A-Za-z]{2,}", q):
        canonical = _COUNTRY_ALIASES.get(token)
        if canonical:
            return canonical
    return None


def canonical_country(name: str) -> str | None:
    """Canonical country (a key of _ISO3) for a name, alias or ISO-3 code the
    caller already isolated — e.g. a tool argument — or None if unsupported."""
    value = name.strip().lower()
    if value in _ISO3:
        return value
    alias = _COUNTRY_ALIASES.get(value)
    if alias in _ISO3:
        return alias
    for country, iso3 in _ISO3.items():
        if iso3 == value.upper():
            return country
    return None


def supported_countries() -> list[str]:
    return sorted(_ISO3)


def _detect_countries(query: str) -> list[str]:
    """Return every named country once, in the order mentioned."""
    matches: list[tuple[int, str]] = []
    for alias, canonical in _COUNTRY_ALIASES.items():
        pattern = rf"(?<!\w){re.escape(alias)}(?!\w)"
        # See _CASE_SENSITIVE_ALIASES: bare "us" must not match the pronoun.
        # The alias is stored lower-case, so match the capitals form instead.
        if alias in _CASE_SENSITIVE_ALIASES:
            match = re.search(
                rf"(?<!\w){re.escape(alias.upper())}(?!\w)", query)
        else:
            match = re.search(pattern, query, re.I)
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
     "GC.TAX.TOTL.GD.ZS", "Tax revenue, central government only (% of GDP)"),
    # Must come before the generic "gdp" rule below: "government debt as a
    # percentage of GDP" contains the literal word "gdp", so with the generic
    # rule first it always won (returning GDP growth data for a debt
    # question) and this specific pattern was dead code — never reachable.
    (re.compile(r"\b(government debt|public debt|central government debt)\b", re.I),
     "GC.DOD.TOTL.GD.ZS", "Central government debt, total (% of GDP)"),
    # Like the government-debt rule above, these must precede the generic
    # "gdp" rule: "trade balance as a share of GDP" contains the literal word
    # "gdp", so a later position would make the generic growth series win for
    # a trade question.
    (re.compile(r"\b(trade balance|net exports?|external balance)\b", re.I),
     "NE.RSB.GNFS.ZS", "External balance on goods and services (% of GDP)"),
    (re.compile(r"\b(current account(?: balance)?)\b", re.I),
     "BN.CAB.XOKA.GD.ZS", "Current account balance (% of GDP)"),
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
            f"{_world_bank_base()}/country/{iso3}/indicator/{indicator}",
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


async def _indicator_source(
    client: httpx.AsyncClient, code: str, label: str, country: str
) -> WebSource | None:
    """One World Bank WDI indicator for one canonical country (a key of
    _ISO3): the publisher first, the DBnomics mirror as fallback, else None."""
    country_iso3 = _ISO3[country]
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
    values_txt = ", ".join(f"{p}: {v:.15g}" for p, v in tail)
    return WebSource(
        title=f"{label} — {country.title()}",
        url=url,
        snippet=(f"{provider}. {label} for {country.title()}. "
                 f"Latest available year: {tail[-1][0]}. Values — {values_txt}."),
        provider=provider,
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


async def fetch_indicator_sources(code: str, label: str, countries: list[str]) -> list[WebSource | None]:
    """Structured entry point: one slot per country, in order (None where that
    country has no data) — what the get_economic_indicator tool calls with the
    model's typed arguments, and what fetch_stats() calls after parsing the
    question. Every country must be a key of _ISO3."""
    async with httpx.AsyncClient(timeout=8.0) as client:
        return list(await asyncio.gather(*(_indicator_source(client, code, label, c) for c in countries)))


def _dbnomics_base() -> str:
    return os.getenv("DBNOMICS_API_BASE_URL", "https://api.db.nomics.world/v22").rstrip("/")


def _world_bank_base() -> str:
    return os.getenv("WORLD_BANK_API_BASE_URL", "https://api.worldbank.org/v2").strip().rstrip("/")


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
    iso3 = _ISO3.get(country or "", "")
    if indicator and iso3:
        code, label = indicator
        sources = await fetch_indicator_sources(code, label, countries)
        available = [source for source in sources if source is not None]
        if len(available) == len(sources):
            return available
        if len(countries) > 1:
            if not available:
                return []
            # A comparison with one missing country must not masquerade as
            # complete — but dropping every country for it answered "I don't
            # have the figures" when three of four were available. Keep them,
            # and state plainly which countries have no figure.
            missing = [country for country, source in zip(countries, sources) if source is None]
            return available + [WebSource(
                title=f"World Bank — no {label} figure for {', '.join(missing)}",
                url="https://data.worldbank.org",
                snippet=(
                    f"The World Bank publishes no recent {label} figure for {', '.join(missing)}. "
                    "Do not state or estimate a value for it; say it is not available from this source."
                ),
                provider="World Bank",
            )]
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
    #
    # The country check below is the general guard against answering a
    # country question with another country's data. It is not a special case:
    # DBnomics' full-text search ranks on text alone, and a dataset about
    # African trade will happily outrank one about US trade for the query
    # "US trade balance" if its name happens to contain the keyword. That is
    # exactly the confirmed wrong-data failure this replaces — a real series,
    # correctly formatted, for a different continent. Naming a country makes
    # the answer's country load-bearing, so the series must then demonstrably
    # BE that country. When it is not, returning None hands the question to
    # the FRED/ABS/BoC/Treasury connectors, which are keyed to the country.
    named_country = _country_in_query(text)
    # No country named, and the question is about an economy we do not cover
    # ("world", "Italy"). Answering from whichever supported country ranked
    # first is a guess, and for an out-of-scope geography it is a confident
    # wrong answer — see _names_out_of_scope_geometry.
    if not named_country and _names_out_of_scope_geometry(text):
        return None
    best: dict | None = None
    best_score = 0
    best_points: list[tuple[str, float]] = []
    for s in candidates:
        points = _real_points(s)
        if not points:
            continue
        name = str(s.get("series_name") or "").lower()
        score = sum(1 for kw in kws if kw in name)
        if score > best_score and _series_is_country(name, named_country):
            best, best_score, best_points = s, score, points

    # Require at least one keyword overlap — otherwise it's likely the wrong
    # series (e.g. a different country), so fall back to SearXNG instead.
    if best is None or best_score < 1:
        return None

    series_name = str(best.get("series_name") or "series").replace("�", "·").strip()
    tail = best_points[-_MAX_POINTS:]
    values_txt = ", ".join(f"{p}: {v:.15g}" for p, v in tail)
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
    if _country_in_query(phrase) and _FISCAL_HINTS.search(phrase):
        return await _find_weo_fiscal_series(phrase, window=window)
    if _country_in_query(phrase) and _GDP_HINTS.search(phrase):
        return await _find_gdp_series(phrase, window=window)
    if _country_in_query(phrase) and _POLICY_RATE_HINTS.search(phrase):
        return await _find_policy_rate_series(phrase, window=window)
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
    # A match with no points still describes itself, so it stays renderable - it
    # simply has no latest value to publish, and must not pretend otherwise.
    observation = None
    if match.points:
        latest_period, latest_value = match.points[-1]
        # A single series has exactly one latest value, so it is attached here
        # rather than left to be re-read out of the snippet. This was the last
        # large live-data path still shipping prose without a LiveObservation:
        # Ireland unemployment, for example, resolved and charted fine but
        # arrived with observation=None, so nothing downstream could read its
        # value, unit or period without parsing English. It also makes the
        # staleness auditable instead of invisible - that same Irish series
        # stops at 2023-12, and an attached period is what exposes the three
        # year gap to a reviewer.
        #
        # The unit is only claimed as "percent" when the series name itself
        # shows one, matching the WDI builder above. SeriesMatch does not retain
        # DBnomics' own unit metadata, so "provider-defined" is the honest
        # remainder: better an unadorned label than a wrong one.
        observation = LiveObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            indicator=match.series_name,
            value=str(latest_value),
            unit="percent" if "%" in match.series_name else "provider-defined",
            period=str(latest_period),
            provider=match.provider_name or "DBnomics",
            source_url=match.url,
            freshness="historical",
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
        # own prose back into numbers. Correlated lookups stay prose-only on
        # purpose (_build_pair_source): two series over one axis have no single
        # value per period to plot.
        series=list(match.points),
        observation=observation,
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
    # Fiscal questions must resolve before the WDI path gets a turn:
    # "budget deficit as a share of GDP" and "government revenue as a share of
    # GDP" both contain the word "GDP", so the generic WDI GDP-growth rule
    # would otherwise grab them and answer with GDP GROWTH — the exact
    # wrong-statistic failure this module exists to stop. Verified before this
    # change: US, UK, Ireland, Canada and Australia all got
    # NY.GDP.MKTP.KD.ZG for a government-revenue question.
    #
    # This is not restricted to _NEW_FIVE. _find_weo_fiscal_series decides per
    # subject which countries it will serve (debt stays with the first five's
    # existing WDI/FRED/Treasury routes; revenue and deficit, which had no
    # route at all there, are served from WEO), so the guard here only has to
    # make sure the resolver is consulted before WDI.
    country = _country_in_query(query)
    if country and _FISCAL_HINTS.search(query):
        fiscal = await _find_weo_fiscal_series(query)
        if fiscal:
            return [_build_source(fiscal)]
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
