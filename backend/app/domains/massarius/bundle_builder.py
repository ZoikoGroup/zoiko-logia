"""
Massarius™ retrieval and evidence subsystem — sole producer of the canonical
SourceBundle (ZL-ENG-03 §5.5, Acceptance Criterion 3).

Consumes the preliminary passage-ranked SourceBundle from
app/orchestration/retrieve.py plus license_gate.py's model-transmission and
display result, and
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.source_library.models import SourcePassage
from app.orchestration.models import EvidenceBundleEntry, EvidenceBundleManifest
from app.orchestration.schemas import ExcludedEvidence, SourceBundle

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

    eligible_source_ids = {source.id for source in licence_result.eligible}
    eligible_version_ids = {source.version_id for source in licence_result.eligible}
    gate_exclusions = [
        ExcludedEvidence(
            source_id=source.id,
            source_version_id=source.version_id or None,
            reason_code=licence_result.exclusion_reasons.get(source.id, "LICENCE_GATE_DENIED"),
        )
        for source in licence_result.excluded
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
        index_version=preliminary.index_version,
        retrieval_plan=preliminary.retrieval_plan,
        passages=[
            passage for passage in preliminary.passages
            if passage.source_id in eligible_source_ids
        ],
        excluded_evidence=[*preliminary.excluded_evidence, *gate_exclusions],
        conflict_version_ids=[
            version_id for version_id in preliminary.conflict_version_ids
            if version_id in eligible_version_ids
        ],
        manifest_version=preliminary.manifest_version,
    )


async def persist_bundle(
    db: AsyncSession, *, bundle: SourceBundle, tenant_id: str, query_id: str,
) -> None:
    """Persist the exact immutable manifest before it can influence an answer."""
    plan = bundle.retrieval_plan.model_dump(mode="json") if bundle.retrieval_plan else {}
    db.add(EvidenceBundleManifest(
        id=bundle.source_bundle_id,
        tenant_id=tenant_id,
        query_id=query_id,
        retrieval_plan=plan,
        manifest=bundle.model_dump(mode="json"),
        index_version=bundle.index_version,
    ))
    for passage in bundle.passages:
        db.add(EvidenceBundleEntry(
            bundle_id=bundle.source_bundle_id,
            tenant_id=tenant_id,
            source_id=passage.source_id,
            source_version_id=passage.source_version_id,
            passage_id=passage.passage_id,
            disposition="selected",
            reason_code="SELECTED",
            rank=passage.rank,
            score=passage.score,
            retrieval_method=passage.method,
            content_hash=passage.content_hash,
        ))
    for item in bundle.excluded_evidence:
        db.add(EvidenceBundleEntry(
            bundle_id=bundle.source_bundle_id,
            tenant_id=tenant_id,
            source_id=item.source_id,
            source_version_id=item.source_version_id or "",
            passage_id=item.passage_id or "",
            disposition="excluded",
            reason_code=item.reason_code,
            retrieval_method=bundle.retrieval_method,
        ))
    await db.commit()


async def load_bundle_passage_text(db: AsyncSession, bundle: SourceBundle) -> list[tuple[str, str, str]]:
    """Reload exact selected text by immutable IDs and verify hashes."""
    passage_ids = [item.passage_id for item in bundle.passages]
    if not passage_ids:
        return []
    result = await db.execute(select(SourcePassage).where(SourcePassage.id.in_(passage_ids)))
    by_id = {passage.id: passage for passage in result.scalars().all()}
    loaded: list[tuple[str, str, str]] = []
    for selection in sorted(bundle.passages, key=lambda item: item.rank):
        passage = by_id.get(selection.passage_id)
        if passage is None or passage.content_hash != selection.content_hash:
            raise ValueError(f"Evidence passage integrity check failed: {selection.passage_id}")
        loaded.append((selection.passage_id, selection.locator, passage.content))
    return loaded
