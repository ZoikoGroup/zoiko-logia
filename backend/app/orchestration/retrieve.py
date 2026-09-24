"""Rights-filtered lexical passage retrieval and evidence planning.

Source/version eligibility is resolved before passage content is loaded. Denied
text therefore never enters ranking or model context.
"""
from __future__ import annotations

import re
import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.source_library.licensing import SourceUseContext, can_use
from app.domains.source_library.models import Source, SourcePassage, SourceRelationship, SourceVersion
from app.orchestration.schemas import (
    EvidencePassage, ExcludedEvidence, RetrievalPlan, SourceBundle, SourceSummary,
)
from app.orchestration.routing_matrix import (
    CONF_CONFLICTING, CONF_INSUFFICIENT, CONF_LIMITED, CONF_RESTRICTED, CONF_SUFFICIENT,
)

INDEX_VERSION = "source-passages-lexical-v1"
_ELIGIBLE_STATUSES = {"ACTIVE", "APPROVED"}
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]+", re.I)
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "the", "this", "to",
    "what", "when", "which", "with",
}


def _tokens(value: str) -> set[str]:
    return {
        token.casefold() for token in _TOKEN_RE.findall(value)
        if token.casefold() not in _STOP_WORDS
    }


def _lexical_score(query_tokens: set[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    content_tokens = _tokens(content)
    overlap = query_tokens & content_tokens
    if not overlap:
        return 0.0
    coverage = len(overlap) / len(query_tokens)
    density = len(overlap) / max(len(content_tokens), 1)
    return round((coverage * 0.85) + (min(density * 5, 1.0) * 0.15), 6)


def build_retrieval_plan(*, jurisdiction: str, framework: str, top_k: int = 8) -> RetrievalPlan:
    return RetrievalPlan(
        retrieval_plan_id=f"rp-{uuid.uuid4().hex[:12]}",
        strategy="rights_filtered_lexical_passages",
        methods=["keyword"],
        jurisdiction=jurisdiction,
        framework=framework,
        requires_current_sources=True,
        top_k=top_k,
        index_version=INDEX_VERSION,
        risk_notes=[
            "Semantic retrieval is disabled until an evaluated embedding index is configured."
        ],
    )


async def _candidate_versions(
    db: AsyncSession, *, tenant_id: str,
) -> list[tuple[Source, SourceVersion]]:
    """Load candidate metadata only, choosing the newest approved version."""
    result = await db.execute(
        select(Source, SourceVersion)
        .join(SourceVersion, SourceVersion.source_id == Source.id)
        .where(
            SourceVersion.status.in_(_ELIGIBLE_STATUSES),
            or_(Source.is_tenant_private.is_(False), Source.tenant_id == tenant_id),
        )
        .order_by(Source.id, SourceVersion.created_at.desc())
    )
    latest: dict[str, tuple[Source, SourceVersion]] = {}
    for source, version in result.all():
        latest.setdefault(source.id, (source, version))
    return list(latest.values())


async def build_source_bundle(
    db: AsyncSession,
    *,
    query: str,
    jurisdiction: str,
    tenant_id: str,
    framework: str = "",
    effective_date: date | None = None,
    top_k: int = 8,
) -> SourceBundle:
    """Execute a bounded, context-aware lexical passage search."""
    plan = build_retrieval_plan(jurisdiction=jurisdiction, framework=framework, top_k=top_k)
    context = SourceUseContext(
        tenant_id=tenant_id, jurisdiction=jurisdiction,
        framework=framework, effective_date=effective_date,
    )

    eligible_rows: list[tuple[Source, SourceVersion]] = []
    excluded: list[ExcludedEvidence] = []
    for source, version in await _candidate_versions(db, tenant_id=tenant_id):
        decision = await can_use(db, version.id, context, "retrieval")
        if decision.allowed:
            eligible_rows.append((source, version))
        else:
            excluded.append(ExcludedEvidence(
                source_id=source.id, source_version_id=version.id,
                reason_code=decision.reason_code,
            ))

    # Only now is source text loaded: every version in this query has already
    # passed tenant, status, date, framework, jurisdiction and retrieval-right checks.
    version_ids = [version.id for _, version in eligible_rows]
    passages: list[SourcePassage] = []
    if version_ids:
        result = await db.execute(
            select(SourcePassage)
            .where(SourcePassage.source_version_id.in_(version_ids))
            .order_by(SourcePassage.source_version_id, SourcePassage.sequence)
        )
        passages = list(result.scalars().all())

    version_to_source = {version.id: source for source, version in eligible_rows}
    query_tokens = _tokens(query)
    ranked: list[tuple[float, SourcePassage]] = []
    for passage in passages:
        score = _lexical_score(query_tokens, passage.content)
        if score > 0:
            ranked.append((score, passage))
        else:
            source = version_to_source[passage.source_version_id]
            excluded.append(ExcludedEvidence(
                source_id=source.id, source_version_id=passage.source_version_id,
                passage_id=passage.id, reason_code="NO_LEXICAL_MATCH",
            ))
    ranked.sort(key=lambda item: (-item[0], item[1].sequence, item[1].id))
    ranked = ranked[:plan.top_k]

    selected_passages = [
        EvidencePassage(
            passage_id=passage.id,
            source_id=version_to_source[passage.source_version_id].id,
            source_version_id=passage.source_version_id,
            locator=passage.locator,
            content_hash=passage.content_hash,
            score=score,
            rank=rank,
            method="keyword",
        )
        for rank, (score, passage) in enumerate(ranked, start=1)
    ]
    selected_version_ids = {item.source_version_id for item in selected_passages}
    selected_sources = [
        SourceSummary(
            id=source.id, version_id=version.id, title=source.title,
            category=source.category, jurisdiction_scope=source.jurisdiction_scope,
            version_label=version.version_label, status=version.status,
        )
        for source, version in eligible_rows if version.id in selected_version_ids
    ]

    conflict_version_ids: set[str] = set()
    if selected_version_ids:
        result = await db.execute(
            select(SourceRelationship).where(
                SourceRelationship.relationship_type == "conflicts",
                SourceRelationship.from_version_id.in_(selected_version_ids),
                SourceRelationship.to_version_id.in_(selected_version_ids),
            )
        )
        for relationship in result.scalars().all():
            conflict_version_ids.update((relationship.from_version_id, relationship.to_version_id))

    if conflict_version_ids:
        confidence = CONF_CONFLICTING
    elif not selected_passages:
        confidence = CONF_RESTRICTED if excluded and not eligible_rows else CONF_INSUFFICIENT
    elif len(selected_passages) < 2:
        confidence = CONF_LIMITED
    else:
        confidence = CONF_SUFFICIENT

    authority_levels = {
        source.authority_level for source, version in eligible_rows
        if version.id in selected_version_ids
    }
    authority_level = (
        "primary" if "primary" in authority_levels
        else "internal" if authority_levels == {"internal"}
        else "secondary"
    )
    return SourceBundle(
        source_bundle_id=f"sb-{uuid.uuid4().hex[:12]}",
        retrieval_method="lexical_passages_v1",
        eligible_source_count=len(selected_sources),
        excluded_source_count=len(excluded),
        sources=selected_sources,
        exclusion_reasons=[
            f"{item.source_id}:{item.passage_id or item.source_version_id or ''}:{item.reason_code}"
            for item in excluded
        ],
        jurisdiction=jurisdiction,
        authority_level=authority_level,
        freshness_state="current" if selected_passages else "unknown",
        licence_state="permitted" if selected_passages else "unknown",
        confidence_state=confidence,
        index_version=INDEX_VERSION,
        retrieval_plan=plan,
        passages=selected_passages,
        excluded_evidence=excluded,
        conflict_version_ids=sorted(conflict_version_ids),
    )
