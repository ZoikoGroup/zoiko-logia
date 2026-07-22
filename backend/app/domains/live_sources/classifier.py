"""
Keyword-based "does this query want live external data" detector — the live-
source analogue of app.orchestration.retrieve.py's infer_category(), but
answering a different question (which external indicator + country, not
which internal document category). Kept as a separate module rather than
folded into infer_category() since the two never need to run against each
other's tables.

Provider routing is data-driven via _COUNTRY_PROVIDER_OVERRIDES: a
country's dedicated connectors (e.g. GB -> Bank of England/ONS) are a
registry entry, not an "if country_code == 'GB'" branch — adding a future
country's connector (e.g. India/RBI) means adding an entry to that dict,
not new code in detect_live_data_intent(). Anything a country's overrides
don't cover (or a country with no overrides at all) falls through to the
generic World Bank indicator list unchanged.

Country resolution priority: the caller's `jurisdiction` (the UI's
jurisdiction dropdown — AskKritonRequest.jurisdiction) wins whenever it's
set. Two distinct "no specific country" cases are NOT treated the same:
  - jurisdiction == "" (Any/unset): a genuine absence of a selection —
    query-text keywords ("UK", "India"...) are used as a fallback signal,
    and country-agnostic phrases like "Bank Rate" may still resolve to
    their implied country.
  - jurisdiction is a non-empty value with no live-data country mapping
    (e.g. "UAE", "IFRS", "EU" — frameworks/regions, or any country without
    a connector yet): this is an EXPLICIT selection, so detect_live_data_intent
    returns None outright rather than falling back to query-text matching or
    an implied-country shortcut. Conflating this with the unset case was a
    real, reported bug: selecting "UAE" (which this module has no country
    mapping for) while asking "What is the Bank Rate?" fell back to the
    implied-country shortcut and silently returned the UK's Bank Rate —
    substituting a country the user never asked for. An explicit selection
    with no matching data must produce no live source, never another
    country's data.
  - jurisdiction mapping to a known country (UK/US/India/...) always wins
    over query text, even when the query names a different country.

Anything unmatched returns None — the live-data path is a no-op for those
queries, leaving the existing document pipeline completely unaffected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.domains.live_sources.schemas import LiveDataIntent

# Ordered so multi-word phrases are checked before their single-word
# substrings (e.g. "gdp growth" before "gdp") would matter if overlapping
# keywords existed; kept as a plain dict since none currently overlap, but
# order is preserved for future additions.
_INDICATOR_KEYWORDS: list[tuple[str, str, str]] = [
    ("gdp growth", "NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)"),
    ("gdp", "NY.GDP.MKTP.CD", "GDP (current US$)"),
    ("inflation", "FP.CPI.TOTL.ZG", "Inflation, consumer prices (annual %)"),
    ("cpi", "FP.CPI.TOTL.ZG", "Inflation, consumer prices (annual %)"),
    ("unemployment", "SL.UEM.TOTL.ZS", "Unemployment (% of total labor force)"),
]

# Single source of truth for country resolution — every alias (whether it
# came from free-text query keywords or the jurisdiction dropdown's exact
# values) is looked up here, lowercased, rather than maintaining separate
# hardcoded per-country tables that could drift out of sync.
# AskKritonRequest.jurisdiction values (frontend/app/ask-kriton/page.tsx's
# JURISDICTIONS dropdown: "", "UK", "US", "US-CA", "IFRS", "UAE", "India",
# "EU") are matched by lowercasing them and looking them up here too —
# "IFRS"/"UAE"/"EU" are deliberately absent (frameworks/regions, not single
# countries a live connector covers), same as "" (Any/unset), so those fall
# back to query-text keyword matching below.
_COUNTRY_ALIASES: dict[str, tuple[str, str]] = {
    "india": ("IN", "India"),
    "united states": ("US", "United States"),
    "usa": ("US", "United States"),
    "us": ("US", "United States"),
    "us-ca": ("US", "United States"),
    "united kingdom": ("GB", "United Kingdom"),
    "uk": ("GB", "United Kingdom"),
}

# Precompiled word-boundary patterns for scanning free-text queries — a
# plain "alias in lowered" substring check (the original implementation)
# matched "us" inside "business", silently resolving a query like "What is
# the inflation rate for our business unit?" to United States. \b...\b
# requires the alias appear as a standalone token (bounded by whitespace,
# punctuation, or string edges), not as a fragment of a longer word.
# _country_from_jurisdiction() below doesn't need this: it looks up the
# UI dropdown's exact value via a plain dict .get(), never a substring scan.
_COUNTRY_ALIAS_PATTERNS: dict[str, re.Pattern] = {
    alias: re.compile(rf"\b{re.escape(alias)}\b") for alias in _COUNTRY_ALIASES
}

_DEFAULT_COUNTRY = ("WLD", "World")


@dataclass(frozen=True)
class _CountryOverrideRule:
    keywords: tuple[str, ...]
    provider_key: str
    indicator_code: str
    indicator_label: str
    # When True, this rule's keywords imply the country even with no
    # jurisdiction/query-text country signal at all (e.g. "bank rate" is
    # UK-specific vocabulary nobody else uses) — but never against an
    # explicit, conflicting jurisdiction selection.
    implies_country: bool = False


# Per-country dedicated-connector rules, checked in order for whichever
# country was resolved (via jurisdiction or query text). A country with no
# entry here — or one whose rules don't match — falls through to the
# generic World Bank indicator list below. This is the registry a new
# country's connector gets added to; detect_live_data_intent() never
# branches on a specific country code.
_COUNTRY_PROVIDER_OVERRIDES: dict[str, list[_CountryOverrideRule]] = {
    "GB": [
        _CountryOverrideRule(
            keywords=("bank rate",), provider_key="bank_of_england",
            indicator_code="IUDBEDR", indicator_label="Bank Rate",
            implies_country=True,
        ),
        _CountryOverrideRule(
            keywords=("repo rate", "interest rate"), provider_key="bank_of_england",
            indicator_code="IUDBEDR", indicator_label="Bank Rate",
        ),
        _CountryOverrideRule(
            keywords=("inflation", "cpi"), provider_key="ons",  # "cpi" also matches "cpih"
            indicator_code="CP00", indicator_label="CPIH Index (Overall Index, 2015=100)",
        ),
        _CountryOverrideRule(
            keywords=("gdp",), provider_key="ons",
            indicator_code="A--T", indicator_label="Monthly GDP Index (Seasonally Adjusted, 2016=100)",
        ),
        _CountryOverrideRule(
            keywords=("unemployment",), provider_key="ons",
            indicator_code="UNEMPLOYMENT_RATE", indicator_label="Unemployment Rate (16+, Seasonally Adjusted)",
        ),
    ],
    "US": [
        _CountryOverrideRule(
            keywords=("fed funds rate", "federal funds rate", "fed rate"), provider_key="fred",
            indicator_code="FEDFUNDS", indicator_label="Federal Funds Effective Rate",
            implies_country=True,  # "Fed funds rate" is unambiguously US vocabulary, same as "Bank Rate" for GB
        ),
        _CountryOverrideRule(
            keywords=("treasury yield", "10-year treasury", "treasury rate"), provider_key="fred",
            indicator_code="DGS10", indicator_label="10-Year Treasury Constant Maturity Rate",
            implies_country=True,
        ),
    ],
}

# country_code -> label, derived from the alias table so it's never
# maintained as a second, separately-hardcoded mapping.
_COUNTRY_LABELS: dict[str, str] = dict(_COUNTRY_ALIASES.values())

# OECD tier — a "generic indicator, any resolved country" provider like
# World Bank, not a per-country override like Bank of England/ONS/FRED
# (those exist because they're that ONE country's own official source;
# OECD's corporate tax rate dataflow spans OECD members plus the
# Inclusive Framework — 140+ jurisdictions — so it's checked once, after
# the per-country overrides fail to match, before falling through to
# World Bank). REF_AREA is ISO alpha-3, unlike this module's own alpha-2
# country_code, hence the small translation table — extend it as more
# countries are added to _COUNTRY_ALIASES (only extend once a real query
# against OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT confirms that country has data,
# same discipline used for every connector this session).
_OECD_REF_AREA_BY_COUNTRY_CODE: dict[str, str] = {
    "GB": "GBR",
    "US": "USA",
    "IN": "IND",
}
_OECD_INDICATOR_KEYWORDS: list[tuple[str, str, str]] = [
    ("corporate tax rate", "CIT_C", "Combined Corporate Income Tax Rate"),
    ("corporate income tax rate", "CIT_C", "Combined Corporate Income Tax Rate"),
]


def _match_oecd_indicator(country_code: str, lowered: str) -> LiveDataIntent | None:
    ref_area = _OECD_REF_AREA_BY_COUNTRY_CODE.get(country_code)
    if ref_area is None:
        return None
    for keyword, indicator_code, indicator_label in _OECD_INDICATOR_KEYWORDS:
        if keyword in lowered:
            return LiveDataIntent(
                provider_key="oecd",
                # Encodes both the REF_AREA and the OECD measure code in one
                # string — same composite-encoding convention already used
                # for Frankfurter's "USD_GBP" — so LiveDataIntent's schema
                # needs no new field.
                indicator_code=f"{ref_area}:{indicator_code}",
                indicator_label=indicator_label,
                country_code=country_code,
                country_label=_COUNTRY_LABELS.get(country_code, country_code),
            )
    return None


def _match_country_in_text(lowered: str) -> tuple[str, str]:
    return next(
        (
            value
            for alias, value in _COUNTRY_ALIASES.items()
            if _COUNTRY_ALIAS_PATTERNS[alias].search(lowered)
        ),
        _DEFAULT_COUNTRY,
    )


def _country_from_jurisdiction(jurisdiction: str) -> tuple[str, str] | None:
    return _COUNTRY_ALIASES.get(jurisdiction.lower())


def _rule_to_intent(rule: _CountryOverrideRule, country_code: str) -> LiveDataIntent:
    return LiveDataIntent(
        provider_key=rule.provider_key,
        indicator_code=rule.indicator_code,
        indicator_label=rule.indicator_label,
        country_code=country_code,
        country_label=_COUNTRY_LABELS.get(country_code, country_code),
        # Tier 1 latency optimization — see LiveDataIntent.skip_document_search's
        # docstring. Reuses implies_country rather than a separate flag:
        # both mean "this phrase is unambiguous enough to resolve without
        # any other signal," which is exactly the bar for skipping document
        # search too.
        skip_document_search=rule.implies_country,
    )


def _match_implied_country_rule(lowered: str) -> LiveDataIntent | None:
    """Only called when jurisdiction is genuinely unset — rules with
    implies_country=True may resolve a country from query text alone
    (e.g. "Bank Rate" -> UK), but ONLY if the query text doesn't already
    name a different, resolvable country. Without this guard, "What is
    the Bank Rate in India?" would silently return the UK's Bank Rate —
    the same "don't substitute a country nobody asked for" bug the
    jurisdiction-dropdown priority logic guards against above, just
    reachable through query text instead of the dropdown (a real,
    reported case: the live Bank of England source was fetched and cited
    for an India query, even though the LLM itself declined to answer
    from it)."""
    text_country_code, _ = _match_country_in_text(lowered)
    for country_code, rules in _COUNTRY_PROVIDER_OVERRIDES.items():
        if text_country_code != _DEFAULT_COUNTRY[0] and text_country_code != country_code:
            continue
        for rule in rules:
            if rule.implies_country and any(keyword in lowered for keyword in rule.keywords):
                return _rule_to_intent(rule, country_code)
    return None


def _match_country_override(country_code: str, lowered: str) -> LiveDataIntent | None:
    for rule in _COUNTRY_PROVIDER_OVERRIDES.get(country_code, []):
        if any(keyword in lowered for keyword in rule.keywords):
            return _rule_to_intent(rule, country_code)
    return None


# FX pairs are inherently cross-country — a jurisdiction dropdown selection
# doesn't gate them the way an indicator does (asking for a USD/GBP rate
# with jurisdiction=UAE selected should still work). Checked first, before
# any country/jurisdiction resolution.
_FX_TRIGGER_KEYWORDS = ("exchange rate", "conversion rate", " to ", "/")
_CURRENCY_ALIASES: dict[str, str] = {
    "us dollar": "USD", "dollar": "USD", "usd": "USD",
    "british pound": "GBP", "sterling": "GBP", "pound": "GBP", "gbp": "GBP",
    "euro": "EUR", "eur": "EUR",
    "indian rupee": "INR", "rupee": "INR", "inr": "INR",
}


def detect_fx_intent(query: str) -> LiveDataIntent | None:
    lowered = query.lower()
    if not any(trigger in lowered for trigger in _FX_TRIGGER_KEYWORDS):
        return None

    # Find every currency alias present, keep only the earliest occurrence
    # per currency code, then order by position in the text — "from X to Y"
    # phrasing reads naturally as (X=from, Y=to) this way, without real NLP.
    earliest_index_by_code: dict[str, int] = {}
    for alias, code in _CURRENCY_ALIASES.items():
        idx = lowered.find(alias)
        if idx != -1:
            earliest_index_by_code[code] = min(idx, earliest_index_by_code.get(code, idx))
    if len(earliest_index_by_code) < 2:
        return None

    ordered_codes = [code for code, _ in sorted(earliest_index_by_code.items(), key=lambda kv: kv[1])]
    from_code, to_code = ordered_codes[0], ordered_codes[1]
    return LiveDataIntent(
        provider_key="frankfurter",
        indicator_code=f"{from_code}_{to_code}",
        indicator_label=f"{from_code}/{to_code} exchange rate",
        country_code="FX",
        country_label="Global",
    )


# Company-lookup: a genuinely different question ("tell me about company X")
# than the country-indicator pattern above. Deliberately a separate function
# — live_sources/service.py tries detect_live_data_intent() first and only
# falls back to this one if it found nothing, never both. Company name
# extraction is simple keyword-anchored pattern matching, not NER — no match
# means no live source, same fallback discipline as everything else here.
_COMPANY_TRIGGER_KEYWORDS = (
    "filing", "filings", "financials", "financial statements", "annual report",
    "10-k", "10-q", "revenue", "net income",
)
# The capture group deliberately stays case-SENSITIVE ([A-Z] literal, not
# under the (?i:...) scoped-insensitive groups around it) — it's how a
# company name ("Apple", "Apple Inc") is told apart from an ordinary
# sentence-initial capitalized word ("Show me Apple's filings" must not
# capture "Show me Apple", only "Apple"). Each word in the captured phrase
# must itself start with a capital letter, so a lowercase filler word like
# "me" breaks the run and is excluded.
_COMPANY_NAME_PATTERNS = (
    re.compile(r"(?i:for|of)\s+((?:[A-Z][\w.&-]*\s*)+)(?:'s)?(?:\s+(?i:filings?|financials?|revenue|assets|10-k|10-q)|\?|$)"),
    # 's? (not 's) — a name already ending in "s" takes a bare trailing
    # apostrophe in standard English possessive form ("Industries'", not
    # "Industries's"). Requiring the literal "s" made every plural company
    # name (e.g. "Reliance Industries' filings") fail to extract at all,
    # silently skipping the live company-lookup path entirely — confirmed
    # live this session. Singular names ("Apple's", "Tesco's") still match,
    # since 's? accepts the "s" being present too.
    re.compile(r"((?:[A-Z][\w.&-]*\s*)+)'s?\s+(?i:filings?|financials?|revenue|assets|net income)"),
)
_FINANCIAL_CONCEPT_KEYWORDS: list[tuple[str, str, str]] = [
    ("net income", "NetIncomeLoss", "Net Income"),
    ("revenue", "Revenues", "Revenue"),
    ("total assets", "Assets", "Total Assets"),
    ("assets", "Assets", "Total Assets"),
]
_DEFAULT_FINANCIAL_CONCEPT = ("Assets", "Total Assets")


def _extract_company_name(query: str) -> str | None:
    for pattern in _COMPANY_NAME_PATTERNS:
        match = pattern.search(query)
        if match:
            name = match.group(1).strip().rstrip(".,")
            if name:
                return name
    return None


def _extract_financial_concept(lowered: str) -> tuple[str, str]:
    for keyword, code, label in _FINANCIAL_CONCEPT_KEYWORDS:
        if keyword in lowered:
            return code, label
    return _DEFAULT_FINANCIAL_CONCEPT


def detect_company_lookup_intent(query: str, jurisdiction: str = "") -> LiveDataIntent | None:
    lowered = query.lower()
    if not any(keyword in lowered for keyword in _COMPANY_TRIGGER_KEYWORDS):
        return None

    company_name = _extract_company_name(query)
    if company_name is None:
        return None

    # Company lookup requires an explicit, resolvable jurisdiction to know
    # which registry to query (US -> SEC EDGAR, UK -> Companies House) — no
    # jurisdiction, or one that doesn't resolve to a country, means we don't
    # know which registry to check, so this returns None rather than
    # guessing (same "don't substitute" discipline used throughout).
    jurisdiction_country = _country_from_jurisdiction(jurisdiction) if jurisdiction else None
    if jurisdiction_country is None:
        return None
    country_code, country_label = jurisdiction_country

    if country_code == "US":
        indicator_code, indicator_label = _extract_financial_concept(lowered)
        return LiveDataIntent(
            provider_key="sec_edgar", indicator_code=indicator_code, indicator_label=indicator_label,
            country_code=country_code, country_label=country_label, company_query=company_name,
        )
    if country_code == "GB":
        return LiveDataIntent(
            provider_key="companies_house", indicator_code="profile", indicator_label="Company Profile",
            country_code=country_code, country_label=country_label, company_query=company_name,
        )
    # Every other resolved country (currently just India, until more are
    # added to _COUNTRY_ALIASES) falls back to GLEIF — keyless LEI registry
    # lookup with coverage beyond a single jurisdiction (see
    # connectors/gleif.py's docstring for the trade-off: LEI-holding
    # entities only, not a universal company register like Companies House).
    return LiveDataIntent(
        provider_key="gleif", indicator_code="profile", indicator_label="Company Profile",
        country_code=country_code, country_label=country_label, company_query=company_name,
    )


def detect_live_data_intent(query: str, jurisdiction: str = "") -> LiveDataIntent | None:
    lowered = query.lower()

    fx_intent = detect_fx_intent(query)
    if fx_intent is not None:
        return fx_intent

    if jurisdiction:
        # An explicit selection was made. If it doesn't map to a known
        # live-data country (UAE/IFRS/EU, or any country without a
        # connector yet), stop here — never fall back to query-text
        # matching or an implied-country shortcut, both of which could
        # substitute a country the user never asked for.
        jurisdiction_country = _country_from_jurisdiction(jurisdiction)
        if jurisdiction_country is None:
            return None
        country_code, country_label = jurisdiction_country
    else:
        # Genuinely unset ("Any") — query text is the only signal available,
        # so country-agnostic phrases may resolve via their implied country.
        implied = _match_implied_country_rule(lowered)
        if implied is not None:
            return implied
        country_code, country_label = _match_country_in_text(lowered)

    override = _match_country_override(country_code, lowered)
    if override is not None:
        return override
    # No per-country override matched (either this country has none, or its
    # rules didn't match this indicator, e.g. GDP/unemployment for GB) —
    # try OECD's generic (any-resolved-country) indicators next, before
    # falling through to World Bank.

    oecd_match = _match_oecd_indicator(country_code, lowered)
    if oecd_match is not None:
        return oecd_match

    indicator = next(
        ((code, label) for keyword, code, label in _INDICATOR_KEYWORDS if keyword in lowered),
        None,
    )
    if indicator is not None:
        indicator_code, indicator_label = indicator
        return LiveDataIntent(
            provider_key="world_bank",
            indicator_code=indicator_code,
            indicator_label=indicator_label,
            country_code=country_code,
            country_label=country_label,
        )

    # Semantic fallback if keyword check did not match
    semantic_match = _semantic_indicator_match(query, country_code, country_label)
    if semantic_match is not None:
        return semantic_match

    return None


import math
from app.domains.rag.embeddings import get_embed_model, get_query_embedding_cached

_INDICATOR_EXEMPLARS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("IUDBEDR", "Bank Rate", "bank_of_england", ("bank rate", "interest rate", "repo rate", "boe rate")),
    ("FEDFUNDS", "Federal Funds Effective Rate", "fred", ("fed funds rate", "federal funds rate", "fed rate")),
    ("DGS10", "10-Year Treasury Constant Maturity Rate", "fred", ("treasury yield", "10-year treasury", "treasury rate")),
    ("CP00", "CPIH Index (Overall Index, 2015=100)", "ons", ("inflation", "cpi", "cpih", "consumer prices", "cost of living", "price index")),
    ("A--T", "Monthly GDP Index (Seasonally Adjusted, 2016=100)", "ons", ("gdp", "gdp growth", "economic growth", "monthly gdp", "economic output")),
    ("UNEMPLOYMENT_RATE", "Unemployment Rate (16+, Seasonally Adjusted)", "ons", ("unemployment", "jobless rate", "employment rate")),
]

_exemplar_embeddings: dict[str, list[list[float]]] = {}

def _get_exemplar_embeddings() -> dict[str, list[list[float]]]:
    global _exemplar_embeddings
    if not _exemplar_embeddings:
        model = get_embed_model()
        for indicator_code, _, _, exemplars in _INDICATOR_EXEMPLARS:
            _exemplar_embeddings[indicator_code] = [list(get_query_embedding_cached(ex)) for ex in exemplars]
    return _exemplar_embeddings

def cosine_similarity(v1: list[float] | tuple[float, ...], v2: list[float] | tuple[float, ...]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(a * a for a in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)

def _semantic_indicator_match(query: str, country_code: str, country_label: str) -> LiveDataIntent | None:
    try:
        q_emb = get_query_embedding_cached(query)
        exemplar_embs = _get_exemplar_embeddings()
        
        best_code = None
        best_score = 0.40  # similarity threshold
        
        for code, p_embs in exemplar_embs.items():
            max_sim = max(cosine_similarity(q_emb, p_emb) for p_emb in p_embs)
            if max_sim > best_score:
                best_score = max_sim
                best_code = code
                
        if not best_code:
            return None
            
        # Map the best matched indicator code to the appropriate provider for this country
        if best_code == "IUDBEDR" and country_code == "GB":
            return LiveDataIntent(
                provider_key="bank_of_england", indicator_code="IUDBEDR", indicator_label="Bank Rate",
                country_code=country_code, country_label=country_label
            )
        if best_code == "FEDFUNDS" and country_code == "US":
            return LiveDataIntent(
                provider_key="fred", indicator_code="FEDFUNDS", indicator_label="Federal Funds Effective Rate",
                country_code=country_code, country_label=country_label
            )
        if best_code == "DGS10" and country_code == "US":
            return LiveDataIntent(
                provider_key="fred", indicator_code="DGS10", indicator_label="10-Year Treasury Constant Maturity Rate",
                country_code=country_code, country_label=country_label
            )
            
        if country_code == "GB":
            if best_code == "CP00":
                return LiveDataIntent(
                    provider_key="ons", indicator_code="CP00", indicator_label="CPIH Index (Overall Index, 2015=100)",
                    country_code=country_code, country_label=country_label
                )
            if best_code == "A--T":
                return LiveDataIntent(
                    provider_key="ons", indicator_code="A--T", indicator_label="Monthly GDP Index (Seasonally Adjusted, 2016=100)",
                    country_code=country_code, country_label=country_label
                )
            if best_code == "UNEMPLOYMENT_RATE":
                return LiveDataIntent(
                    provider_key="ons", indicator_code="UNEMPLOYMENT_RATE", indicator_label="Unemployment Rate (16+, Seasonally Adjusted)",
                    country_code=country_code, country_label=country_label
                )
                
        if best_code == "CP00":
            return LiveDataIntent(
                provider_key="world_bank", indicator_code="FP.CPI.TOTL.ZG", indicator_label="Inflation, consumer prices (annual %)",
                country_code=country_code, country_label=country_label
            )
        if best_code == "A--T":
            return LiveDataIntent(
                provider_key="world_bank", indicator_code="NY.GDP.MKTP.CD", indicator_label="GDP (current US$)",
                country_code=country_code, country_label=country_label
            )
        if best_code == "UNEMPLOYMENT_RATE":
            return LiveDataIntent(
                provider_key="world_bank", indicator_code="SL.UEM.TOTL.ZS", indicator_label="Unemployment (% of total labor force)",
                country_code=country_code, country_label=country_label
            )
            
        return None
    except Exception:
        return None
