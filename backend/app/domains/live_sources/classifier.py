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


def _match_country_in_text(lowered: str) -> tuple[str, str]:
    return next(
        (value for alias, value in _COUNTRY_ALIASES.items() if alias in lowered),
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
    )


def _match_implied_country_rule(lowered: str) -> LiveDataIntent | None:
    """Only called when jurisdiction is genuinely unset — rules with
    implies_country=True may resolve a country from query text alone
    (e.g. "Bank Rate" -> UK)."""
    for country_code, rules in _COUNTRY_PROVIDER_OVERRIDES.items():
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
    re.compile(r"((?:[A-Z][\w.&-]*\s*)+)'s\s+(?i:filings?|financials?|revenue|assets|net income)"),
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
    return None


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
    # fall through to World Bank below, same for every country.

    indicator = next(
        ((code, label) for keyword, code, label in _INDICATOR_KEYWORDS if keyword in lowered),
        None,
    )
    if indicator is None:
        return None

    indicator_code, indicator_label = indicator
    return LiveDataIntent(
        provider_key="world_bank",
        indicator_code=indicator_code,
        indicator_label=indicator_label,
        country_code=country_code,
        country_label=country_label,
    )
