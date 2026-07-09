"""
Retrieve step: build a lightweight source bundle from the real source_library
register. This is a proportionate stand-in for the full RAG pipeline (vector
search, reranking, citation anchors) described in the ZL-T0-03 RAG wireframe —
that domain (backend/app/domains/rag/) is still unbuilt. What's here is real:
it queries actual approved sources and its confidence_state genuinely drives
the safety classification, it just doesn't do semantic ranking yet.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.source_library.service import list_sources
from app.orchestration.schemas import SourceBundle, SourceSummary

_CATEGORY_KEYWORDS = {
    "tax": ["tax"],
    "audit": ["audit", "going concern"],
    "payroll-compliance": ["payroll", "employment"],
    "internal-policies": ["internal policy", "firm policy"],
    "education-content": ["exam", "study", "cpd", "syllabus"],
}
_DEFAULT_CATEGORY = "standards"

# Seed data uses "ACTIVE" for pre-approved reference sources; the live
# approve_source_version() workflow produces "APPROVED". The frontend
# already treats both as usable (see STATUS_TONE in source-library/page.tsx),
# so eligibility here matches that same existing vocabulary.
_ELIGIBLE_STATUSES = {"ACTIVE", "APPROVED"}


def infer_category(query: str) -> str:
    lowered = query.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return _DEFAULT_CATEGORY


async def build_source_bundle(db: AsyncSession, *, query: str, jurisdiction: str) -> SourceBundle:
    category = infer_category(query)
    candidates = await list_sources(db, category)

    eligible = [
        c
        for c in candidates
        if c["latest_version"].status in _ELIGIBLE_STATUSES
        and (not jurisdiction or c["jurisdiction_scope"] in ("Global", jurisdiction))
    ]

    if not eligible:
        confidence_state = "NO_ELIGIBLE_SOURCE"
    elif len(eligible) == 1:
        confidence_state = "LOW_CONFIDENCE"
    else:
        confidence_state = "HIGH_CONFIDENCE"

    return SourceBundle(
        bundle_id=f"bnd-{uuid.uuid4().hex[:12]}",
        retrieval_run_id=f"ret-{uuid.uuid4().hex[:12]}",
        category=category,
        confidence_state=confidence_state,
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
    )
