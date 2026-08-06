"""
Massarius™ retrieval and evidence subsystem — Checkpoint C, output exposure
gate (ZL-ENG-02 §10 / Release Gate RG-03, ZL-ENG-03 §5.7).

Supersedes app/orchestration/composition_validator.py, which covers only 3 of
the checks below (grounding, citation binding, prohibited-claim scan) —
those three are reused here rather than reimplemented, since they already
work correctly. This module adds authority ceiling, confidence support,
disclaimer presence, and licence exposure — the last of which
composition_validator.py could never have implemented, since
source_display_states didn't exist until this Phase 1 work. Checks 11-12
(summarize-don't-copy, tutor-depth structure) were added 2026-07-22 as the
governance backstop for the product vision doc's items 5-6 — see memory
product-vision-kriton-tutor-not-search.

The spec wants a raised ValidationFailed on failure; the live orchestration
pipeline (orchestration/service.py) is built around a return-value pattern
(check `.passed`, read `.failures`, branch on `.degraded_route`) at every
other control point, not exceptions. validate_answer() below is the
call-site-friendly function: it runs the checks and returns a ValidationResult,
converting internally from ValidationFailed. validate_answer_or_raise() is
the literal, spec-shaped function for direct/unit-test use — it's what
validate_answer() calls internally.

Must NOT: compose answers, decide routing, or build the SourceBundle — only
gate what's already been composed against what's already been built.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.domains.calculation.provenance import ProvenanceStore
from app.domains.massarius.errors import ValidationFailed
from app.orchestration.schemas import SourceBundle, ValidationResult

# ── 1. Prohibited professional claim patterns (reused from composition_validator.py) ──
# 2026-07-22 real incident: "Compare a qualified opinion vs an unqualified
# audit opinion" was refused end-to-end. Both patterns below were too broad:
# #2's "the company('s)?" branch matched any generic illustrative example
# ("the company's audit opinion is clean") right along with genuine
# second-person claims about the reader's own entity, and #4's leading
# "(this is )?" group was optional, so it matched the bare term "audit
# opinion" appearing ANYWHERE — including a purely educational sentence
# explaining what an audit opinion is, a core accounting concept Kriton
# must be able to discuss. Narrowed #2 to "your" only (an illustrative
# "the company" is not a claim about the reader's own situation) and made
# #4's "this is" prefix mandatory (only a genuine "this is my audit
# opinion"-shaped claim should trip it, not the bare term).
_PROHIBITED_PATTERNS = [
    r"you\s+(should|must|need\s+to)\s+(file|register|pay|submit|declare)",
    r"\byour\s+(tax\s+(liability|return)|audit\s+opinion)\b",
    r"i\s+(confirm|certify|guarantee|assure)\s+(that\s+)?",
    r"this\s+is\s+(?:my\s+|our\s+)?(legal|tax|audit|financial)\s+(advice|opinion|certification)",
    r"as\s+your\s+(accountant|auditor|tax\s+advisor|legal\s+counsel)",
    r"(sign|signature|signed)\s+(off|on)\s+(by|as)",
]
_PROHIBITED = [re.compile(p, re.IGNORECASE) for p in _PROHIBITED_PATTERNS]

# ── 4. Authority ceiling — absolute-authority language a non-primary source can't back ──
_AUTHORITY_OVERREACH_PATTERNS = [
    r"the\s+definitive\s+(answer|rule|treatment)",
    r"this\s+is\s+the\s+only\s+correct\s+(answer|treatment|interpretation)",
    r"authoritative\s+ruling",
    r"binding\s+(interpretation|precedent)",
]
_AUTHORITY_OVERREACH = [re.compile(p, re.IGNORECASE) for p in _AUTHORITY_OVERREACH_PATTERNS]

# ── 5. Confidence support — unhedged certainty language ──
_UNHEDGED_CERTAINTY_PATTERNS = [
    r"\bdefinitely\b", r"\balways\b", r"\bguaranteed?\b", r"\bnever\s+wrong\b",
    r"\bwithout\s+(a\s+)?doubt\b", r"\b100%\s+certain\b",
]
_UNHEDGED_CERTAINTY = [re.compile(p, re.IGNORECASE) for p in _UNHEDGED_CERTAINTY_PATTERNS]

_CONFIDENCE_STATES_REQUIRING_HEDGING = {"limited", "insufficient", "conflicting_sources", "stale_sources"}

_REF_PATTERN = re.compile(r"\[REF-(\d+)\]")

# ── 2. Citation binding — the real valid-REF range, derived from what was
# actually shown to the model. app/domains/rag/context_fit.py::build_grounded_context
# numbers [REF-N] by CHUNK position (1..len(reranked_chunks), up to the
# reranker's top_n=5) — NOT by distinct governed Source count. A single
# large document (e.g. GAAS) routinely gets split into multiple embedded
# chunks at ingestion, several of which can each make the top-5 rerank cut,
# so eligible_source_count (2, say) can be smaller than the number of real
# REF anchors actually in the prompt (up to 5). Real incident (2026-07-20):
# every GAAS-grounded HIGH-risk answer in a test batch failed this check —
# not because the model hallucinated anything, but because it correctly
# cited REF-3/4/5 (real, shown chunks) while the check only accepted
# REF-1/REF-2 (eligible_source_count's coarser number). Parsed straight
# from grounding_context's own "[REF-N] Source: ..." headers (the exact
# format build_grounded_context emits) rather than trusting a proxy count.
_GROUNDED_REF_HEADER_PATTERN = re.compile(r"^\[REF-(\d+)\]\s+Source:", re.MULTILINE)

# ── 6. Disclaimer presence marker — matches the text
# orchestration/composition_validator.py's build_validated_disclaimer appends ──
_DISCLAIMER_MARKER = "Kriton™ Disclaimer"

# ── 8. Numeric fidelity — a $/% figure claimed in the answer must appear
# somewhere in the actual grounding context sent to the model. Citation
# binding (#2) only checks that [REF-N] points to a real, eligible source —
# it says nothing about whether the specific number attached to that
# citation is real. A model can cite a genuine source and still invent a
# number nowhere in that source's text (a real incident this caught in
# testing: a "$56,844" EITC figure was fabricated for a field whose
# retrieved chunk contained only a name and description, no value at all).
_CLAIMED_FIGURE_PATTERN = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?%")
_CLAIMED_DATE_PATTERN = re.compile(
    r"\b(?:by|on|before|after|deadline(?:\s+is)?|due(?:\s+on)?)\s+"
    r"(?:the\s+)?(?:\d{1,2}(?:st|nd|rd|th)|"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?)\b",
    re.IGNORECASE,
)
_NUMERIC_TOKEN_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _normalize_digits(s: str) -> str:
    return re.sub(r"[^\d.]", "", s)


def _extract_normalized_numbers(text: str) -> set[str]:
    return {_normalize_digits(t) for t in _NUMERIC_TOKEN_PATTERN.findall(text)}


def _claim_matches_provenance(normalized: str, provenance: ProvenanceStore) -> bool:
    """True when a claimed figure's value matches any verified calculation
    record — Decimal equality, not string equality, so trailing-zero/scale
    differences (a formula's "70000.00" vs a claim written "70000") don't
    cause a false mismatch. Deliberately exact-value matching only (no
    percent/fraction reformatting the way the grounding_context check
    above allows) — every engine's output is already stored in its
    declared display unit, so a genuine match is always exact."""
    try:
        claimed_value = Decimal(normalized)
    except InvalidOperation:
        return False
    return bool(provenance.find_by_value(claimed_value))


# Real gap (2026-08-03): a query that supplies a complete itemized dataset
# inline ("Rent 3000, Payroll 8000, Marketing 1500...") routinely gets a
# composed answer with a "Displayed total: $X" and/or "representing Y% of
# the total" line — the composition prompt asks for exactly this shape (see
# orchestration/service.py's "Executive summary"/"Key insight" guidance).
# Both figures are simple arithmetic on numbers the user already supplied,
# not an invented claim, but neither the literal total nor the literal
# percentage string appears anywhere in query_text itself, so they used to
# fail checkpoint 8 whenever grounding_context happened to be non-empty
# (queries that retrieved zero sources skipped checkpoint 8 entirely,
# which is why the SAME kind of question sometimes passed and sometimes
# didn't — not a random failure, just inconsistent gating). This widens
# "supported" the same conservative way query_text and provenance already
# do: only a straightforward sum of every number literally in the query,
# and each item's percentage share of that sum — never an invented figure.
def _derived_total_and_shares(query_numbers: set[str]) -> tuple[Optional[Decimal], set[str]]:
    decimals: list[Decimal] = []
    for token in query_numbers:
        try:
            decimals.append(Decimal(token))
        except InvalidOperation:
            continue
    if not decimals:
        return None, set()
    total = sum(decimals)
    if total <= 0:
        return total, set()
    shares: set[str] = set()
    for value in decimals:
        share = value / total * 100
        # Covers both the 1-decimal ("28.1%") and whole-number ("28%")
        # renderings the composition prompt's summary lines actually use.
        shares.add(f"{share:.1f}")
        shares.add(f"{share:.0f}")
    return total, shares


# Real gap (2026-08-06): "Analyze these monthly expenses and identify the
# largest change: January $80,000, February $92,000, March $87,000 and
# April $105,000." — the deterministic composition (see user_provided_
# data.py's "Key insight" line) correctly computed the largest period-to-
# period CHANGE as $18,000 (April $105,000 minus March $87,000), both of
# which the user supplied directly. But _derived_total_and_shares above
# only recognizes a SUM of every number and each one's percentage SHARE of
# that sum — a pairwise DIFFERENCE between two supplied numbers isn't
# either of those, so a perfectly correct, query-derived figure was
# rejected as "unsupported" and the whole answer degraded to a needless
# clarification. Same conservative posture as the total/shares check: only
# the absolute difference between two numbers literally in the query,
# never an invented figure.
def _derived_differences(query_numbers: set[str]) -> set[str]:
    decimals: list[Decimal] = []
    for token in query_numbers:
        try:
            decimals.append(Decimal(token))
        except InvalidOperation:
            continue
    diffs: set[str] = set()
    for i, a in enumerate(decimals):
        for b in decimals[i + 1:]:
            diffs.add(str(abs(a - b)))
    return diffs


def _claim_is_supported(
    claim_text: str,
    *,
    context_numbers: set[str],
    query_numbers: set[str],
    provenance: Optional[ProvenanceStore],
    derived_total: Optional[Decimal] = None,
    derived_shares: Optional[set[str]] = None,
    derived_differences: Optional[set[str]] = None,
) -> bool:
    normalized = _normalize_digits(claim_text)
    if not normalized or normalized in context_numbers or normalized in query_numbers:
        return True
    # Real gap (2026-08-06): a date claim like "on August 4" normalizes to
    # bare "4", but an ISO-format date in the grounding context ("2026-08-
    # 04") normalizes its own day component to zero-padded "04" — the same
    # calendar day, but a different STRING, so the plain membership check
    # above missed it and a genuinely-grounded FRED date composition failed
    # numeric fidelity every time. Falls back to integer-value equality
    # only when the claim is a plain (non-decimal) integer, which a date's
    # day/month component always is — a genuine currency/measurement
    # mismatch is never rescued by this, since _normalize_digits keeps the
    # decimal point for those ("4" vs "4.50" still correctly fails).
    if normalized.isdigit():
        claim_int = int(normalized)
        if any(token.isdigit() and int(token) == claim_int for token in context_numbers | query_numbers):
            return True
    if derived_differences and normalized in derived_differences:
        return True
    if claim_text.strip().endswith("%"):
        try:
            as_fraction = f"{float(normalized) / 100:g}"
        except ValueError:
            as_fraction = None
        if as_fraction in context_numbers:
            return True
        if derived_shares and normalized in derived_shares:
            return True
    elif derived_total is not None:
        try:
            if Decimal(normalized) == derived_total:
                return True
        except InvalidOperation:
            pass
    return bool(provenance and _claim_matches_provenance(normalized, provenance))


def generalize_unsupported_numeric_claims(
    answer_text: str,
    *,
    grounding_context: str,
    query_text: str = "",
    provenance: Optional[ProvenanceStore] = None,
) -> str:
    """Replace invented illustrative $/% figures with non-numeric wording.

    Used only for non-numeric user requests before Checkpoint C. It preserves
    all prose and citations while removing values that are absent from the
    sources, user query, and governed calculation records. The repaired answer
    still passes the complete validator afterward.
    """
    if not grounding_context:
        return answer_text
    context_numbers = _extract_normalized_numbers(grounding_context)
    query_numbers = _extract_normalized_numbers(query_text) if query_text else set()
    derived_total, derived_shares = _derived_total_and_shares(query_numbers)
    derived_differences = _derived_differences(query_numbers)

    def is_supported(match: re.Match) -> bool:
        return _claim_is_supported(
            match.group(),
            context_numbers=context_numbers,
            query_numbers=query_numbers,
            provenance=provenance,
            derived_total=derived_total,
            derived_shares=derived_shares,
            derived_differences=derived_differences,
        )

    # A worked example with invented values is no longer useful once those
    # values are generalized. Remove the whole optional example section and
    # preserve the supported procedure around it.
    lines = answer_text.splitlines()
    repaired_lines: list[str] = []
    index = 0
    example_heading = re.compile(r"^\s*(?:#{1,6}\s+example\b|\*\*example\*\*\s*:?)", re.I)
    next_heading = re.compile(r"^\s*(?:#{1,6}\s+\S|\*\*[^*]+\*\*\s*:?)")
    while index < len(lines):
        if example_heading.match(lines[index]):
            end = index + 1
            while end < len(lines) and not next_heading.match(lines[end]):
                end += 1
            section = "\n".join(lines[index:end])
            if any(not is_supported(match) for match in _CLAIMED_FIGURE_PATTERN.finditer(section)):
                index = end
                continue
        repaired_lines.append(lines[index])
        index += 1
    answer_text = "\n".join(repaired_lines)

    def replace(match: re.Match) -> str:
        claim = match.group()
        if is_supported(match):
            return claim
        return "the applicable rate" if claim.strip().endswith("%") else "the applicable amount"

    return _CLAIMED_FIGURE_PATTERN.sub(replace, answer_text)


# ── 9. Repetition / degenerate output — the model gets stuck reasoning in
# circles instead of concluding. Real incident (2026-07-20): asked for a
# credit the calculation engine doesn't compute (CDCC — no care-expenses
# input exists to feed it), the model was left with only fact-path
# descriptions (no values) and produced the same ~60-word paragraph
# ("Since we do not have information about the Adjusted Care Benefits
# Amount, we will assume...") 7 times verbatim before being cut off
# mid-word by max_tokens. None of checks 1-8 catch this: the answer never
# asserts a false claim, a bad citation, or a fabricated number — it simply
# never converges. This is exactly the failure groq_adapter.py's
# frequency_penalty=0.7 comment says it's meant to prevent; 0.7 evidently
# isn't sufficient for every case, so this is the necessary backstop that
# actually blocks a degenerate answer from reaching a user, regardless of
# which future under-supported topic triggers it next.
_MIN_REPEATED_SENTENCE_LENGTH = 40
_MIN_REPETITION_COUNT = 3
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")

_MISSING_REQUESTED_FACT_PATTERNS = [
    re.compile(r"\b(?:context|sources?)\s+(?:does|do)\s+not\s+provide\s+(?:the\s+)?(?:exact|requested|specific)", re.IGNORECASE),
    re.compile(r"\b(?:provided\s+)?context\s+does\s+not\s+contain\s+(?:any\s+)?information\s+about\b", re.IGNORECASE),
    re.compile(r"\bno\s+(?:relevant|responsive)\s+(?:information|document|source)\s+(?:was|is)\s+(?:found|available|provided)\b", re.IGNORECASE),
    re.compile(r"\brequested\s+(?:amount|figure|fact|information)\s+is\s+not\s+(?:available|provided|present)", re.IGNORECASE),
    re.compile(r"\bno\s+(?:exact|specific)\s+(?:amount|figure|information)\s+(?:is|was)\s+provided", re.IGNORECASE),
]

# ── 11. Summarize, don't copy — 2026-07-22 product vision doc item 5. The
# composition prompt (orchestration/service.py's grounded_input) already
# instructs the model to compress sources into its own words rather than
# transcribe them; this is the governance backstop verifying it actually
# did, the same relationship check 3 (prohibited-claim scan) has to the
# "never give personal advice" prompt instruction. 2026-07-23 real
# incident: a single live-testing batch escalated 4 separate ordinary
# educational answers to a persisted HUMAN_REVIEW case off this check and
# check 12 combined — exactly the human-review-at-scale pattern the vision
# doc's item 3 says to move away from, for queries that weren't even
# advice-signal. Raised from 20 to 35 words: dense-but-legitimate technical
# phrasing (GAAS/IRS language that a correct paraphrase would still
# resemble closely) can share a 20-word run by chance far more often than
# it can share 35; a real block-copied paragraph still trivially clears 35.
_MIN_VERBATIM_RUN_WORDS = 35
_WORD_PATTERN = re.compile(r"\S+")


def _has_verbatim_copy(answer_text: str, grounding_context: str) -> bool:
    if not grounding_context:
        return False
    answer_words = _WORD_PATTERN.findall(answer_text.lower())
    context_words = _WORD_PATTERN.findall(grounding_context.lower())
    if len(answer_words) < _MIN_VERBATIM_RUN_WORDS or len(context_words) < _MIN_VERBATIM_RUN_WORDS:
        return False
    context_ngrams = {
        tuple(context_words[i:i + _MIN_VERBATIM_RUN_WORDS])
        for i in range(len(context_words) - _MIN_VERBATIM_RUN_WORDS + 1)
    }
    return any(
        tuple(answer_words[i:i + _MIN_VERBATIM_RUN_WORDS]) in context_ngrams
        for i in range(len(answer_words) - _MIN_VERBATIM_RUN_WORDS + 1)
    )


# ── 12. Tutor-depth structure — 2026-07-22 product vision doc item 6. Only
# engaged for queries shaped like a genuine "teach me about X" concept
# request (same trigger-verb shape as prescreen.py's domain-restriction
# gate, deliberately not anchored to a fixed subject list this time) — a
# narrow factual/numeric lookup ("What is the standard deduction amount?")
# is explicitly exempted by the composition prompt itself and must not be
# forced into this fuller structure. Heuristic, not exhaustive: flags an
# answer that is both short AND missing any explanatory ("why"/"purpose")
# or illustrative ("for example") signal — the two structural elements a
# bare one-line definition lacks that a tutor-style explanation has.
_CONCEPT_QUESTION_PATTERN = re.compile(
    r"^\s*(?:explain|what\s+is|what\s+are|tell\s+me\s+about|describe|"
    r"teach\s+me\s+(?:about\s+)?|help\s+me\s+(?:learn|understand)|"
    r"why\s+(?:is|are|does|do)|how\s+does)\b",
    re.IGNORECASE,
)
# 2026-07-22 real incident: "What are the VAT rates in the UAE vs India?"
# matched the leading "what are" trigger above and was long enough (two
# jurisdictions) to engage the check, then failed for lacking a why/example
# signal a rate lookup was never going to have — "what is/are" is ambiguous
# between a genuine concept question ("What is double-entry bookkeeping?")
# and a specific-value lookup or comparison ("What is the VAT rate in the
# UAE?", "What are the standard deduction amounts for 2025 vs 2026?"). This
# overrides the leading-trigger match when the query names the kind of
# concrete attribute being looked up, regardless of phrasing — the leading
# verb alone isn't a reliable enough signal of intent.
# Real gap (2026-08-06): "What is US GDP?" got wrongly held to full
# tutor-depth structure (what/why/rule/example) — a plain factual number
# lookup, not a concept to teach — because "GDP" names no word in this
# override list the way "What is the [X] RATE" already does for inflation/
# interest-rate questions. Same fix shape as the 2026-07-23 incident noted
# below, just a different missing noun.
_FACTUAL_LOOKUP_OVERRIDE_PATTERN = re.compile(
    r"\b(rate|rates|amount|amounts|percentage|percent|threshold|thresholds|"
    r"limit|limits|cap|caps|deduction|deductions|credit|credits|exemption|"
    r"exemptions|price|prices|cost|costs|fee|fees|number|value|values|date|"
    r"dates|deadline|deadlines|mistake|mistakes|checklist|checklists|"
    r"gdp|gross\s+domestic\s+product)\b",
    re.IGNORECASE,
)
# 2026-07-23 real incident: "What is $500 minus $200?" also matched the
# "what is" trigger and, lacking any word from the override pattern above
# (it's not a rate/amount/deduction/etc. lookup — it's bare arithmetic),
# still engaged the check and failed for having no why/example structure a
# two-term subtraction was never going to have. A query that is itself a
# plain arithmetic expression (two figures joined by a math operator word
# or symbol) is a calculation question, not a concept-explanation one,
# regardless of starting with "what is."
_ARITHMETIC_QUESTION_PATTERN = re.compile(
    r"[\d.]\s*(?:%|percent)?\s*(?:\+|-|x|\*|/|plus|minus|times|multiplied\s+by|"
    r"divided\s+by|of)\s*\$?[\d.]",
    re.IGNORECASE,
)
_EXPLANATORY_SIGNAL_PATTERN = re.compile(
    r"\b(because|the\s+purpose|the\s+reason|is\s+used\s+to|exists\s+to|"
    r"in\s+order\s+to|why\s+it\s+matters|why\s+it\s+is\s+used)\b",
    re.IGNORECASE,
)
_ILLUSTRATIVE_SIGNAL_PATTERN = re.compile(
    r"\b(for\s+example|for\s+instance|such\s+as|e\.g\.|imagine|suppose|consider\s+a)\b",
    re.IGNORECASE,
)
# 2026-07-23: lowered 60 -> 40 and require only ONE of (why-signal,
# example-signal) rather than both — same real incident as check 11 above.
# "Explain the purpose of an audit trail." was escalated with only 3
# eligible sources: sparse retrieval legitimately can't support a full
# what/why/example answer, and forcing that structure regardless of source
# depth punished an honestly concise, accurate answer the same as a lazy
# one. A genuine tutor-depth answer still clears 40 words with at least one
# structural signal; this only stops blocking the answers that couldn't
# have had more without inventing content the context didn't support.
_MIN_CONCEPT_ANSWER_WORDS = 40
# Below this, an answer is more likely a short admission/refusal fragment
# than a genuine (if underdeveloped) concept explanation — not what this
# check is meant to catch.
_MIN_WORDS_TO_ENGAGE_CONCEPT_CHECK = 15


def _has_degenerate_repetition(text: str) -> bool:
    sentences = [s.strip().lower() for s in _SENTENCE_SPLIT_PATTERN.split(text) if s.strip()]
    substantive = [s for s in sentences if len(s) >= _MIN_REPEATED_SENTENCE_LENGTH]
    counts: dict[str, int] = {}
    for s in substantive:
        counts[s] = counts.get(s, 0) + 1
        if counts[s] >= _MIN_REPETITION_COUNT:
            return True
    return False


def validate_answer_or_raise(
    answer_text: str,
    source_bundle: SourceBundle,
    *,
    disclaimer_required: bool = False,
    grounding_context: str = "",
    query_text: str = "",
    provenance: Optional["ProvenanceStore"] = None,
    enforce_tutor_depth: bool = True,
) -> None:
    """
    Run all twelve Checkpoint C checks. Raises ValidationFailed listing every
    failure (not just the first) if any check fails. Returns None on success.

    provenance (2026-07-23, governed calculation architecture — see
    docs/calculation_architecture.md): an optional per-request
    ProvenanceStore of every expression/formula/PolicyEngine calculation
    that actually executed while composing this answer. Extends check 8
    (numeric fidelity) rather than replacing it — a claimed figure is now
    supported if it appears in grounding_context (unchanged,
    retrieved_fact), OR in query_text (user_provided_input — the user
    stated the figure themselves), OR matches a verified calculation's
    output (policy_engine_result / named_formula_result /
    expression_derived). Passing no provenance store leaves check 8's
    behavior byte-for-byte identical to before this parameter existed.
    """
    failures: list[str] = []

    # 1. Grounding — answer must not claim substantive content with no eligible sources
    if source_bundle.eligible_source_count == 0 and len(answer_text.strip()) > 50:
        failures.append(
            "Grounding check failed: answer contains substantive content "
            "but no eligible sources exist in the SourceBundle."
        )

    # 2. Citation binding — every [REF-N] must map to a real, shown chunk.
    # Prefer the actual grounding_context's own REF headers (the ground
    # truth of what the model was given) over eligible_source_count (a
    # coarser distinct-source count that can be smaller than the number of
    # real chunks shown — see _GROUNDED_REF_HEADER_PATTERN's comment above).
    # Falls back to the eligible_source_count-based range only when no
    # grounding_context is supplied, matching this module's existing
    # convention (see check 8) of degrading gracefully for callers that
    # don't have that context available (e.g. some existing unit tests).
    ref_ids_in_answer = set(_REF_PATTERN.findall(answer_text))
    # grounding_context not containing any "[REF-N] Source:" header (e.g. a
    # caller passing raw content text rather than build_grounded_context's
    # real output) falls back to the eligible_source_count-based range too —
    # an empty grounded-ref set must never mean "nothing is a valid
    # citation," only "this caller didn't give us the real header format."
    grounded_ref_ids = set(_GROUNDED_REF_HEADER_PATTERN.findall(grounding_context)) if grounding_context else set()
    eligible_ids = grounded_ref_ids or set(str(i + 1) for i in range(source_bundle.eligible_source_count))
    unbound_refs = ref_ids_in_answer - eligible_ids
    if unbound_refs:
        failures.append(
            f"Citation binding failed: answer references [REF-{','.join(sorted(unbound_refs))}] "
            f"which are not present in eligible_sources."
        )
    if source_bundle.eligible_source_count > 0 and len(answer_text.strip()) > 50 and not ref_ids_in_answer:
        failures.append(
            "Citation binding failed: substantive answer contains no source citation markers."
        )

    # 3. Prohibited-claim scan
    for pattern in _PROHIBITED:
        if pattern.search(answer_text):
            failures.append(
                f"Prohibited-claim detected: answer contains professional-advice language "
                f"matching pattern '{pattern.pattern}'."
            )
            break

    # 4. Authority ceiling — answer can't claim more certainty than its sources' authority_level
    if source_bundle.authority_level != "primary":
        for pattern in _AUTHORITY_OVERREACH:
            if pattern.search(answer_text):
                failures.append(
                    f"Authority ceiling exceeded: answer uses absolute-authority language "
                    f"('{pattern.pattern}') but source_bundle.authority_level is "
                    f"'{source_bundle.authority_level}', not 'primary'."
                )
                break

    # 5. Confidence support — hedging must match confidence_state
    if source_bundle.confidence_state in _CONFIDENCE_STATES_REQUIRING_HEDGING:
        for pattern in _UNHEDGED_CERTAINTY:
            if pattern.search(answer_text):
                failures.append(
                    f"Confidence support failed: answer uses unhedged certainty language "
                    f"('{pattern.pattern}') but confidence_state is "
                    f"'{source_bundle.confidence_state}'."
                )
                break

    # 6. Disclaimer presence
    if disclaimer_required and _DISCLAIMER_MARKER not in answer_text:
        failures.append(
            "Disclaimer presence check failed: disclaimer_required is True but no "
            f"disclaimer marker ('{_DISCLAIMER_MARKER}') is present in the answer."
        )

    # 7. Licence exposure (Checkpoint C proper) — no internal_reasoning_only /
    # restricted-licence source's title may appear in the answer text.
    exposed: list[str] = []
    for source in source_bundle.sources:
        state = source_bundle.source_display_states.get(source.id)
        if state == "internal_reasoning_only" and source.title and source.title in answer_text:
            exposed.append(source.id)
    if exposed:
        failures.append(
            f"Licence exposure detected: internal_reasoning_only source(s) {exposed} "
            f"appear in the answer text, citations, or metadata."
        )

    # 8. Numeric fidelity — skipped entirely when no grounding_context is
    # supplied (e.g. existing unit tests that don't pass one), matching this
    # module's existing convention of only running checks its inputs support.
    # Provenance-aware extension (2026-07-23, see docstring above): a claim
    # unsupported by grounding_context gets two more chances before it's
    # flagged — query_text (the user stated this figure themselves) and
    # provenance (a governed calculation actually produced this figure) —
    # neither replaces the context-text check, both only widen what counts
    # as supported.
    if grounding_context:
        context_numbers = _extract_normalized_numbers(grounding_context)
        query_numbers = _extract_normalized_numbers(query_text) if query_text else set()
        derived_total, derived_shares = _derived_total_and_shares(query_numbers)
        derived_differences = _derived_differences(query_numbers)
        for match in list(_CLAIMED_FIGURE_PATTERN.finditer(answer_text)) + list(_CLAIMED_DATE_PATTERN.finditer(answer_text)):
            claim_text = match.group()
            if _claim_is_supported(
                claim_text,
                context_numbers=context_numbers,
                query_numbers=query_numbers,
                provenance=provenance,
                derived_total=derived_total,
                derived_shares=derived_shares,
                derived_differences=derived_differences,
            ):
                continue
            failures.append(
                f"Numeric fidelity failed: answer claims a figure ('{claim_text.strip()}') "
                "that does not appear anywhere in the retrieved grounding context, the user's "
                "own query, or a governed calculation record."
            )
            break

    # 9. Repetition / degenerate output — a coherence failure, not a policy
    # violation, so it degrades to HUMAN_REVIEW like every non-prohibited/
    # non-exposure failure below, never REFUSAL.
    if _has_degenerate_repetition(answer_text):
        failures.append(
            "Repetition check failed: answer repeats the same substantive sentence "
            f"{_MIN_REPETITION_COUNT}+ times, indicating the model failed to converge "
            "on a conclusion rather than stating a false claim outright."
        )

    # 10. Missing requested fact — an honest admission is better than a
    # hallucination, but it is still not an "Answer ready" outcome. Route it
    # to clarification so the user can supply a year or an authority can be
    # added, instead of escalating an otherwise safe non-answer to a reviewer.
    if any(pattern.search(answer_text) for pattern in _MISSING_REQUESTED_FACT_PATTERNS):
        failures.append(
            "Missing requested fact: the generated response states that the retrieved "
            "evidence does not contain the exact information requested."
        )

    # 11. Summarize, don't copy — skipped when no grounding_context is
    # supplied, matching this module's existing convention (see checks 8, 2).
    if grounding_context and _has_verbatim_copy(answer_text, grounding_context):
        failures.append(
            f"Summarize-don't-copy check failed: answer reproduces a "
            f"{_MIN_VERBATIM_RUN_WORDS}+ word verbatim passage from the source "
            "context instead of explaining it in Kriton's own words."
        )

    # 12. Tutor-depth structure — skipped when no query_text is supplied
    # (existing callers/tests that don't pass one), and only engaged for
    # queries matching the concept-explanation shape and long enough to be
    # a genuine (if underdeveloped) attempt at one.
    if (
        enforce_tutor_depth
        and query_text
        and _CONCEPT_QUESTION_PATTERN.search(query_text)
        and not _FACTUAL_LOOKUP_OVERRIDE_PATTERN.search(query_text)
        and not _ARITHMETIC_QUESTION_PATTERN.search(query_text)
    ):
        answer_word_count = len(_WORD_PATTERN.findall(answer_text))
        if answer_word_count >= _MIN_WORDS_TO_ENGAGE_CONCEPT_CHECK:
            has_why = bool(_EXPLANATORY_SIGNAL_PATTERN.search(answer_text))
            has_example = bool(_ILLUSTRATIVE_SIGNAL_PATTERN.search(answer_text))
            has_depth = answer_word_count >= _MIN_CONCEPT_ANSWER_WORDS
            # 2026-07-23: only ONE of (why, example) is required, not both —
            # a sparse-source answer that legitimately has depth plus a
            # why-signal but no room for an invented example shouldn't be
            # punished the same as a bare one-line definition with neither.
            if not has_depth or not (has_why or has_example):
                failures.append(
                    "Tutor-depth structure failed: concept-explanation query answered "
                    "without covering the what/why/rule/example structure a tutor-style "
                    "explanation requires (missing: "
                    + ", ".join(
                        label for label, present in (
                            ("sufficient depth", has_depth),
                            ("why/purpose or example", has_why or has_example),
                        ) if not present
                    ) + ")."
                )

    if failures:
        has_prohibited_or_exposure = any(
            "Prohibited" in f or "Licence exposure" in f for f in failures
        )
        missing_fact_only = all("Missing requested fact" in f for f in failures)
        unsupported_number_only = all("Numeric fidelity" in f for f in failures)
        degraded_route = (
            "REFUSAL" if has_prohibited_or_exposure
            else "CLARIFICATION" if missing_fact_only or unsupported_number_only
            else "HUMAN_REVIEW"
        )
        raise ValidationFailed(failures, degraded_route=degraded_route)


def validate_answer(
    answer_text: str,
    source_bundle: SourceBundle,
    *,
    disclaimer_required: bool = False,
    grounding_context: str = "",
    query_text: str = "",
    provenance: Optional[ProvenanceStore] = None,
    enforce_tutor_depth: bool = True,
) -> ValidationResult:
    """Call-site-friendly wrapper: same checks as validate_answer_or_raise(),
    but returns a ValidationResult instead of raising — matches the
    return-value pattern the rest of orchestration/service.py already uses."""
    try:
        validate_answer_or_raise(
            answer_text, source_bundle,
            disclaimer_required=disclaimer_required, grounding_context=grounding_context,
            query_text=query_text, provenance=provenance,
            enforce_tutor_depth=enforce_tutor_depth,
        )
    except ValidationFailed as exc:
        return ValidationResult(passed=False, failures=exc.failures, degraded_route=exc.degraded_route)
    return ValidationResult(passed=True)
