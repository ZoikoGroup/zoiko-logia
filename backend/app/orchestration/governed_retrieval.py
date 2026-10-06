"""Governed knowledge-base retrieval as one reusable step.

The same sequence ask_kriton runs before composition — retrieve.py's
rights-filtered hybrid search, the licence gate (Checkpoints A/B),
bundle_builder's frozen SourceBundle, its persisted manifest, source-usage
records and hash-verified passage text — packaged so the agent's
search_knowledge_base tool reaches the governed library through exactly the
same controls. No retrieval logic lives here; it only composes the existing
steps.

The agent runs tools concurrently and the request has one database session,
so the tool reaches the session through a request-scoped context whose lock
serialises knowledge-base searches.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.massarius import bundle_builder, license_gate
from app.domains.source_library.service import record_source_usages
from app.orchestration.retrieve import build_source_bundle
from app.orchestration.schemas import SourceBundle


@dataclass
class GovernedRetrievalContext:
    db: AsyncSession
    tenant_id: str
    user_id: str
    query_id: str
    jurisdiction: str = ""
    framework: str = ""
    effective_date: date | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_context: ContextVar[GovernedRetrievalContext | None] = ContextVar("governed_retrieval_context", default=None)


def current_context() -> GovernedRetrievalContext | None:
    return _context.get()


def bind_context(context: GovernedRetrievalContext):
    """Make the request's governed retrieval available to agent tools; returns
    the token for reset_context()."""
    return _context.set(context)


def reset_context(token) -> None:
    _context.reset(token)


async def retrieve_governed_evidence(
    db: AsyncSession,
    *,
    query: str,
    tenant_id: str,
    query_id: str,
    jurisdiction: str = "",
    framework: str = "",
    effective_date: date | None = None,
    top_k: int = 8,
) -> tuple[SourceBundle, list[tuple[str, str, str]]]:
    """The frozen, persisted SourceBundle and its verified passage text
    (passage_id, locator, content), in rank order."""
    preliminary = await build_source_bundle(
        db, query=query, jurisdiction=jurisdiction, tenant_id=tenant_id,
        framework=framework, effective_date=effective_date, top_k=top_k,
    )
    licence = await license_gate.check_eligibility(
        db, preliminary.sources, tenant_id=tenant_id, jurisdiction=preliminary.jurisdiction,
        framework=framework, effective_date=effective_date,
    )
    bundle = bundle_builder.build_bundle(preliminary, licence)
    # Persisted under the request's query_id, so a reviewer replaying the
    # case sees the passages the agent searched as well as the initial ones.
    await bundle_builder.persist_bundle(db, bundle=bundle, tenant_id=tenant_id, query_id=query_id)
    await record_source_usages(
        db, sources=bundle.sources, tenant_id=tenant_id, artifact_type="source_bundle",
        artifact_id=bundle.source_bundle_id, operation="model_transmission",
    )
    return bundle, await bundle_builder.load_bundle_passage_text(db, bundle)
