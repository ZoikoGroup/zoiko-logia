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
    # Common real-world synonyms for the UK missed until a real query
    # ("How many people are out of work in Britain right now?") silently
    # defaulted to World Bank's WLD/"World" aggregate instead of GB —
    # confirmed live. "england"/"scotland"/etc. deliberately NOT added here:
    # those are constituent countries, not reliably synonymous with "UK" in
    # every context, unlike "Britain"/"Great Britain" which colloquially
    # always mean the UK.
    "britain": ("GB", "United Kingdom"),
    "great britain": ("GB", "United Kingdom"),
    "blighty": ("GB", "United Kingdom"),
    # The jurisdiction dropdown's "EU" used to resolve to nothing, which meant
    # selecting it disabled live data entirely — a real reported case: "What is
    # the ECB deposit facility rate?" with EU selected returned "the retrieved
    # context does not mention the ECB deposit facility rate", because the
    # explicit-selection rule below correctly refuses to fall back to
    # query-text matching, and there was nothing for EU to match.
    #
    # EURO_AREA rather than a country: it is the scope the ECB's own series are
    # published for, and it is already the key _COUNTRY_PROVIDER_OVERRIDES uses
    # for them. Providers that have no euro-area aggregate simply return None
    # for it, which is the correct outcome — see _WORLD_BANK_COUNTRY_CODES for
    # the one translation this needs.
    "eu": ("EURO_AREA", "Euro area"),
    "euro area": ("EURO_AREA", "Euro area"),
    "eurozone": ("EURO_AREA", "Euro area"),
}

# World Bank uses its own aggregate codes, not this module's internal country
# codes — same shape as _OECD_REF_AREA_BY_COUNTRY_CODE and
# _IMF_ISO3_BY_COUNTRY_CODE below, which already translate for their own
# providers. "XC" confirmed live against
# api.worldbank.org/v2/country/XC/indicator/FP.CPI.TOTL.ZG (returns "Euro
# area"); EMU and EUU both error on that endpoint.
#
# Anything absent here passes its country_code through unchanged, so adding a
# country to _COUNTRY_ALIASES needs an entry here only when World Bank spells
# it differently.
_WORLD_BANK_COUNTRY_CODES: dict[str, str] = {"EURO_AREA": "XC"}


def _world_bank_intent(
    indicator_code: str, indicator_label: str, country_code: str, country_label: str,
) -> LiveDataIntent:
    """Single constructor for every World Bank intent in this module.

    Centralised because the country-code translation has to apply on all five
    paths that can reach World Bank (keyword match, semantic fallback's three
    branches, and the LLM-guess resolver). Building one of them inline is how
    an untranslated code reaches the API and 502s.
    """
    return LiveDataIntent(
        provider_key="world_bank",
        indicator_code=indicator_code,
        indicator_label=indicator_label,
        country_code=_WORLD_BANK_COUNTRY_CODES.get(country_code, country_code),
        country_label=country_label,
    )

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
    "EURO_AREA": [
        _CountryOverrideRule(
            keywords=("ecb deposit facility rate", "ecb deposit rate"), provider_key="ecb",
            indicator_code="FM:D.U2.EUR.4F.KR.DFR.LEV", indicator_label="ECB deposit facility rate",
            implies_country=True,
        ),
        _CountryOverrideRule(
            keywords=("ecb main refinancing rate", "ecb policy rate"), provider_key="ecb",
            indicator_code="FM:D.U2.EUR.4F.KR.MRR_FR.LEV", indicator_label="ECB main refinancing operations rate",
            implies_country=True,
        ),
    ],
}

# country_code -> label, derived from the alias table so it's never
# maintained as a second, separately-hardcoded mapping.
_COUNTRY_LABELS: dict[str, str] = dict(_COUNTRY_ALIASES.values())
_COUNTRY_LABELS["EURO_AREA"] = "Euro area"

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

_IMF_ISO3_BY_COUNTRY_CODE = {"GB": "GBR", "US": "USA", "IN": "IND"}
# Naming the IMF is what selects this provider; the concept words only pick
# the series. The original table required one of three exact phrases
# ("imf gdp growth forecast"), so every natural variation — "the IMF's
# inflation projection for India", "what does the IMF forecast for US
# growth" — silently missed and fell through to a different provider.
_IMF_MENTION = re.compile(r"\bimf\b")
_IMF_INDICATOR_KEYWORDS = (
    (("gdp growth", "real gdp", "economic growth", "growth forecast"), "NGDP_RPCH", "Real GDP growth (IMF WEO)"),
    (("inflation", "cpi", "consumer prices", "price growth"), "PCPIPCH", "Inflation rate (IMF WEO)"),
    (("unemployment", "jobless", "employment rate"), "LUR", "Unemployment rate (IMF WEO)"),
)
_VAT_NUMBER_PATTERN = re.compile(r"\b((?:AT|BE|BG|HR|CY|CZ|DE|DK|EE|EL|ES|FI|FR|GR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK)[A-Z0-9]{4,14})\b", re.IGNORECASE)
_EU_COUNTRY_LABELS = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia", "CY": "Cyprus",
    "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EE": "Estonia", "EL": "Greece",
    "ES": "Spain", "FI": "Finland", "FR": "France", "GR": "Greece", "HU": "Hungary",
    "IE": "Ireland", "IT": "Italy", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia",
    "MT": "Malta", "NL": "Netherlands", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
    "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia",
}


def _match_vies_intent(query: str) -> LiveDataIntent | None:
    lowered = query.lower()
    if not any(term in lowered for term in ("vat number", "vies", "vat id", "vat registration")):
        return None
    match = _VAT_NUMBER_PATTERN.search(query)
    if match is None:
        return None
    vat_number = match.group(1).upper()
    country_code = vat_number[:2]
    return LiveDataIntent(
        provider_key="vies", indicator_code="vat_validation", indicator_label="EU VAT number validation",
        country_code=country_code, country_label=_EU_COUNTRY_LABELS.get(country_code, country_code),
        company_query=vat_number, skip_document_search=True,
    )


def _match_regulations_gov_intent(query: str) -> LiveDataIntent | None:
    lowered = query.lower()
    explicit = "regulations.gov" in lowered
    rule_search = any(term in lowered for term in ("proposed rule", "final rule", "rulemaking docket", "comment period"))
    current_search = any(term in lowered for term in ("latest", "current", "search", "find", "show"))
    if not explicit and not (rule_search and current_search):
        return None
    return LiveDataIntent(
        provider_key="regulations_gov", indicator_code="document_search",
        indicator_label="Regulations.gov rulemaking search", country_code="US",
        country_label="United States", company_query=query,
    )


def _search_subject(query: str) -> str:
    quoted = re.search(r'["“]([^"”]{2,200})["”]', query)
    if quoted:
        return quoted.group(1).strip()
    for marker in (" about ", " concerning ", " for ", " on "):
        if marker in query.lower():
            return query[query.lower().rfind(marker) + len(marker):].strip(" ?.!")
    return query.strip()


def _match_phase2_intent(query: str) -> LiveDataIntent | None:
    lowered = query.lower()
    subject = _search_subject(query)
    if "eur-lex" in lowered or "cellar" in lowered or (
        any(term in lowered for term in ("eu legislation", "eu regulation", "eu directive"))
        and any(term in lowered for term in ("find", "search", "latest", "show"))
    ):
        return LiveDataIntent(provider_key="cellar", indicator_code="legal_search", indicator_label="EU legal metadata search",
                              country_code="EU", country_label="European Union", company_query=subject)
    if "legislation.gov.uk" in lowered or (
        any(term in lowered for term in ("uk legislation", "uk act", "uk statutory instrument"))
        and any(term in lowered for term in ("find", "search", "latest", "show"))
    ):
        return LiveDataIntent(provider_key="legislation_gov_uk", indicator_code="legal_search",
                              indicator_label="UK legislation search", country_code="GB",
                              country_label="United Kingdom", company_query=subject)
    if "ted api" in lowered or "ted.europa" in lowered or (
        any(term in lowered for term in ("eu tender", "eu procurement notice"))
        and any(term in lowered for term in ("find", "search", "latest", "show"))
    ):
        return LiveDataIntent(provider_key="ted", indicator_code="notice_search", indicator_label="TED procurement search",
                              country_code="EU", country_label="European Union", company_query=subject)
    if "sam.gov" in lowered or (
        any(term in lowered for term in ("us federal contract", "us contract opportunity"))
        and any(term in lowered for term in ("find", "search", "latest", "show"))
    ):
        return LiveDataIntent(provider_key="sam_gov", indicator_code="opportunity_search",
                              indicator_label="SAM.gov opportunity search", country_code="US",
                              country_label="United States", company_query=subject)
    return None


_SANCTIONS_PROVIDERS = (
    (("ofac", "sdn list"), "ofac", "US", "United States"),
    (("un sanctions", "un security council consolidated list"), "un_sanctions", "UN", "United Nations"),
    (("uk sanctions", "uk sanctions list"), "uk_sanctions", "GB", "United Kingdom"),
    (("eu sanctions", "eu consolidated financial sanctions"), "eu_sanctions", "EU", "European Union"),
)


def _screening_name(query: str) -> str | None:
    quoted = re.search(r'["“]([^"”]{2,200})["”]', query)
    if quoted:
        return quoted.group(1).strip()
    patterns = (
        r"\bscreen\s+(.+?)\s+against\b", r"\bcheck\s+(.+?)\s+against\b",
        r"\bis\s+(.+?)\s+(?:on|listed on)\b", r"\bsearch\s+(.+?)\s+(?:on|in)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1).strip(" ?.!")
    return None


# Identifiers a screening query may supply alongside a name. Anchored to an
# explicit label so an arbitrary alphanumeric token in a sentence is never
# screened as a passport number — a false identifier match is the most
# damaging result this path can produce, because an identifier hit is the one
# signal a reviewer treats as identifying rather than describing a party.
_SCREENING_IDENTIFIER_PATTERN = re.compile(
    r"\b(?:passport|national\s+id(?:entification)?(?:\s+number)?|id\s+number|"
    r"registration\s+(?:number|no\.?)|company\s+number|reg\.?\s*no\.?)"
    r"\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/\s]{3,20}[A-Z0-9])",
    re.IGNORECASE,
)


def _screening_identifiers(query: str) -> tuple[str, ...]:
    found = (match.group(1).strip() for match in _SCREENING_IDENTIFIER_PATTERN.finditer(query))
    return tuple(dict.fromkeys(value for value in found if value))


def _match_sanctions_intent(query: str) -> LiveDataIntent | None:
    lowered = query.lower()
    name = _screening_name(query)
    if not name:
        return None
    identifiers = _screening_identifiers(query)
    for aliases, provider, country_code, country_label in _SANCTIONS_PROVIDERS:
        if any(alias in lowered for alias in aliases):
            return LiveDataIntent(
                provider_key=provider,
                # Reflects what will actually be compared, so the audit
                # record does not claim a name-only screen when identifiers
                # were supplied.
                indicator_code="name_and_identifier_screening" if identifiers else "exact_name_screening",
                indicator_label="Official sanctions screening", country_code=country_code,
                country_label=country_label, company_query=name,
                screening_identifiers=identifiers,
            )
    return None


def _match_imf_indicator(country_code: str, lowered: str) -> LiveDataIntent | None:
    iso3 = _IMF_ISO3_BY_COUNTRY_CODE.get(country_code)
    if iso3 is None:
        # No verified IMF ISO3 mapping for this country. Deliberately not
        # derived from the alpha-2 code: the same discipline every connector
        # here follows — a country is added only once a real query has
        # confirmed the upstream actually holds data for it, rather than
        # constructing a plausible code and citing whatever comes back.
        return None
    if not _IMF_MENTION.search(lowered):
        return None
    for keywords, code, label in _IMF_INDICATOR_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return LiveDataIntent(provider_key="imf", indicator_code=f"{code}:{iso3}", indicator_label=label,
                                  country_code=country_code, country_label=_COUNTRY_LABELS[country_code])
    return None


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

# Semantic fallback for the trigger phrase only — same discipline as
# _semantic_indicator_match below: paraphrases like "how many dollars is
# 100 pounds worth" contain no literal trigger keyword ("to", "/",
# "exchange rate") and previously fell straight through to None. The
# currency-count check a few lines below (>= 2 aliases found) is what
# actually guards against false positives here, not this threshold alone —
# confirmed empirically: "What is the price of gold?" scores close to
# real FX queries on this exemplar set (0.53 vs 0.55-0.56) but mentions no
# currency at all, so it's rejected downstream regardless.
_FX_INTENT_EXEMPLARS = (
    "convert an amount from one currency to another",
    "how much is this amount worth in a different currency",
    "how many units of one currency equal this amount in another",
)
_fx_exemplar_embeddings: list[list[float]] = []


def _get_fx_exemplar_embeddings() -> list[list[float]]:
    global _fx_exemplar_embeddings
    if not _fx_exemplar_embeddings:
        _fx_exemplar_embeddings = [list(get_query_embedding_cached(ex)) for ex in _FX_INTENT_EXEMPLARS]
    return _fx_exemplar_embeddings


def _semantic_fx_trigger_match(query: str) -> bool:
    try:
        q_emb = get_query_embedding_cached(query)
        return max(cosine_similarity(q_emb, e) for e in _get_fx_exemplar_embeddings()) > 0.48
    except Exception:
        return False


def detect_fx_intent(query: str) -> LiveDataIntent | None:
    lowered = query.lower()
    has_trigger = any(trigger in lowered for trigger in _FX_TRIGGER_KEYWORDS)
    if not has_trigger and not _semantic_fx_trigger_match(query):
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


# Semantic fallback for the TRIGGER only (same discipline as the FX gate
# above) — verb-based phrasings like "what did Apple make last quarter" or
# "how much did Microsoft earn last year" contain none of
# _COMPANY_TRIGGER_KEYWORDS. This doesn't extract the name itself (the
# regex patterns above still own that, anchored to specific trailing
# keywords) — it only answers "does this look like a company financial
# inquiry at all," which is what the async LLM name-extraction fallback in
# live_sources/llm_fallback.py needs before it's worth a network call.
_COMPANY_LOOKUP_INTENT_EXEMPLARS = (
    "what did a company earn or make in a period",
    "how much profit or revenue did a company report",
    "tell me about a company's financial results",
)
_company_lookup_exemplar_embeddings: list[list[float]] = []


def _get_company_lookup_exemplar_embeddings() -> list[list[float]]:
    global _company_lookup_exemplar_embeddings
    if not _company_lookup_exemplar_embeddings:
        _company_lookup_exemplar_embeddings = [
            list(get_query_embedding_cached(ex)) for ex in _COMPANY_LOOKUP_INTENT_EXEMPLARS
        ]
    return _company_lookup_exemplar_embeddings


def _semantic_company_lookup_trigger_match(query: str) -> bool:
    try:
        q_emb = get_query_embedding_cached(query)
        return max(cosine_similarity(q_emb, e) for e in _get_company_lookup_exemplar_embeddings()) > 0.30
    except Exception:
        return False


def build_company_lookup_intent_from_name(
    company_name: str, jurisdiction: str, query: str = ""
) -> LiveDataIntent | None:
    """Shared by both the regex path below and the async LLM-extraction
    fallback (live_sources/service.py) — same provider-selection rule
    (US -> SEC EDGAR, GB -> Companies House, else -> GLEIF), so a name found
    either way resolves identically. Returns None on an unresolvable
    jurisdiction, same "don't substitute" discipline as the regex path.

    `query` is the full original question, used only for US financial-
    concept extraction ("revenue"/"net income"/"assets") — deliberately NOT
    company_name itself, which obviously never contains those words
    (a real regression caught by test_classifier_company_lookup_picks_
    provider_by_jurisdiction: searching "microsoft" for "revenue" always
    falls through to the Assets default, silently ignoring what the user
    actually asked for)."""
    jurisdiction_country = _country_from_jurisdiction(jurisdiction) if jurisdiction else None
    if jurisdiction_country is None:
        return None
    country_code, country_label = jurisdiction_country

    if country_code == "US":
        indicator_code, indicator_label = _extract_financial_concept((query or company_name).lower())
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


def detect_company_lookup_intent(query: str, jurisdiction: str = "") -> LiveDataIntent | None:
    lowered = query.lower()
    if not any(keyword in lowered for keyword in _COMPANY_TRIGGER_KEYWORDS):
        return None

    company_name = _extract_company_name(query)
    if company_name is None:
        return None

    return build_company_lookup_intent_from_name(company_name, jurisdiction, query=query)


def company_lookup_needs_llm_fallback(query: str, jurisdiction: str = "") -> bool:
    """True only when the regex path (trigger keyword + name pattern) found
    nothing, but the query semantically resembles a company financial
    inquiry AND the jurisdiction actually resolves — the async caller in
    live_sources/service.py uses this to decide whether an LLM call for
    name extraction is worth making at all, rather than firing one on every
    unrelated query that happens to mention a capitalized word."""
    if detect_company_lookup_intent(query, jurisdiction) is not None:
        return False  # regex path already succeeded, no fallback needed
    if not jurisdiction or _country_from_jurisdiction(jurisdiction) is None:
        return False  # can't resolve a provider even if the LLM finds a name
    lowered = query.lower()
    has_keyword_trigger = any(keyword in lowered for keyword in _COMPANY_TRIGGER_KEYWORDS)
    return has_keyword_trigger or _semantic_company_lookup_trigger_match(query)


def detect_live_data_intent(query: str, jurisdiction: str = "") -> LiveDataIntent | None:
    lowered = query.lower()

    vies_intent = _match_vies_intent(query)
    if vies_intent is not None:
        return vies_intent

    regulations_intent = _match_regulations_gov_intent(query)
    if regulations_intent is not None:
        return regulations_intent

    phase2_intent = _match_phase2_intent(query)
    if phase2_intent is not None:
        return phase2_intent

    sanctions_intent = _match_sanctions_intent(query)
    if sanctions_intent is not None:
        return sanctions_intent

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

    # Checked BEFORE the per-country overrides, unlike every other provider
    # here, because naming the IMF is an explicit choice of source and the
    # overrides match on bare concept words. With the old ordering, "What is
    # the IMF inflation forecast for the United Kingdom?" matched the GB
    # override's "inflation" keyword and returned the ONS CPIH index — a
    # different institution's different measure than the one asked for,
    # with nothing in the answer to say so. Every keyword on this path
    # requires a literal "imf" token, so it cannot capture a query that
    # did not name the IMF.
    imf_match = _match_imf_indicator(country_code, lowered)
    if imf_match is not None:
        return imf_match

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
        return _world_bank_intent(indicator_code, indicator_label, country_code, country_label)

    # Semantic fallback if keyword check did not match
    semantic_match = _semantic_indicator_match(query, country_code, country_label)
    if semantic_match is not None:
        return semantic_match

    return None


# ── Tier 2 (LLM reasoning fallback) + Tier 3 (validation) ────────────────────
#
# Generalizes the same shape already proven for company-name extraction
# (llm_fallback.py) to country+indicator resolution. Reached in two cases:
#   1. detect_live_data_intent() returned None outright (total miss).
#   2. It returned a real indicator match but the country silently
#      defaulted to _DEFAULT_COUNTRY ("WLD") — an indicator matched, but no
#      known country alias was found in the query text (e.g. "Britain"
#      before it was added to _COUNTRY_ALIASES above — confirmed live as a
#      real, reported case: "How many people are out of work in Britain
#      right now?" silently returned World Bank's global aggregate instead
#      of the UK's own figure).
#
# Tier 3 is the critical safety property: the LLM's own guess is NEVER
# routed to directly. Both fields get re-validated against the exact same
# closed tables Tier 0/1 already use — _resolve_country_free_text() only
# accepts a country already in _COUNTRY_ALIASES, and the indicator concept
# only ever supplies a representative keyword string that gets fed through
# _match_country_override()/_match_oecd_indicator()/the generic World Bank
# keyword table, the SAME functions and SAME substring-matching semantics
# Tier 0/1 already use. An invented country or an indicator Kriton has no
# connector for can never produce a fabricated provider_key/indicator_code
# this way — it just correctly falls through to None, same as any other
# unmatched case in this module.

# Representative keyword for each indicator concept the LLM may name —
# reused as the "lowered" text fed into the existing keyword-matching
# functions below, so a new concept never needs new routing code, only a
# new entry here (same registry discipline as _COUNTRY_PROVIDER_OVERRIDES).
_INDICATOR_CONCEPT_KEYWORDS: dict[str, str] = {
    "gdp": "gdp",
    "gdp_growth": "gdp growth",
    "inflation": "inflation",
    "unemployment": "unemployment",
    "bank_rate": "bank rate",
    "fed_funds_rate": "fed funds rate",
    "treasury_yield": "treasury yield",
    "corporate_tax_rate": "corporate tax rate",
}

# Reverse lookup from a World Bank indicator_code back to its concept, used
# only in case 2 above (existing_intent already has a real indicator; we
# only need to fix the country, not re-derive the indicator from scratch).
# Precise by indicator_code rather than re-parsing indicator_label text, so
# "GDP (current US$)" and "GDP growth (annual %)" — genuinely different
# concepts that both contain the substring "gdp" — never get confused.
_WORLD_BANK_CODE_TO_CONCEPT: dict[str, str] = {
    "NY.GDP.MKTP.KD.ZG": "gdp_growth",
    "NY.GDP.MKTP.CD": "gdp",
    "FP.CPI.TOTL.ZG": "inflation",
    "SL.UEM.TOTL.ZS": "unemployment",
}

# Soft gate for case 1 (total miss) only — cheap enough to check before
# spending a real LLM call, without needing a second embedding-similarity
# threshold to tune. Deliberately broader than any single indicator's own
# keywords (e.g. "economy"/"growing"/"shrinking" catch phrasings like "How
# is India's economy performing lately?" that name no indicator word at
# all) — false positives here just cost one wasted LLM call, not a wrong
# answer, since Tier 3 validation still gates what comes back.
_ECONOMIC_CUE_WORDS = (
    "gdp", "inflation", "unemployment", "economy", "economic", "growth",
    "growing", "shrinking", "recession", "cost of living", "jobless",
    "out of work", "interest rate", "tax rate", "yield", "employment",
)


def _resolve_country_free_text(country_guess: str | None) -> tuple[str, str] | None:
    """Tier 3 validation for the LLM's free-text country guess. Word-
    boundary substring match (not exact-equals) since the model may answer
    "the United Kingdom" rather than the bare alias — but every match still
    has to land on a literal entry in _COUNTRY_ALIASES, the same closed set
    everything else in this module resolves against."""
    if not country_guess:
        return None
    lowered = country_guess.lower()
    for alias, value in _COUNTRY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return value
    return None


def live_data_needs_llm_fallback(
    query: str, jurisdiction: str, existing_intent: LiveDataIntent | None
) -> bool:
    """Gate before spending a real LLM call — mirrors
    company_lookup_needs_llm_fallback()'s discipline of only firing when
    it's actually worth the round trip."""
    if existing_intent is not None:
        # Case 2: an indicator already matched — the only thing worth
        # asking the LLM to fix is a silently-defaulted country. Already a
        # strong positive signal on its own; no extra cue-word gate needed.
        return existing_intent.country_code == _DEFAULT_COUNTRY[0]

    # Case 1: total miss. An explicit jurisdiction that doesn't map to a
    # known country (UAE/IFRS/EU) must stay a hard None, never a query for
    # the LLM to try substituting a country into — same "don't substitute"
    # discipline detect_live_data_intent() already enforces for Tier 0/1.
    if jurisdiction and _country_from_jurisdiction(jurisdiction) is None:
        return False

    lowered = query.lower()
    return any(cue in lowered for cue in _ECONOMIC_CUE_WORDS)


def resolve_live_data_intent_from_llm_guess(
    llm_result: dict | None,
    jurisdiction: str,
    existing_intent: LiveDataIntent | None,
) -> LiveDataIntent | None:
    """Tier 3: validates the LLM's (country, indicator) guess against the
    same closed tables Tier 0/1 use, then routes through the exact same
    _match_country_override -> _match_oecd_indicator -> generic World Bank
    chain — never a new, separate routing path. Returns None (never worse
    than what Tier 0/1 already had) if either field can't be validated."""
    if llm_result is None:
        return None

    if jurisdiction:
        # An explicit jurisdiction still wins over the LLM's country guess,
        # same priority rule as Tier 0/1 — and an unmapped one (UAE/IFRS/EU)
        # was already filtered out by the gate above, so reaching here with
        # a set jurisdiction means it resolves.
        jurisdiction_country = _country_from_jurisdiction(jurisdiction)
        if jurisdiction_country is None:
            return None
        country_code, country_label = jurisdiction_country
    else:
        resolved_country = _resolve_country_free_text(llm_result.get("country"))
        if resolved_country is None:
            return None
        country_code, country_label = resolved_country

    if existing_intent is not None and existing_intent.provider_key == "world_bank":
        # Case 2: keep the indicator Tier 0/1 already correctly identified —
        # only the country was wrong — rather than trusting the LLM's own
        # indicator guess a second time for something that already matched.
        concept = _WORLD_BANK_CODE_TO_CONCEPT.get(existing_intent.indicator_code)
        keyword = _INDICATOR_CONCEPT_KEYWORDS.get(concept or "")
    else:
        keyword = _INDICATOR_CONCEPT_KEYWORDS.get(llm_result.get("indicator") or "")

    if keyword is None:
        return None

    override = _match_country_override(country_code, keyword)
    if override is not None:
        return override
    oecd_match = _match_oecd_indicator(country_code, keyword)
    if oecd_match is not None:
        return oecd_match
    generic = next(
        ((code, label) for kw, code, label in _INDICATOR_KEYWORDS if kw in keyword),
        None,
    )
    if generic is not None:
        code, label = generic
        return _world_bank_intent(code, label, country_code, country_label)
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
            return _world_bank_intent(
                "FP.CPI.TOTL.ZG", "Inflation, consumer prices (annual %)",
                country_code, country_label)
        if best_code == "A--T":
            return _world_bank_intent(
                "NY.GDP.MKTP.CD", "GDP (current US$)", country_code, country_label)
        if best_code == "UNEMPLOYMENT_RATE":
            return _world_bank_intent(
                "SL.UEM.TOTL.ZS", "Unemployment (% of total labor force)",
                country_code, country_label)
            
        return None
    except Exception:
        return None
