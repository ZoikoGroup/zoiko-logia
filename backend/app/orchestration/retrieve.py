"""
Massarius™ source retrieval layer — ZL-ENG-02 §7.

MVP: category-keyword source selection. Pre-RAG.
DO NOT label this as RAG in code comments, docs or external materials until §7 criteria are met:
  embeddings, chunking, semantic retrieval, ranking, re-ranking, citation binding,
  retrieval evaluation, hallucination checks and source freshness handling.

retrieval_method = "keyword_mvp" in all SourceBundle responses.

Tenant isolation: every source_library query carries tenant_id at the data-access layer.
Application-level filtering alone is not sufficient (§7.1).
"""
from __future__ import annotations

import uuid
import os
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.source_library.service import list_sources, get_source_by_id
from app.orchestration.schemas import SourceBundle, SourceSummary
from app.orchestration.routing_matrix import (
    CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT,
    CONF_CONFLICTING, CONF_STALE, CONF_RESTRICTED,
)

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "tax": ["tax"],
    "audit": ["audit", "going concern"],
    "payroll-compliance": ["payroll", "employment"],
    "internal-policies": ["internal policy", "firm policy"],
    "education-content": ["exam", "study", "cpd", "syllabus"],
}
_DEFAULT_CATEGORY = "standards"

# Sources with these statuses are eligible for retrieval
_ELIGIBLE_STATUSES = {"ACTIVE", "APPROVED"}

# Sources with these statuses are excluded as restricted
_RESTRICTED_STATUSES = {"DRAFT", "DEPRECATED", "BLOCKED", "RESTRICTED"}


def infer_category(query: str) -> str:
    lowered = query.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return _DEFAULT_CATEGORY


async def build_source_bundle(
    db: AsyncSession,
    *,
    query: str,
    jurisdiction: str,
    tenant_id: str,
) -> SourceBundle:
    """
    Build a SourceBundle via keyword-based category retrieval, merged with
    governance-verified vector search hits.
    tenant_id is enforced at the data-access layer via list_sources /
    get_source_by_id.
    Returns confidence_state per §7.2 six-state vocabulary.
    """
    category = infer_category(query)

    eligible = []
    excluded = []
    exclusion_reasons = []
    has_restricted = False
    has_conflict = False

    # Always resolve the governed keyword_mvp candidates first — vector hits
    # below are additive evidence, never a replacement for this. Previously,
    # any non-empty vector result short-circuited this list entirely (an
    # `if vector_sources: ... else: ...` branch), so a single unrelated
    # vector match — or a chunk embedded outside the governance workflow —
    # could make a properly registered, ACTIVE source disappear from the
    # bundle with no error at all.
    candidates = await list_sources(db, category, tenant_id=tenant_id)
    seen_ids = set()
    for c in candidates:
        version_status = c["latest_version"].status
        jur_ok = (not jurisdiction) or c["jurisdiction_scope"] in ("Global", jurisdiction)

        if version_status in _RESTRICTED_STATUSES:
            excluded.append(c)
            exclusion_reasons.append(f"Source '{c['title']}' has restricted status: {version_status}")
            has_restricted = True
        elif version_status not in _ELIGIBLE_STATUSES:
            excluded.append(c)
            exclusion_reasons.append(f"Source '{c['title']}' has ineligible status: {version_status}")
        elif not jur_ok:
            excluded.append(c)
            exclusion_reasons.append(f"Source '{c['title']}' outside jurisdiction scope")
        else:
            eligible.append(c)
        seen_ids.add(c["id"])

    if os.getenv("ENABLE_RAG_EMBEDDINGS", "").lower() in {"1", "true", "yes"}:
        # ── Vector Search ──
        # Chunk metadata is untrusted as far as governance goes — it's
        # whatever was present at embed time, which can go stale (a source
        # later deprecated) or never have existed as a real governed record
        # at all (chunks embedded outside create_source/approve_source_version,
        # e.g. via the upload path). Every hit is re-checked against the real
        # sources/source_versions record by source_id, through the same
        # status/jurisdiction rules as the keyword path above — never taken
        # at face value as "ACTIVE".
        from app.domains.rag.retrieval import retrieve_documents

        try:
            raw_chunks = await retrieve_documents(
                query=query,
                tenant_id=tenant_id,
                jurisdiction=jurisdiction or None,
                top_k=5
            )
            checked_source_ids = set()
            for chunk in raw_chunks:
                meta = chunk.get("metadata", {})
                source_id = meta.get("source_id")
                title = meta.get("title", "unknown")
                if not source_id:
                    exclusion_reasons.append(
                        f"Vector chunk '{title}' has no linked source_id — not embedded via the governed source workflow, excluded"
                    )
                    continue
                if source_id in seen_ids or source_id in checked_source_ids:
                    continue
                checked_source_ids.add(source_id)

                governed = await get_source_by_id(db, source_id, tenant_id=tenant_id)
                if governed is None:
                    exclusion_reasons.append(f"{source_id}: source_record_not_found")
                    continue

                version_status = governed["latest_version"].status if governed["latest_version"] else None
                jur_ok = (not jurisdiction) or governed["jurisdiction_scope"] in ("Global", jurisdiction)

                if version_status in _RESTRICTED_STATUSES:
                    excluded.append(governed)
                    exclusion_reasons.append(f"Source '{governed['title']}' has restricted status: {version_status}")
                    has_restricted = True
                elif version_status not in _ELIGIBLE_STATUSES:
                    excluded.append(governed)
                    exclusion_reasons.append(f"Source '{governed['title']}' has ineligible status: {version_status}")
                elif not jur_ok:
                    excluded.append(governed)
                    exclusion_reasons.append(f"Source '{governed['title']}' outside jurisdiction scope")
                else:
                    eligible.append(governed)
                    seen_ids.add(source_id)
        except Exception as e:
            exclusion_reasons.append(f"Vector store search failed: {str(e)}")

    # Determine confidence_state per §7.2
    if has_restricted and len(eligible) == 0:
        confidence_state = CONF_RESTRICTED
    elif len(eligible) == 0:
        confidence_state = CONF_INSUFFICIENT
    elif len(eligible) == 1:
        confidence_state = CONF_LIMITED
    elif has_conflict:
        confidence_state = CONF_CONFLICTING
    else:
        confidence_state = CONF_SUFFICIENT

    # Determine authority_level from category
    authority_level = "primary" if category in ("audit", "tax") else "secondary"

    return SourceBundle(
        source_bundle_id=f"sb-{uuid.uuid4().hex[:12]}",
        retrieval_method="keyword_mvp",  # §7: do not label as RAG
        eligible_source_count=len(eligible),
        excluded_source_count=len(excluded),
        sources=[
            SourceSummary(
                id=c["id"],
                title=c["title"],
                category=c["category"],
                jurisdiction_scope=c["jurisdiction_scope"],
                version_label=c["latest_version"].version_label,
                status=c["latest_version"].status,
            )
            for c in eligible
        ],
        exclusion_reasons=exclusion_reasons,
        jurisdiction=jurisdiction,
        authority_level=authority_level,
        freshness_state="unknown",   # TODO: implement freshness check in full RAG phase
        licence_state="permitted",   # MVP assumption; enforce per-source in production
        confidence_state=confidence_state,
    )
