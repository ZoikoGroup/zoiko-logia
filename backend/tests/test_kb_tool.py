"""The agent's knowledge-base tool reuses governed retrieval and its display rights."""
from types import SimpleNamespace

import pytest

from app.domains.model_gateway.tools import kb_tool
from app.orchestration import governed_retrieval
from app.orchestration.governed_retrieval import GovernedRetrievalContext, bind_context, reset_context


def _bundle(states):
    sources = [SimpleNamespace(id=f"s{i}", title=f"Notice {i}", source_url=f"https://www.gov.uk/n{i}", effective_from=None)
               for i in range(len(states))]
    passages = [SimpleNamespace(passage_id=f"p{i}", source_id=f"s{i}") for i in range(len(states))]
    return SimpleNamespace(sources=sources, passages=passages, confidence_state="sufficient",
                           source_display_states={f"s{i}": state for i, state in enumerate(states)})


async def test_without_a_request_context_the_tool_refuses_rather_than_guessing():
    result = await kb_tool._handle(kb_tool.KnowledgeBaseArgs(query="UK VAT threshold?"))
    assert not result.ok and result.error_code == "no_data" and "memory" in result.content


async def test_display_rights_carry_through_to_sources(monkeypatch):
    calls = {}

    async def fake_retrieve(db, **kwargs):
        calls.update(kwargs)
        return _bundle(["show", "summarise", "internal_reasoning_only"]), [
            ("p0", "§1", "Threshold is £90,000."), ("p1", "§2", "Summary-only text."), ("p2", "§3", "Internal only."),
        ]

    monkeypatch.setattr(governed_retrieval, "retrieve_governed_evidence", fake_retrieve)
    token = bind_context(GovernedRetrievalContext(db=object(), tenant_id="t1", user_id="u1", query_id="q1",
                                                  jurisdiction="United Kingdom"))
    try:
        result = await kb_tool._handle(kb_tool.KnowledgeBaseArgs(query="When must I register for VAT?"))
    finally:
        reset_context(token)
    assert result.ok
    # Same governed path, scoped to the request's tenant, query and jurisdiction.
    assert calls["tenant_id"] == "t1" and calls["query_id"] == "q1" and calls["jurisdiction"] == "United Kingdom"
    assert [s.source_id for s in result.sources] == ["p0", "p1"]          # internal-only never returned
    assert [s.preview_allowed for s in result.sources] == [True, False]   # summarise: citable, no verbatim preview
    assert "Internal only." not in result.content


async def test_no_governed_passage_is_reported_as_a_gap(monkeypatch):
    async def fake_retrieve(db, **kwargs):
        return _bundle([]), []

    monkeypatch.setattr(governed_retrieval, "retrieve_governed_evidence", fake_retrieve)
    token = bind_context(GovernedRetrievalContext(db=object(), tenant_id="t1", user_id="u1", query_id="q1"))
    try:
        result = await kb_tool._handle(kb_tool.KnowledgeBaseArgs(query="UK corporation tax rate?"))
    finally:
        reset_context(token)
    assert not result.ok and result.error_code == "no_data"
