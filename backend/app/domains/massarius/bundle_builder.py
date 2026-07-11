"""
Massarius™ retrieval and evidence subsystem — sole producer of the canonical
SourceBundle (ZL-ENG-03 §5.5, Acceptance Criterion 3).

Consumes the preliminary SourceBundle app/orchestration/retrieve.py already
constructs (that file's own bundle assembly is treated here as raw,
implementation-detail retrieval output — a keyword_mvp candidate list, not
the final evidence object) plus license_gate.py's Checkpoint A/B result, and
produces the one SourceBundle every downstream step actually uses. The
result is frozen (SourceBundle.model_config sets frozen=True in
orchestration/schemas.py) — nothing after this point can mutate it.

Must NOT: perform reranking, retrieval, or licence decisions itself (those
are retrieve.py and license_gate.py's jobs) or risk classification
(risk_safety.py's job, and it must only run after this module has produced
its output).
"""
from __future__ import annotations

from app.domains.massarius.license_gate import LicenceCheckResult
from app.orchestration.schemas import SourceBundle

INDEX_VERSION = "v1"

_DOWNGRADE_ON_EXCLUSION = {
    "sufficient": "limited",
    "limited": "insufficient",
}


def build_bundle(preliminary: SourceBundle, licence_result: LicenceCheckResult) -> SourceBundle:
    """
    Build the final, frozen SourceBundle from retrieve.py's preliminary
    output plus Checkpoint A/B's eligibility decision.

    If license_gate.py excluded sources retrieve.py had counted as eligible,
    confidence_state is downgraded one step (sufficient -> limited -> ...) —
    the bundle retrieve.py handed us was optimistic about eligibility;
    this corrects it rather than silently reporting a confidence higher
    than what actually survived the licence gate.
    """
    newly_excluded = len(licence_result.excluded)
    confidence_state = preliminary.confidence_state
    if newly_excluded and not licence_result.eligible:
        confidence_state = "restricted_sources"
    elif newly_excluded:
        confidence_state = _DOWNGRADE_ON_EXCLUSION.get(confidence_state, confidence_state)

    exclusion_reasons = list(preliminary.exclusion_reasons) + [
        f"{source_id}: {reason}" for source_id, reason in licence_result.exclusion_reasons.items()
    ]

    return SourceBundle(
        source_bundle_id=preliminary.source_bundle_id,
        retrieval_method=preliminary.retrieval_method,
        eligible_source_count=len(licence_result.eligible),
        excluded_source_count=preliminary.excluded_source_count + newly_excluded,
        sources=licence_result.eligible,
        exclusion_reasons=exclusion_reasons,
        jurisdiction=preliminary.jurisdiction,
        authority_level=preliminary.authority_level,
        freshness_state=preliminary.freshness_state,
        licence_state=preliminary.licence_state,
        confidence_state=confidence_state,
        source_display_states=licence_result.display_states,
        index_version=INDEX_VERSION,
    )
