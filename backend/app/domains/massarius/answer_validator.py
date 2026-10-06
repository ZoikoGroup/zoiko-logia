"""
Massarius™ retrieval and evidence subsystem — Checkpoint C, output exposure
gate (ZL-ENG-02 §10 / Release Gate RG-03, ZL-ENG-03 §5.7).

Supersedes app/orchestration/composition_validator.py, which covers only 3 of
the 7 checks below (grounding, citation binding, prohibited-claim scan) —
those three are reused here rather than reimplemented, since they already
work correctly. This module adds the remaining four: authority ceiling,
confidence support, disclaimer presence, and licence exposure — the last of
which composition_validator.py could never have implemented, since
source_display_states didn't exist until this Phase 1 work.

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

from app.domains.massarius.errors import ValidationFailed
from app.orchestration.schemas import SourceBundle, ValidationResult

# ── 1. Prohibited professional claim patterns (reused from composition_validator.py) ──
# Directive wording ("you must register", "you should pay") is personal
# advice only when the question is about the asker's own or a client's
# matter (risk HIGH). In a general question it describes the rule: "how long
# do I have to register for VAT?" and "how do penalty points work?" were both
# refused for restating HMRC's own wording. Checked only for user-specific
# questions; the claims below are blocked whatever the question.
_DIRECTIVE = re.compile(r"you\s+(should|must|need\s+to)\s+(file|register|pay|submit|declare)", re.IGNORECASE)

def is_directive_failure(failure: str) -> bool:
    """A validation failure raised only by directive wording on a
    user-specific question — curable by restating the answer as general
    guidance, unlike the other prohibited claims."""
    return failure.startswith("Prohibited-claim detected") and _DIRECTIVE.pattern in failure


_PROHIBITED_PATTERNS = [
    r"(your|the\s+company('s)?)\s+(tax\s+(liability|return)|audit\s+opinion)",
    r"i\s+(confirm|certify|guarantee|assure)\s+(that\s+)?",
    # Kriton CLAIMING its answer is professional advice/an opinion. "this is"
    # used to be optional, so merely explaining the TOPIC ("the types of audit
    # opinions") was refused as a prohibited claim.
    r"\bthis\s+(is|constitutes)\s+(a\s+|an\s+|my\s+|formal\s+|professional\s+)*(legal|tax|audit|financial)\s+(advice|opinion|certification)",
    r"as\s+your\s+(accountant|auditor|tax\s+advisor|legal\s+counsel)",
    r"(sign|signature|signed)\s+(off|on)\s+(by|as)",
]
_PROHIBITED = [re.compile(p, re.IGNORECASE) for p in _PROHIBITED_PATTERNS]


def _normalise_for_match(text: str) -> str:
    return " ".join(re.sub(r"[\u2018\u2019]", "'", text or "").lower().split())

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
    # "always" and "guarantee" are ordinary accounting words ("debits must
    # always equal credits", "bank guarantee", IFRS 9 "financial guarantee
    # contracts"), not certainty claims; flagging them escalated correct answers.
    r"\bdefinitely\b", r"\bnever\s+wrong\b",
    r"\bwithout\s+(a\s+)?doubt\b", r"\b100%\s+certain\b",
]
_UNHEDGED_CERTAINTY = [re.compile(p, re.IGNORECASE) for p in _UNHEDGED_CERTAINTY_PATTERNS]

_CONFIDENCE_STATES_REQUIRING_HEDGING = {"limited", "insufficient", "conflicting_sources", "stale_sources"}

_REF_PATTERN = re.compile(r"\[REF-(\d+)\]")

# ── 6. Disclaimer presence marker — matches the text
# orchestration/composition_validator.py's build_validated_disclaimer appends ──
_DISCLAIMER_MARKER = "Kriton™ Disclaimer"


def validate_answer_or_raise(
    answer_text: str,
    source_bundle: SourceBundle,
    *,
    disclaimer_required: bool = False,
    external_source_count: int = 0,
    ungrounded_answer_allowed: bool = False,
    evidence_text: str = "",
    user_specific: bool = False,
) -> None:
    """
    Run all seven Checkpoint C checks. Raises ValidationFailed listing every
    failure (not just the first) if any check fails. Returns None on success.

    external_source_count is the number of live retrieval sources the answer was
    actually composed against — SearXNG hits plus the exact-figure connectors
    (orchestration/live_data.py), which become the [REF-N] citations the reader
    sees. They are evidence, but they are not registered in the governed
    SourceBundle, so counting only bundle sources treats a fully web-grounded
    answer as ungrounded and degrades it to HUMAN_REVIEW. An answer is
    unsupported only when NEITHER kind of source exists.
    """
    failures: list[str] = []

    # 1. Grounding — answer must not claim substantive content with no sources
    # of any kind behind it.
    # Skipped only when routing already decided to answer without governed
    # evidence (policy pm_1.1/pm_1.2) — that answer carries an explicit
    # "no sources could be retrieved" caveat, so failing it here would
    # escalate the very answers the policy chose to give.
    total_sources = source_bundle.eligible_source_count + max(external_source_count, 0)
    if total_sources == 0 and len(answer_text.strip()) > 50 and not ungrounded_answer_allowed:
        failures.append(
            "Grounding check failed: answer contains substantive content "
            "but no eligible sources exist in the SourceBundle and no live "
            "retrieval sources were supplied."
        )

    # 2. Citation binding — every [REF-N] must map to a source the reader can
    # actually open. [REF-N] is assigned positionally over the live citations
    # when there are any (see orchestration/service.py), so the valid range is
    # whichever collection the markers were drawn from.
    ref_ids_in_answer = set(_REF_PATTERN.findall(answer_text))
    eligible_ids = set(
        str(i + 1)
        for i in range(max(source_bundle.eligible_source_count, max(external_source_count, 0)))
    )
    unbound_refs = ref_ids_in_answer - eligible_ids
    if unbound_refs:
        failures.append(
            f"Citation binding failed: answer references [REF-{','.join(sorted(unbound_refs))}] "
            f"which are not present in eligible_sources."
        )

    # 3. Prohibited-claim scan. A phrase the cited evidence itself contains is
    # the law being quoted, not advice being given: HMRC's own guidance says
    # "You must register if…", and an answer restating it was refused as a
    # professional sign-off. Wording with no such backing is still blocked.
    evidence = _normalise_for_match(evidence_text)
    for pattern in [_DIRECTIVE, *_PROHIBITED] if user_specific else _PROHIBITED:
        if any(
            _normalise_for_match(match.group(0)) not in evidence
            for match in pattern.finditer(answer_text)
        ):
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

    if failures:
        has_prohibited_or_exposure = any(
            "Prohibited" in f or "Licence exposure" in f for f in failures
        )
        degraded_route = "REFUSAL" if has_prohibited_or_exposure else "HUMAN_REVIEW"
        raise ValidationFailed(failures, degraded_route=degraded_route)


def validate_answer(
    answer_text: str,
    source_bundle: SourceBundle,
    *,
    disclaimer_required: bool = False,
    external_source_count: int = 0,
    ungrounded_answer_allowed: bool = False,
    evidence_text: str = "",
    user_specific: bool = False,
) -> ValidationResult:
    """Call-site-friendly wrapper: same checks as validate_answer_or_raise(),
    but returns a ValidationResult instead of raising — matches the
    return-value pattern the rest of orchestration/service.py already uses."""
    try:
        validate_answer_or_raise(
            answer_text,
            source_bundle,
            disclaimer_required=disclaimer_required,
            external_source_count=external_source_count,
            ungrounded_answer_allowed=ungrounded_answer_allowed,
            evidence_text=evidence_text,
            user_specific=user_specific,
        )
    except ValidationFailed as exc:
        return ValidationResult(passed=False, failures=exc.failures, degraded_route=exc.degraded_route)
    return ValidationResult(passed=True)
