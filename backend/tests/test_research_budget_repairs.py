"""Regressions for repeated research results and missing comparison topics."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import time

from app.domains.model_gateway.agent_budget import GenerationBudget
from app.domains.model_gateway.research_context import MessageSection, pack_messages, render_sources
from app.orchestration.official_standards import standards_for
from app.orchestration.verification_service import is_evidence_gap_statement
from app.orchestration.websearch import WebSource


def research_messages():
    messages = [{"role": "user", "content": "Prepare an audit plan. Supplied exposure: GBP 123456."}]
    sections = []
    for batch in range(3):
        refs = [(f"REF-{batch * 12 + n + 1}", WebSource(
            title=f"Official audit guidance {n}", url=f"https://example.test/{batch}/{n}",
            snippet="Audit correspondence and supporting documents must be retained. " * 1000,
        )) for n in range(12)]
        text = render_sources(refs, "audit documents", char_budget=100000)
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call-{batch}", "type": "function", "function": {"name": "search_web", "arguments": "{}"}}]})
        messages.append({"role": "tool", "tool_call_id": f"call-{batch}", "content": text})
        sections.append(MessageSection(len(messages) - 1, 0, len(text),
                                       lambda factor, refs=refs: render_sources(refs, "audit documents", factor=factor)))
    messages.append({"role": "tool", "tool_call_id": "calculation", "content": "Verified calculation: 123456 * 0.2 = 24691.2"})
    return messages, sections


def test_three_searches_with_thirty_six_sources_fit_without_changing_protocol_or_figures():
    messages, sections = research_messages()
    packed, before, after = pack_messages(messages, None, sections, 10667)
    assert before > 16000 and after <= 10667
    assert packed[0] == messages[0] and packed[-1] == messages[-1]
    for index in (1, 3, 5):
        assert packed[index] == messages[index]
        assert packed[index + 1]["tool_call_id"] == messages[index + 1]["tool_call_id"]
    joined = " ".join(message.get("content") or "" for message in packed)
    assert all(f"[REF-{n}]" in joined for n in range(1, 37))
    assert "Omitted material is not available evidence" in joined
    assert len(messages[2]["content"]) > len(packed[2]["content"])


async def test_budget_compacts_before_provider_call_and_removes_internal_metadata():
    messages, sections = research_messages()
    create = AsyncMock(return_value=SimpleNamespace(usage=SimpleNamespace(total_tokens=100)))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    budget = GenerationBudget(max_total_tokens=128000, max_request_tokens=16000, max_completion_tokens=8192)
    await budget.create(client, seconds=5, model="test", messages=messages, _context_sections=sections)
    sent = create.call_args.kwargs
    assert "_context_sections" not in sent
    assert sent["max_completion_tokens"] >= 5000
    assert sent["messages"][0] == messages[0]


def test_comparison_fetches_all_three_standards_and_avoids_wrong_impairment_framework():
    assert set(standards_for("Compare leases, impairment, and provisions under IFRS.")) == {
        ("IFRS", "16"), ("IAS", "36"), ("IAS", "37")}
    assert len(standards_for("Compare IAS 2, IAS 36, IAS 37 and IFRS 16.")) == 4
    assert ("IAS", "36") not in standards_for("Explain impairment of financial assets under IFRS.")


def test_explicit_gap_does_not_require_a_citation_but_cannot_smuggle_a_rate():
    assert is_evidence_gap_statement("The evidence does not detail what tax-authority audit teams concentrate on.")
    assert not is_evidence_gap_statement("The evidence does not detail the withholding tax rate of 15%.")


async def test_failed_standard_download_does_not_hide_a_recovered_publisher_for_a_day(monkeypatch):
    from app.orchestration import official_standards as standards
    monkeypatch.setattr(standards, "_standard_cache", {"ias36": (time.monotonic() - 31, "")})
    download = AsyncMock(return_value="Recovered official standard text")
    monkeypatch.setattr(standards, "_download_standard", download)
    assert await standards._official_standard_text("ias36") == "Recovered official standard text"
    download.assert_awaited_once()


async def test_prepared_plan_is_reused_only_inside_its_search_task(monkeypatch):
    from app.orchestration import evidence_planning as planning
    plan = planning.EvidenceSearchPlan([], method="semantic")
    monkeypatch.setenv("EVIDENCE_PLANNING", "off")
    async def read():
        await asyncio.sleep(0)
        return await planning.plan_evidence_search("request", ["fallback"])
    task = planning.create_prepared_search_task(read(), "request", plan)
    assert await task is plan
    assert (await read()).method == "fallback"


async def test_standard_purpose_survives_comparison_cross_references(monkeypatch):
    from app.orchestration import official_standards as standards
    text = ("Objective\n1 | This Standard sets out principles for recognition and measurement of leases.\n"
            "2 | A lessee shall consider the terms and conditions of contracts.\n"
            "77 | A lessor shall apply impairment requirements of other standards.\n")
    monkeypatch.setattr(standards, '_official_standard_text', AsyncMock(return_value=text))
    sources = await standards.official_standard_excerpts('Compare leases, impairment, and provisions: explain the purpose of each.')
    assert 'This Standard sets out principles for recognition and measurement of leases.' in sources[0].snippet
    assert len(sources[0].snippet) <= 3000


async def test_slow_backup_retry_keeps_the_sources_already_found(monkeypatch):
    from app.orchestration import websearch as search
    monkeypatch.setattr(search, '_cache_get', AsyncMock(return_value=None))
    monkeypatch.setattr(search, '_tavily_results', AsyncMock(return_value=None))
    monkeypatch.setattr(search, '_SEARCH_BUDGET_SECONDS', .05)
    monkeypatch.setattr(search, '_strict_allowlist', lambda: False)
    monkeypatch.setattr(search, '_is_relevant', lambda *args: True)
    calls = 0
    async def results(*args):
        nonlocal calls
        calls += 1
        if calls > 1:
            await asyncio.sleep(5)
        return [{'url': 'https://example.test/audit', 'title': 'Audit preparation', 'content': 'Tax audit preparation guidance.'}]
    monkeypatch.setattr(search, '_searxng_results', results)
    found = await asyncio.wait_for(search.web_search('How to prepare for a multinational tax audit?', read_pages=0), .5)
    assert calls > 1 and found[0].url == 'https://example.test/audit'
