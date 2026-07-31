"""Retrieval strategy planner for the Massarius evidence pipeline."""
from __future__ import annotations

import uuid

from app.orchestration.schemas import RetrievalPlan


def create_retrieval_plan(
    query: str,
    jurisdiction: str,
    *,
    embeddings_enabled: bool,
    requires_current_sources: bool | None = None,
) -> RetrievalPlan:
    """Declare retrieval intent without reading sources or applying policy."""
    lowered = query.lower()
    requires_current = (
        requires_current_sources
        if requires_current_sources is not None
        else any(term in lowered for term in ("current", "today", "latest", "rate", "2026"))
    )
    methods = ["keyword"]
    strategy = "keyword"
    if embeddings_enabled:
        methods.append("vector")
        strategy = "hybrid"
    return RetrievalPlan(
        retrieval_plan_id=f"rp-{uuid.uuid4().hex[:12]}",
        strategy=strategy,
        methods=methods,
        jurisdiction=jurisdiction,
        requires_current_sources=requires_current,
    )
