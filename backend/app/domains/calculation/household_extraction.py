"""
Query-parsing helpers for extracting a household's tax-relevant identity
facts (income, filing status, dependents, tax year, state) from raw query
text — feeds policyengine_engine.py's real PolicyEngine-US simulation with
real inputs instead of the LLM guessing numbers on its own.

Fail-closed by design: an income figure or filing status this module can't
confidently resolve is never guessed — a guessed household fact is a
fabricated household, exactly the failure mode this feature exists to
prevent (see reingest_policyengine_fixed.py's documented incident: a model
fabricated a plausible-but-wrong EITC figure from thin/empty context). This
mirrors the fail-closed contract app/domains/reference_data/service.py
already uses for match_work_state/extract_cfr_section: None means "do not
run the calculation," never "assume a default."

No policyengine_us import here — kept import-light so tests of parsing
logic run fast without pulling in numpy/pandas/the parameter tree (see
policyengine_engine.py, which isolates that heavy import instead).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domains.reference_data.service import match_work_state


@dataclass(frozen=True)
class HouseholdParams:
    annual_income: float
    # PolicyEngine FilingStatus enum name: SINGLE / JOINT / SEPARATE /
    # HEAD_OF_HOUSEHOLD / SURVIVING_SPOUSE (verified against the installed
    # policyengine_us v1.775.8 package's filing_status variable).
    filing_status: str
    num_dependents: int
    tax_year: int
    # None means "no state named" — policyengine_engine.py treats this as a
    # federal-only calculation, never a guessed state.
    state_code: str | None


_DOLLAR_PATTERN = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
_INCOME_KEYWORD_NUMBER_PATTERN = re.compile(
    r"(?:income|earning|earned|salary|wages|made|makes|earns)\D{0,15}?(\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)


def extract_annual_income(query: str) -> float | None:
    """Returns an annual income figure only when the query states exactly
    one unambiguously: an explicit '$' figure, or a number anchored
    immediately to an income-keyword phrase. Returns None otherwise — no
    default, since a bare number in a tax query is just as plausibly a CFR
    section, a tax year, or a dependent count, and guessing which would
    fabricate the household.

    Returns None when more than one *distinct* dollar figure appears in the
    query, rather than silently picking the first one — a compound query
    ("I earn $45,000... what's my tax on $60,000...") is exactly the kind
    of ambiguity this module exists to refuse, not guess through. A
    real incident (verified 2026-07-20): a two-question query picked the
    first figure and silently ran the second question's calculation
    against the wrong income, and the LLM then discarded the (correct, for
    the wrong figure) computed result and hallucinated its own number
    instead — worse than not calculating at all."""
    dollar_matches = _DOLLAR_PATTERN.findall(query)
    distinct_dollar_values = {m.replace(",", "") for m in dollar_matches}
    if len(distinct_dollar_values) > 1:
        return None
    if dollar_matches:
        return float(dollar_matches[0].replace(",", ""))

    keyword_matches = _INCOME_KEYWORD_NUMBER_PATTERN.findall(query)
    distinct_keyword_values = {m.replace(",", "") for m in keyword_matches}
    if len(distinct_keyword_values) > 1:
        return None
    if keyword_matches:
        return float(keyword_matches[0].replace(",", ""))

    return None


# Order matters: "married filing jointly"/"married filing separately" must
# be checked before any bare "married" would be — there is deliberately no
# bare "married" entry, since "married" alone is ambiguous between
# Joint/Separate and guessing between them would misstate the household.
_FILING_STATUS_KEYWORDS: dict[str, str] = {
    "married filing jointly": "JOINT",
    "mfj": "JOINT",
    "married filing separately": "SEPARATE",
    "mfs": "SEPARATE",
    "head of household": "HEAD_OF_HOUSEHOLD",
    "hoh": "HEAD_OF_HOUSEHOLD",
    "qualifying surviving spouse": "SURVIVING_SPOUSE",
    "qualifying widow": "SURVIVING_SPOUSE",
    "surviving spouse": "SURVIVING_SPOUSE",
    "single filer": "SINGLE",
    "single": "SINGLE",
}


def extract_filing_status(query: str) -> str | None:
    """Returns a PolicyEngine FilingStatus enum name, or None if the query
    doesn't name exactly one unambiguously. No default: filing status
    changes every bracket and every credit's phase-out — unlike
    extract_tax_year's current-year fallback, there is no "ordinary
    reading" to fall back to.

    Collects every *distinct* status named, not just the first dict-order
    match — a compound query naming two different statuses ("Single vs
    Head of Household...") would otherwise silently resolve to whichever
    status happens to be checked first in _FILING_STATUS_KEYWORDS'
    iteration order, regardless of which one the query actually leads
    with. Real incident (2026-07-20): a two-scenario comparison query
    ("$70,000... Single vs Head of Household... no dependents for the
    single case and 1 dependent for HoH") silently resolved to a
    conflated household matching neither described scenario. Multiple
    keyword phrasings of the *same* status ("single filer" + "single")
    are deduplicated and don't count as ambiguity."""
    lowered = query.lower()
    matched_statuses = {status for keyword, status in _FILING_STATUS_KEYWORDS.items() if keyword in lowered}
    if len(matched_statuses) == 1:
        return matched_statuses.pop()
    return None


_ZERO_DEPENDENT_PATTERN = re.compile(r"\bno\s+(?:kids?|children|dependents?)\b", re.IGNORECASE)
# "(?:qualifying\s+)?" — real incident (2026-07-20): "3 qualifying children"
# didn't match at all (extract_num_dependents returned None for an otherwise
# perfectly legitimate, non-ambiguous single-household query) because
# "qualifying" sat between the number and the noun. "Qualifying child" is
# the literal IRS term of art for EITC/CTC dependents, not rare phrasing —
# handled specifically rather than a generic wildcard, to avoid loosening
# this into matching unrelated words between the number and the noun.
_EXPLICIT_DEPENDENT_COUNT_PATTERN = re.compile(r"\b(\d+)\s+(?:qualifying\s+)?(?:kids?|children|dependents?)\b", re.IGNORECASE)
_WORD_TO_NUMBER = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_WORD_DEPENDENT_COUNT_PATTERN = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:qualifying\s+)?(?:kids?|children|dependents?)\b",
    re.IGNORECASE,
)
_UNRESOLVED_DEPENDENT_MENTION_PATTERN = re.compile(r"\b(?:kids?|children|dependents?)\b", re.IGNORECASE)


def extract_num_dependents(query: str) -> int | None:
    """Returns an explicit dependent count when the query states one ("2
    kids", "no children", "three dependents"). Returns None (fail closed —
    an unresolved count, not a guessed one) when the query raises the topic
    of dependents at all without a resolvable count ("with kids", a bare
    "dependents"), since a guessed count materially changes CTC/EITC.
    Returns 0 only when the query never mentions dependents at all — the
    same safe-default reasoning extract_pay_date already uses elsewhere in
    this codebase for an unstated-but-inferable fact: the ordinary reading
    of a standard-deduction or generic-EITC question that never raises
    dependents is zero, not an unknown. This is the one asymmetric default
    in this module — every other extractor here is uniformly fail-closed
    or uniformly safe-default, not a mix.

    Collects every *distinct* count signaled by the query rather than
    returning on the first pattern that matches — a compound query can
    contain both a zero-signal ("no dependents") and an explicit count
    ("1 dependent") describing two different scenarios, and previously the
    zero-check ran first and silently won regardless. Real incident
    (2026-07-20): "no dependents for the single case and 1 dependent for
    HoH" resolved to 0, discarding the "1 dependent" half entirely. Two or
    more distinct counts signaled -> None (ambiguous), not a guess at
    which one was meant."""
    resolved_counts: set[int] = set()
    if _ZERO_DEPENDENT_PATTERN.search(query):
        resolved_counts.add(0)

    explicit = _EXPLICIT_DEPENDENT_COUNT_PATTERN.search(query)
    if explicit:
        resolved_counts.add(int(explicit.group(1)))

    worded = _WORD_DEPENDENT_COUNT_PATTERN.search(query)
    if worded:
        resolved_counts.add(_WORD_TO_NUMBER[worded.group(1).lower()])

    if len(resolved_counts) > 1:
        return None
    if resolved_counts:
        return resolved_counts.pop()

    if _UNRESOLVED_DEPENDENT_MENTION_PATTERN.search(query):
        return None

    return 0


_TAX_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
# PolicyEngine-US's parameter tree covers a wide but not unlimited range —
# this bounds accidental matches (e.g. a CFR section or document number
# that happens to contain a 20xx-shaped substring) to a plausible tax-year
# window rather than accepting any 4-digit 20xx number found anywhere.
_MIN_SUPPORTED_TAX_YEAR = 2021
_MAX_SUPPORTED_TAX_YEAR = 2035


def extract_tax_year(query: str) -> int:
    """Returns an explicit 4-digit year named in the query if it falls in a
    plausible supported range, else the current calendar year. Not
    fail-closed by design (unlike income/filing-status/dependents): an
    absent year isn't an unknown fact about the household, just an
    unstated-but-inferable time reference — same posture as
    reference_data/service.py's extract_pay_date."""
    for match in _TAX_YEAR_PATTERN.finditer(query):
        year = int(match.group(1))
        if _MIN_SUPPORTED_TAX_YEAR <= year <= _MAX_SUPPORTED_TAX_YEAR:
            return year
    return datetime.now(timezone.utc).year


def match_state_for_calculation(query: str) -> str | None:
    """Thin re-export of reference_data.service.match_work_state — reused
    rather than maintaining a third 51-entry state-name map (Census's
    match_state_fips is the second, FIPS-keyed variant of the same map)."""
    return match_work_state(query)


def extract_household_params(query: str) -> HouseholdParams | None:
    """The single gate app/orchestration/service.py calls. Returns None
    unless annual_income AND filing_status both resolve, and dependents
    aren't in the ambiguous unresolved state — those are the facts with no
    honest default. Tax year always resolves (to a default); state may
    resolve to None, meaning "federal-only calculation" (see
    policyengine_engine.py's state-handling note), which is a legitimate
    outcome, not a failure."""
    income = extract_annual_income(query)
    if income is None:
        return None

    filing_status = extract_filing_status(query)
    if filing_status is None:
        return None

    num_dependents = extract_num_dependents(query)
    if num_dependents is None:
        return None

    return HouseholdParams(
        annual_income=income,
        filing_status=filing_status,
        num_dependents=num_dependents,
        tax_year=extract_tax_year(query),
        state_code=match_state_for_calculation(query),
    )
