"""search_knowledge_base — the governed source library, as an agent tool.

The question's governed passages are retrieved once before the agent starts.
This tool lets the agent search again for a sub-question that evidence does
not cover, through the same governed path (orchestration/governed_retrieval):
rights-filtered hybrid retrieval, the licence gate, a frozen and persisted
SourceBundle, and hash-verified passage text. Display rights carry through:
"internal_reasoning_only" passages are never returned (they could surface as
citations), and "summarise" passages are citable but never previewed verbatim.
"""
from __future__ import annotations

import asyncio
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domains.model_gateway.tool_registry import ToolResult, ToolSpec
from app.orchestration.websearch import WebSource

TOOL_NAME = "search_knowledge_base"
_MAX_PASSAGE_CHARS = 1500


class KnowledgeBaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=3, max_length=300, description="The specific point to look up, as a question.")
    jurisdiction: str = Field(
        default="", max_length=60,
        description="Country the rule must apply to, e.g. 'United Kingdom' or 'India'. Leave empty to use the question's.",
    )
    as_of: date | None = Field(default=None, description="Date the rule must be in force on (YYYY-MM-DD). Leave empty for today.")


async def _handle(args: KnowledgeBaseArgs) -> ToolResult:
    from app.core.database import restore_request_identity
    from app.orchestration.governed_retrieval import current_context, retrieve_governed_evidence

    context = current_context()
    if context is None:
        return ToolResult.failure("no_data", "The knowledge base is not available for this request. Do not answer from memory.")
    async with context.lock:
        try:
            bundle, passages = await retrieve_governed_evidence(
                context.db, query=args.query, tenant_id=context.tenant_id, query_id=context.query_id,
                jurisdiction=args.jurisdiction or context.jurisdiction, framework=context.framework,
                effective_date=args.as_of or context.effective_date, top_k=5,
            )
        except asyncio.CancelledError:
            # A timeout cancels mid-query; the connection may be replaced by a
            # pooled one carrying another request's identity (see get_db).
            await context.db.rollback()
            await restore_request_identity(context.db, tenant_id=context.tenant_id, user_id=context.user_id)
            raise
        except Exception:
            await context.db.rollback()
            await restore_request_identity(context.db, tenant_id=context.tenant_id, user_id=context.user_id)
            raise

    sources_by_id = {source.id: source for source in bundle.sources}
    selection = {passage.passage_id: passage for passage in bundle.passages}
    results: list[WebSource] = []
    lines: list[str] = []
    for passage_id, locator, content in passages:
        source = sources_by_id[selection[passage_id].source_id]
        display = bundle.source_display_states.get(source.id, "internal_reasoning_only")
        if display == "internal_reasoning_only":
            continue
        effective = f", in force from {source.effective_from}" if source.effective_from else ""
        results.append(WebSource(
            title=f"{source.title} — {locator}",
            url=source.source_url or locator,
            snippet=content[:_MAX_PASSAGE_CHARS],
            provider="Governed source register",
            freshness="registered_version",
            source_id=passage_id,
            preview_allowed=display == "show",
        ))
        lines.append(f"[{len(results)}] {source.title} — {locator}{effective}:\n{content[:_MAX_PASSAGE_CHARS]}")
    if not results:
        return ToolResult.failure(
            "no_data",
            f"No governed passage covers this ({bundle.confidence_state} evidence). "
            "Say the sources do not state it; do not answer from memory.",
        )
    return ToolResult(
        ok=True,
        content="Governed knowledge-base passages (cite them; quote figures exactly):\n\n" + "\n\n".join(lines),
        sources=tuple(results),
    )


KNOWLEDGE_BASE_TOOL = ToolSpec(
    name=TOOL_NAME,
    version="1.0",
    description=(
        "Search the firm's governed knowledge base — approved official guidance registered "
        "with licence and version checks (for example UK VAT notices and GOV.UK guidance) — "
        "for passages on one specific point. Use it when the evidence already provided does "
        "not cover a part of the question. Prefer it to memory for any rule, rate, threshold "
        "or deadline it may cover."
    ),
    args_model=KnowledgeBaseArgs,
    handler=_handle,
    data_source="Governed source register (licence-checked, versioned passages)",
    risk_level="low",
    # Measured against the Tokyo-hosted database from India: ~0.56s per round
    # trip and ~20s for the full governed path (retrieval, licence gate,
    # persisted manifest, verified text); a second fanned-out search waits on
    # the lock. Co-located, the same path takes well under a second.
    timeout_seconds=45.0,
)
