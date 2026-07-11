"""
Massarius™ retrieval and evidence subsystem — risk classification ordering
contract (ZL-ENG-03 §5.6, paired with policy_matrix.py; Acceptance Criterion 6).

The spec treats risk_safety as a Phase 1 control dependency even though it
isn't in the Phase 1 file table in §9, because policy_matrix.py can't be
meaningfully tested without something producing its risk_level input. This
is flagged explicitly per the spec's own request — it's a scope note, not a
silent scope expansion: the actual classifier (app/domains/risk_safety/) is
mature, pre-existing, and unchanged here.

What this module adds is the ordering guarantee: risk classification must
run AFTER bundle_builder.py has *attempted* to produce the final
SourceBundle, not before and not against retrieve.py's preliminary output.
orchestration/service.py must call classify_after_bundle(), not
risk_safety_service.evaluate() directly, so the ordering can't silently
regress at a call site. bundle_attempted=False is a distinct, legitimate
case from "ordering was skipped" — it means retrieval/bundle construction
itself failed (an exception, not a bundle_builder.py bypass), which is a
real degraded-confidence scenario the classifier still needs to score
(source_confidence falls back to "insufficient" upstream); it is NOT the
ordering violation this wrapper exists to catch, which is a caller invoking
classification without bundle_builder.py's step having run at all.

Must NOT: reimplement classification logic (app/domains/risk_safety/
service.py's job) or decide routing (policy_matrix.py's job).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.risk_safety import service as risk_safety_service
from app.domains.risk_safety.schemas import ClassifyRequest, SafetyDecision


def classify_after_bundle(
    bundle_attempted: bool,
    request: ClassifyRequest,
    db: Session,
) -> SafetyDecision:
    """
    Run risk classification. Raises if bundle_attempted is False — meaning
    the caller never went through bundle_builder.build_bundle() at all
    (the ordering bug ZL-ENG-03 §5.6 exists to prevent). Pass
    bundle_attempted=True whether bundle_builder.py succeeded or the whole
    retrieval step failed with an exception first — both mean the step was
    reached in order; only skipping it entirely is the violation.
    """
    if not bundle_attempted:
        raise RuntimeError(
            "classify_after_bundle() called without bundle_builder.py having "
            "run first — risk classification must run after bundle "
            "construction is attempted, not before."
        )
    return risk_safety_service.evaluate(request, db=db)
