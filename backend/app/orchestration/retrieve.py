"""Rights-filtered lexical passage retrieval and evidence planning.

Source/version eligibility is resolved before passage content is loaded. Denied
text therefore never enters ranking or model context.
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from datetime import date

from sqlalchemy import bindparam, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.source_library.embeddings import embed_query, vector_literal

from app.domains.source_library.licensing import SourceUseContext, can_use_many
from app.domains.source_library.models import Source, SourcePassage, SourceRelationship, SourceVersion
from app.orchestration.dbnomics import countries_in_query
from app.orchestration.procedures import is_other_procedure
from app.orchestration.ranking import bm25, rerank, diversify
from app.orchestration.schemas import (
    EvidencePassage, ExcludedEvidence, RetrievalPlan, SourceBundle, SourceSummary,
)
from app.orchestration.routing_matrix import (
    CONF_CONFLICTING, CONF_INSUFFICIENT, CONF_LIMITED, CONF_RESTRICTED, CONF_SUFFICIENT,
)

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    # "vat"/"gst"/"hmrc": "Who can sign off a VAT return?" names no "tax", fell
    # to the default "standards" category and never reached the VAT sources.
    "tax": ["tax", "vat", "gst", "hmrc", "cbic"],
    "audit": ["audit", "going concern"],
    "payroll-compliance": ["payroll", "employment"],
    "internal-policies": ["internal policy", "firm policy"],
    "education-content": ["exam", "study", "cpd", "syllabus"],
}
_DEFAULT_CATEGORY = "standards"

# Word-boundary patterns, built from _CATEGORY_KEYWORDS above — plain substring
# matching let "employment" match inside "unemployment", so e.g. "UK
# unemployment" was miscategorized as payroll-compliance instead of falling
# through to the general "standards" category, which could starve it of
# eligible governed sources and wrongly force a clarification route.
_CATEGORY_KEYWORD_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    category: [re.compile(rf"\b{re.escape(keyword)}\b") for keyword in keywords]
    for category, keywords in _CATEGORY_KEYWORDS.items()
}

INDEX_VERSION = "source-passages-lexical-v1"
HYBRID_INDEX_VERSION = "source-passages-hybrid-bm25-rerank-v2"
# Reciprocal-rank fusion constant: the standard 60 keeps either list from
# dominating on its top few ranks.
_RRF_K = 60
# When embeddings are available, semantic similarity decides WHETHER a
# passage is relevant; keyword overlap only helps rank the relevant ones.
# Measured on the UK VAT corpus with bge-small: the best passage for six VAT
# questions scored 0.73-0.87, while off-topic questions (IFRS 16, accruals,
# UK corporation tax, Indian income tax) peaked at 0.60-0.695. Keyword
# overlap could not separate them: "What is the UK corporation tax rate?"
# scored 0.67 against VAT passages on shared "tax", "rate", "UK".
# 0.72 not 0.71: a plain currency conversion ("Convert 5,000 USD to INR")
# matched VAT Notice 700 §7.6 "Values expressed in a foreign currency" at
# 0.712. The lowest correct VAT match measured is 0.729.
_SEMANTIC_MIN = float(os.getenv("SEMANTIC_RETRIEVAL_MIN_SIMILARITY", "0.72"))
_SEMANTIC_CANDIDATES = 40
# Keyword-only retrieval (no embeddings): the passage must cover at least
# half the question's terms — one shared word ("VAT", "business") is not
# relevance.
_LEXICAL_ONLY_MIN = 0.5
_PER_VERSION_CAP = 3
# Sources with these statuses are eligible for retrieval
_ELIGIBLE_STATUSES = {"ACTIVE", "APPROVED"}
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]+", re.I)
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "the", "this", "to",
    "what", "when", "which", "with",
}


# Exclusions that mean "not applicable or not yet set up", not "forbidden":
# lifecycle, context mismatch, tenant boundary and rights that are unknown,
# not yet valid or lapsed. Anything else (an explicit rights denial and its
# custom reason codes) is a real restriction.
_NOT_RESTRICTIVE_REASONS = frozenset({
    "UNKNOWN_OPERATION", "SOURCE_VERSION_NOT_FOUND", "TENANT_PRIVATE_BOUNDARY",
    "SOURCE_REVOKED", "SOURCE_SUPERSEDED", "VERSION_NOT_APPROVED",
    "JURISDICTION_MISMATCH", "FRAMEWORK_MISMATCH", "NOT_YET_EFFECTIVE", "SOURCE_EXPIRED",
    "RIGHT_UNKNOWN", "RIGHT_NOT_YET_VALID", "RIGHT_EXPIRED",
})
def _retrieval_timeout_seconds() -> float:
    """Bound remote governed-source reads below the frontend request limit.

    Retrieval is useful grounding, but it already has a defined insufficient-
    evidence fallback.  A slow database must therefore fail soft instead of
    preventing an otherwise valid live-data/LLM answer from returning at all.
    """
    try:
        return max(1.0, float(os.getenv("SOURCE_RETRIEVAL_TIMEOUT_SECONDS", "20")))
    except ValueError:
        return 20.0


# Cues that tie a question to one tax jurisdiction when it names no country.
# "VAT" alone and "GST" alone are ambiguous worldwide (UAE VAT, Australian
# GST); among the jurisdictions in the knowledge base they mean the UK and
# India respectively, and a question naming any other country is matched to
# that country, so neither corpus is offered for it.
_UK_CUES = re.compile(r"£|\b(?:hmrc|gov\.uk|making tax digital)\b", re.I)
_INDIA_CUES = re.compile(r"₹|\b(?:cgst|sgst|igst|utgst|cbic|gstin|gst council|lakh|crore)\b", re.I)
# VAT/GST jurisdictions the country detector does not list. Naming one rules
# out both corpora rather than letting "VAT" alone mean the UK.
_OTHER_TAX_JURISDICTIONS = re.compile(
    r"\b(?:uae|u\.a\.e\.|emirates|dubai|abu dhabi|saudi|ksa|bahrain|oman|qatar|kuwait|"
    r"eu|european union|europe|singapore|new zealand|malaysia|philippines|thailand|vietnam|"
    r"indonesia|nigeria|kenya|egypt|turkey|switzerland|norway|mexico|brazil)\b",
    re.I,
)
_VAT = re.compile(r"\bvat\b", re.I)
_GST = re.compile(r"\bgst\b", re.I)


def infer_jurisdiction(query: str) -> str:
    """The one jurisdiction a question is about, or "" when it names none or
    several. Used only when the request carries no explicit jurisdiction, so a
    UK VAT question is never answered from Indian GST guidance (or the
    reverse) because the two read alike."""
    named = set(countries_in_query(query))
    if _UK_CUES.search(query):
        named.add("United Kingdom")
    if _INDIA_CUES.search(query):
        named.add("India")
    if other := _OTHER_TAX_JURISDICTIONS.search(query):
        named.add(other.group(0).title())
    if len(named) == 1:
        return named.pop()
    if named:
        return ""
    vat, gst = bool(_VAT.search(query)), bool(_GST.search(query))
    if vat != gst:
        return "United Kingdom" if vat else "India"
    return ""


def infer_category(query: str) -> str:
    lowered = query.lower()
    for category, patterns in _CATEGORY_KEYWORD_PATTERNS.items():
        if any(pattern.search(lowered) for pattern in patterns):
            return category
    return _DEFAULT_CATEGORY


def _normalise_numbers(value: str) -> str:
    """"56th" -> "56", "22nd" -> "22", "7,500" -> "7500", for keyword matching
    only. "From what date do the rates recommended at the 56th GST Council
    meeting apply?" missed the FAQ that says "in its 56 meeting … effective
    from 22nd September, 2025" by one token (coverage 0.70 < 0.75)."""
    value = re.sub(r"(?<=\d),(?=\d{2,3}\b)", "", value)
    return re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", r"\1", value, flags=re.I)


def _tokens(value: str) -> set[str]:
    return {
        token.casefold() for token in _TOKEN_RE.findall(_normalise_numbers(value))
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


def build_retrieval_plan(
    *, jurisdiction: str, framework: str, top_k: int = 8, semantic: bool = False,
) -> RetrievalPlan:
    return RetrievalPlan(
        retrieval_plan_id=f"rp-{uuid.uuid4().hex[:12]}",
        strategy="rights_filtered_hybrid_passages" if semantic else "rights_filtered_lexical_passages",
        methods=["keyword", "vector"] if semantic else ["keyword"],
        jurisdiction=jurisdiction,
        framework=framework,
        requires_current_sources=True,
        top_k=top_k,
        index_version=HYBRID_INDEX_VERSION if semantic else INDEX_VERSION,
        risk_notes=[] if semantic else [
            "Semantic retrieval unavailable (no embeddings or no vector index); keyword only."
        ],
    )


async def _semantic_scores(db: AsyncSession, query: str, version_ids: list[str]) -> dict[str, float]:
    """Cosine similarity of the closest passages in the eligible versions
    (pgvector). Empty on SQLite, without embeddings, or on any failure: the
    semantic half is an addition to keyword retrieval, never a dependency."""
    if not version_ids or db.get_bind().dialect.name != "postgresql":
        return {}
    vector = await embed_query(query)
    if vector is None:
        return {}
    statement = text(
        "SELECT id, 1 - (embedding <=> CAST(:vector AS vector)) AS similarity "
        "FROM source_passages "
        "WHERE source_version_id IN :version_ids AND embedding IS NOT NULL "
        "ORDER BY embedding <=> CAST(:vector AS vector) LIMIT :limit"
    ).bindparams(bindparam("version_ids", expanding=True))
    # A savepoint, so a failed vector query rolls back only itself: a full
    # rollback would discard the request's earlier uncommitted audit writes.
    try:
        async with db.begin_nested():
            rows = (await db.execute(statement, {
                "vector": vector_literal(vector), "version_ids": version_ids, "limit": _SEMANTIC_CANDIDATES,
            })).all()
    except Exception:  # noqa: BLE001 — e.g. the vector column not migrated yet
        return {}
    return {row.id: float(row.similarity) for row in rows}


async def _candidate_versions(
    db: AsyncSession, *, tenant_id: str, category: str | None = None,
) -> list[tuple[Source, SourceVersion]]:
    """Load candidate metadata only, choosing the newest approved version."""
    result = await db.execute(
        select(Source, SourceVersion)
        .join(SourceVersion, SourceVersion.source_id == Source.id)
        .where(
            SourceVersion.status.in_(_ELIGIBLE_STATUSES),
            or_(Source.is_tenant_private.is_(False), Source.tenant_id == tenant_id),
            *([Source.category == category] if category else []),
        )
        .order_by(Source.id, SourceVersion.created_at.desc())
    )
    # Keep versions until applicability is checked. Taking the newest here
    # would hide a historical version needed for an explicit as-of date.
    return list(result.all())



async def build_source_bundle(
    db: AsyncSession,
    *,
    query: str,
    jurisdiction: str,
    tenant_id: str,
    framework: str = "",
    effective_date: date | None = None,
    top_k: int = 8,
    _all_categories: bool = False,
) -> SourceBundle:
    """Execute a bounded, context-aware hybrid (keyword + semantic) passage search.

    With no explicit jurisdiction, sources are scoped to the jurisdiction the
    question itself implies (infer_jurisdiction).

    Sources are first narrowed to the category inferred from the question;
    when that yields no relevant passage the search is repeated across every
    category ("What flat rate percentage does a limited cost trader use?"
    names no VAT and was routed away from the VAT guidance)."""
    context = SourceUseContext(
        tenant_id=tenant_id, jurisdiction=jurisdiction or infer_jurisdiction(query),
        framework=framework, effective_date=effective_date or date.today(),
    )

    query_tokens = _tokens(query)
    category = infer_category(query)
    eligible_rows: list[tuple[Source, SourceVersion]] = []
    excluded: list[ExcludedEvidence] = []
    # Whether a source RELEVANT to this question was explicitly denied — the
    # only exclusion that means "the evidence exists but may not be used".
    relevant_source_denied = False
    async with asyncio.timeout(_retrieval_timeout_seconds()):
        candidates = await _candidate_versions(
            db, tenant_id=tenant_id, category=None if _all_categories else category,
        )
    decisions = await can_use_many(db, [version.id for _, version in candidates], context, "retrieval")
    selected_source_ids: set[str] = set()
    for source, version in candidates:
        decision = decisions[version.id]
        if decision.allowed:
            if source.id not in selected_source_ids:
                eligible_rows.append((source, version))
                selected_source_ids.add(source.id)
        else:
            excluded.append(ExcludedEvidence(
                source_id=source.id, source_version_id=version.id,
                reason_code=decision.reason_code,
            ))
            # Relevance from the title (metadata) only: an ineligible
            # source's text is never read.
            if (decision.reason_code not in _NOT_RESTRICTIVE_REASONS
                    and _lexical_score(query_tokens, source.title or "") > 0):
                relevant_source_denied = True

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
    # Evidence about a different procedure on the same tax (a VAT refund
    # passage for a VAT-return question) is filtered, not out-ranked: keyword
    # and semantic scores alike rate the two as close.
    passages = [passage for passage in passages if not is_other_procedure(passage.procedure, query)]
    by_id = {passage.id: passage for passage in passages}
    lexical = {
        passage.id: score for passage in passages
        if (score := _lexical_score(query_tokens, f"{passage.heading} {passage.content}")) > 0
    }
    semantic = {
        passage_id: similarity
        for passage_id, similarity in (await _semantic_scores(db, query, version_ids)).items()
        if passage_id in by_id
    }
    plan = build_retrieval_plan(
        jurisdiction=context.jurisdiction, framework=framework, top_k=top_k, semantic=bool(semantic),
    )
    # Reciprocal-rank fusion. A passage with no keyword overlap qualifies only
    # when it is semantically close. Unselected passages are not recorded as
    # exclusions: one row per non-matching passage per question would grow
    # with the library on every request, and relevance is not a rights
    # decision.
    keyword_scores = bm25(query_tokens, {
        p.id: [token.casefold() for token in _TOKEN_RE.findall(_normalise_numbers(f"{p.heading} {p.content}"))
               if token.casefold() not in _STOP_WORDS] for p in passages
    })
    lexical_rank = {pid: rank for rank, pid in enumerate(sorted(keyword_scores, key=lambda p: (-keyword_scores[p], p)), start=1)}
    semantic_rank = {pid: rank for rank, pid in enumerate(sorted(semantic, key=lambda p: -semantic[p]), start=1)}
    if semantic:
        candidates = {pid for pid, similarity in semantic.items() if similarity >= _SEMANTIC_MIN}
        # Strong keyword matches remain eligible even when embedding wording
        # differs. Semantic search must not erase rare exact identifiers.
        candidates |= {pid for pid, coverage in lexical.items() if coverage >= 0.75}
    else:
        candidates = {pid for pid, score in lexical.items() if score >= _LEXICAL_ONLY_MIN}
    fused = {
        pid: sum(1 / (_RRF_K + ranks[pid]) for ranks in (lexical_rank, semantic_rank) if pid in ranks)
        for pid in candidates
    }
    # At most _PER_VERSION_CAP passages per document: VAT Notice 723A (refunds
    # for NON-UK businesses) filled six of eight slots for a question about UK
    # organisations not registered for VAT, crowding out the one page whose
    # passage names form VAT126.
    #
    # The cap only makes room for OTHER qualifying documents: slots it frees
    # that nothing else can fill go back to the capped document's next-best
    # passages. Without that backfill, a question only Notice 723A answers got
    # 3 passages instead of 8 and lost the one naming form VAT65A (ranked 5th).
    ordered = rerank(
        fused=fused, passages=by_id, sources=version_to_source,
        versions={version.id: version for _, version in eligible_rows},
        title_coverage={version.id: _lexical_score(query_tokens, source.title or "") for source, version in eligible_rows},
        as_of=context.effective_date or date.today(),
    )
    ranked = diversify(ordered, top_k=plan.top_k, per_version_cap=_PER_VERSION_CAP)
    if not ranked and not _all_categories:
        return await build_source_bundle(
            db, query=query, jurisdiction=jurisdiction, tenant_id=tenant_id, framework=framework,
            effective_date=effective_date, top_k=top_k, _all_categories=True,
        )

    selected_passages = [
        EvidencePassage(
            passage_id=passage.id,
            source_id=version_to_source[passage.source_version_id].id,
            source_version_id=passage.source_version_id,
            locator=passage.locator,
            content_hash=passage.content_hash,
            score=round(score, 6),
            rank=rank,
            method=(
                "hybrid" if passage.id in lexical and passage.id in semantic
                else "vector" if passage.id in semantic and passage.id not in lexical
                else "keyword"
            ),
        )
        for rank, (score, passage) in enumerate(ranked, start=1)
    ]
    selected_version_ids = {item.source_version_id for item in selected_passages}
    selected_sources = [
        SourceSummary(
            id=source.id, version_id=version.id, title=source.title,
            category=source.category, jurisdiction_scope=source.jurisdiction_scope,
            version_label=version.version_label, status=version.status,
            source_url=version.source_url, authority_level=source.authority_level,
            publisher=source.publisher, effective_from=version.effective_from, effective_to=version.effective_to,
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
        # Previously RESTRICTED whenever every library source was excluded for
        # any reason — e.g. all licence rights still unrecorded — which made
        # EVERY question, on any topic, route to refusal. Restricted now means
        # a relevant source was explicitly denied; otherwise the library just
        # has no usable evidence for this question.
        confidence = CONF_RESTRICTED if relevant_source_denied else CONF_INSUFFICIENT
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
        retrieval_method="hybrid_passages_v1" if semantic else "lexical_passages_v1",
        eligible_source_count=len(selected_sources),
        excluded_source_count=len(excluded),
        sources=selected_sources,
        exclusion_reasons=[
            f"{item.source_id}:{item.passage_id or item.source_version_id or ''}:{item.reason_code}"
            for item in excluded
        ],
        jurisdiction=context.jurisdiction,
        as_of=context.effective_date,
        authority_level=authority_level,
        freshness_state="current" if selected_passages else "unknown",
        licence_state="permitted" if selected_passages else "unknown",
        confidence_state=confidence,
        index_version=plan.index_version,
        retrieval_plan=plan,
        passages=selected_passages,
        excluded_evidence=excluded,
        conflict_version_ids=sorted(conflict_version_ids),
    )
