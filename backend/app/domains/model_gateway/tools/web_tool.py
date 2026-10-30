"""search_web — trusted-site web search, as a tool the agent calls when it
needs it (ZL-ENG-AGT-01 §02: fetch only what the question needs, instead of
pre-fetching the web for every question).

Uses the same search as the pre-fetch path (websearch.web_search_each):
results are filtered to the authoritative accounting/tax/audit domains for
the jurisdiction, snippets only, and every result becomes a citable source.
Results are public pages; nothing tenant-specific is sent or returned.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domains.identity.permissions import KRITON_TOOL_ROLES
from app.domains.model_gateway.tool_registry import ToolResult, ToolSpec
from app.orchestration.websearch import web_search_each

TOOL_NAME = "search_web"
_MAX_SNIPPET = 3000


class SearchWebArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=3, max_length=300,
                       description="What to look up, as a specific question, e.g. 'UK VAT registration threshold 2026'.")
    jurisdiction: str = Field(default="", max_length=60,
                              description="Country the answer must apply to, e.g. 'United Kingdom'. Empty for the question's own.")


async def _handle(args: SearchWebArgs) -> ToolResult:
    sources = await web_search_each(args.query, jurisdiction=args.jurisdiction, limit=5)
    if not sources:
        from app.orchestration.websearch import retrieval_failure_note
        issue = retrieval_failure_note()
        if issue:
            return ToolResult.failure("retrieval_unavailable", issue + " Do not present external rules as verified. "
                                      "Optional workflow suggestions may still be given as labelled general practice.")
        return ToolResult.failure("no_data", "No trusted source was found for this search. Do not answer from memory; "
                                             "say which external facts remain unverified. Optional workflow suggestions "
                                             "may still be given as labelled general practice.")
    from app.orchestration.websearch import _focused_excerpt
    # The registry caps the complete result. Share its budget before that
    # cap so later subjects do not disappear behind the first long source.
    from app.domains.model_gateway.tool_registry import MAX_RESULT_CHARS
    headers = [f"{source.title}\nURL: {source.url}\n" for source in sources]
    allowance = min(_MAX_SNIPPET, max(0, (MAX_RESULT_CHARS - 100 - sum(map(len, headers))) // len(sources)))
    lines = [header + _focused_excerpt(source.snippet or '', args.query, allowance)
             for header, source in zip(headers, sources)]
    return ToolResult(ok=True, content="Trusted search results:\n\n" + "\n\n".join(lines), sources=tuple(sources))


SEARCH_WEB_TOOL = ToolSpec(
    name=TOOL_NAME,
    version="1.0",
    description=(
        "Search authoritative accounting, tax and regulator websites for rules, thresholds, deadlines and "
        "guidance not in the governed knowledge base. Returns cited snippets. Use search_knowledge_base first "
        "for UK and Indian tax rules; use this for anything else or when the knowledge base has nothing."
    ),
    args_model=SearchWebArgs,
    handler=_handle,
    data_source="Trusted-domain web search (Tavily / SearXNG), filtered per jurisdiction",
    risk_level="low",
    timeout_seconds=30.0,
    allowed_roles=KRITON_TOOL_ROLES,
    tenant_scope="public",
    owner="Kriton / AI-ML",
)
