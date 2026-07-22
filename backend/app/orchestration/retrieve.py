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
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.jurisdiction_locale.service import acceptable_jurisdiction_scopes
from app.domains.source_library.service import list_sources, get_source_by_id
from app.orchestration.schemas import SourceBundle, SourceSummary
from app.orchestration.routing_matrix import (
    CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT,
    CONF_CONFLICTING, CONF_STALE, CONF_RESTRICTED,
)


def _jurisdiction_ok(source_scope: str, jurisdiction: str) -> bool:
    """A source is in-scope for the requested jurisdiction when there's no
    jurisdiction filter at all, the source is globally scoped, or the
    source's own scope is one of the values acceptable_jurisdiction_scopes()
    returns for this request (exact match for most jurisdictions; also the
    bare state code and "US" for a state-qualified one like "US-CA")."""
    if not jurisdiction:
        return True
    return source_scope == "Global" or source_scope in acceptable_jurisdiction_scopes(jurisdiction)

import math
from app.domains.rag.embeddings import get_embed_model, get_query_embedding_cached

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "tax": ["tax"],
    "audit": ["audit", "going concern"],
    "payroll-compliance": ["payroll", "employment"],
    "internal-policies": ["internal policy", "firm policy"],
    "education-content": ["exam", "study", "cpd", "syllabus"],
}
_DEFAULT_CATEGORY = "standards"

_CATEGORY_EXEMPLARS: dict[str, list[str]] = {
    "tax": ["tax guidelines", "corporate taxation", "vat compliance", "tax filings", "hmrc regulations"],
    "audit": ["audit procedures", "going concern assessment", "financial auditing standards", "auditor report", "audit testing"],
    "payroll-compliance": ["payroll processing", "employment regulations", "paye compliance", "national insurance", "payroll compliance"],
    "internal-policies": ["internal company policy", "firm handbook", "employee guidelines", "internal procedures"],
    "education-content": ["cpd training syllabus", "accounting exam questions", "study materials", "syllabus", "exam preparation"],
}

_exemplar_embeddings: dict[str, list[list[float]]] = {}

def _get_exemplar_embeddings() -> dict[str, list[list[float]]]:
    global _exemplar_embeddings
    if not _exemplar_embeddings:
        model = get_embed_model()
        for category, phrases in _CATEGORY_EXEMPLARS.items():
            _exemplar_embeddings[category] = [list(get_query_embedding_cached(phrase)) for phrase in phrases]
    return _exemplar_embeddings

def cosine_similarity(v1: list[float] | tuple[float, ...], v2: list[float] | tuple[float, ...]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(a * a for a in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)

def infer_category(query: str, query_embedding: tuple[float, ...] | None = None) -> str:
    """query_embedding: pass an already-computed embedding for this exact
    query (e.g. the one orchestration/service.py already computed to run
    the real vector search) to skip embedding it a second time here. A
    caller with no embedding on hand (e.g. a standalone/test call, or
    embeddings disabled entirely) still gets one computed inline — that
    fallback is fine for those rare/non-request-serving paths, but the
    normal request path must always pass one through to avoid a second,
    redundant, blocking model call for the same text."""
    try:
        q_emb = query_embedding if query_embedding is not None else get_query_embedding_cached(query)
        exemplar_embs = _get_exemplar_embeddings()
        
        best_category = _DEFAULT_CATEGORY
        best_score = 0.35  # similarity threshold
        
        for category, p_embs in exemplar_embs.items():
            max_sim = max(cosine_similarity(q_emb, p_emb) for p_emb in p_embs)
            if max_sim > best_score:
                best_score = max_sim
                best_category = category
        return best_category
    except Exception:
        lowered = query.lower()
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                return category
        return _DEFAULT_CATEGORY

# Sources with these statuses are eligible for retrieval
_ELIGIBLE_STATUSES = {"ACTIVE", "APPROVED"}

# Sources with these statuses are excluded as restricted
_RESTRICTED_STATUSES = {"DRAFT", "DEPRECATED", "BLOCKED", "RESTRICTED"}


async def build_source_bundle(
    db: AsyncSession,
    *,
    query: str,
    jurisdiction: str,
    tenant_id: str,
    raw_chunks: list | None = None,
    extra_sources: Optional[list[SourceSummary]] = None,
    query_embedding: tuple[float, ...] | None = None,
) -> SourceBundle:
    """
    Build a SourceBundle via keyword-based category retrieval, merged with
    governance-verified vector search hits.
    tenant_id is enforced at the data-access layer via list_sources /
    get_source_by_id.
    Returns confidence_state per §7.2 six-state vocabulary.

    query_embedding: forwarded to infer_category() — pass the same
    embedding already computed for raw_chunks' vector search (when one
    exists) so the semantic category step doesn't redundantly re-embed the
    same query text. See infer_category()'s docstring.

    raw_chunks: pass already-fetched vector search results (e.g. the same
    chunks orchestration/service.py separately fetches at a larger top_k for
    the LLM's grounded context) to skip this function's own retrieve_documents()
    call entirely. retrieve_documents() embeds the query text and does a real
    Postgres vector search — profiling showed it costs ~20s per call on this
    setup, and it was previously being called twice per request (once here at
    top_k=5, once in service.py at top_k=30) for the exact same query, which
    is pure waste. Pass None (the old behavior) to have this function fetch
    its own chunks, e.g. for standalone/test use.

    extra_sources: pre-built SourceSummary entries from a peer retrieval
    method (currently: app.domains.live_sources — a live external-data fetch
    already resolved by the caller). These aren't source_library rows, so no
    status/jurisdiction filtering applies here; they're added straight to
    eligible and folded into the same confidence_state calculation below.
    Eligibility/licence checks for them happen downstream in
    massarius/license_gate.py, same as document sources.
    """
    category = infer_category(query, query_embedding=query_embedding)

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
        jur_ok = _jurisdiction_ok(c["jurisdiction_scope"], jurisdiction)

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
        try:
            if raw_chunks is None:
                from app.domains.rag.retrieval import retrieve_documents

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
                jur_ok = _jurisdiction_ok(governed["jurisdiction_scope"], jurisdiction)

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

    # Kept separate from `eligible` (governed source dicts, keyed by c["id"])
    # rather than merged into it — extra_sources are already-built
    # SourceSummary objects (e.g. from app.domains.live_sources), not
    # source_library rows, so they can't go through the c["id"]-style dict
    # access the final sources= comprehension below uses for `eligible`.
    eligible_extra: list[SourceSummary] = []
    for extra in (extra_sources or []):
        if extra.id in seen_ids:
            continue
        eligible_extra.append(extra)
        seen_ids.add(extra.id)

    total_eligible_count = len(eligible) + len(eligible_extra)

    # Determine confidence_state per §7.2
    if has_restricted and total_eligible_count == 0:
        confidence_state = CONF_RESTRICTED
    elif total_eligible_count == 0:
        confidence_state = CONF_INSUFFICIENT
    elif total_eligible_count == 1:
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
        eligible_source_count=total_eligible_count,
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
        ] + eligible_extra,
        exclusion_reasons=exclusion_reasons,
        jurisdiction=jurisdiction,
        authority_level=authority_level,
        freshness_state="unknown",   # TODO: implement freshness check in full RAG phase
        licence_state="permitted",   # MVP assumption; enforce per-source in production
        confidence_state=confidence_state,
    )
