"""The intent planner runs in shadow mode only: it may log a proposal, but it
can never change an answer, a tool call, a permission, a source decision or a
safety decision, and a slow or failing planner is invisible to the request."""
import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome, ToolCallRecord
from app.orchestration import intent_planner, planner_shadow
from tests.test_answer_status_pipeline import pipeline  # noqa: F401 — full-pipeline fixture

CALC = "A product costs £84 and sells for £126. Calculate the gross profit, gross margin and markup."
RESEARCH = "Under IAS 2, how is inventory measured when net realisable value falls below cost?"
PLAN = intent_planner.TaskPlan(
    intent="calculation", sub_tasks=[intent_planner.SubTask(kind="calculation", text="margin", needs_evidence=False,
                                                        tools=["calculate"], missing_inputs=[])],
    tools=["calculate", "search_web"], needs_authoritative_evidence=False, standards=[],
    uses_conversation=False, missing_inputs=[], invalid_inputs=[], wants_visualization=False, confidence=0.9)


def comparable(response) -> dict:
    data = response.model_dump(mode="json")
    for key in ("query_id", "correlation_id", "audit_reference", "workflow_plan", "effective_context",
                "context_decision"):
        data.pop(key, None)
    return data


@pytest.fixture
def shadow(monkeypatch, tmp_path):
    log = tmp_path / "planner-shadow.jsonl"
    monkeypatch.setattr(planner_shadow, "_LOG_FILE", log)
    proposals = AsyncMock(return_value=intent_planner.PlanResult(PLAN.model_copy(deep=True), 120.0, tokens=900))
    monkeypatch.setattr(intent_planner, "propose_plan", proposals)

    async def drain():
        while planner_shadow._inflight:
            await asyncio.gather(*list(planner_shadow._inflight), return_exceptions=True)

    def records():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return type("Shadow", (), {"proposals": proposals, "drain": staticmethod(drain), "records": staticmethod(records)})


async def test_off_by_default_nothing_is_planned(pipeline, shadow, monkeypatch):
    monkeypatch.delenv("KRITON_PLANNER_SHADOW", raising=False)
    await pipeline.ask(CALC)
    await shadow.drain()
    shadow.proposals.assert_not_awaited()
    assert shadow.records() == []


@pytest.mark.parametrize("query, agent_answer", [
    (CALC, None),
    (RESEARCH, "Inventories are measured at the lower of cost and net realisable value."),
])
async def test_the_answer_is_identical_with_shadow_on(pipeline, shadow, monkeypatch, query, agent_answer):
    if agent_answer:
        pipeline.answers(AgentOutcome(text=agent_answer, tool_calls=[ToolCallRecord(1, "search_web", "h", True, None, 5, 1)]))
    monkeypatch.delenv("KRITON_PLANNER_SHADOW", raising=False)
    off, off_audit = await pipeline.ask(query)
    monkeypatch.setenv("KRITON_PLANNER_SHADOW", "true")
    on, on_audit = await pipeline.ask(query)
    await shadow.drain()
    assert comparable(on) == comparable(off) and on_audit == off_audit
    shadow.proposals.assert_awaited_once()
    [record] = shadow.records()
    assert record["route"] == on.route and record["planner_available"] is True


async def test_a_slow_planner_never_delays_the_answer(pipeline, shadow, monkeypatch):
    monkeypatch.setenv("KRITON_PLANNER_SHADOW", "true")

    async def slow(*args, **kwargs):
        await asyncio.sleep(3)
        return intent_planner.PlanResult(PLAN.model_copy(deep=True), 3000.0)
    shadow.proposals.side_effect = slow
    started = time.monotonic()
    response, _ = await pipeline.ask(CALC)
    assert time.monotonic() - started < 2.0 and response.outcome == "answered"
    await shadow.drain()
    assert shadow.records()[0]["planner_latency_ms"] == 3000


async def test_a_failing_planner_is_invisible(pipeline, shadow, monkeypatch):
    monkeypatch.setenv("KRITON_PLANNER_SHADOW", "true")
    shadow.proposals.side_effect = RuntimeError("provider down")
    response, audited = await pipeline.ask(CALC)
    await shadow.drain()
    assert response.outcome == audited.outcome == "answered"
    assert response.calculation.outputs[0].display_value == "£42.00"


async def test_a_refused_certification_request_is_never_sent_to_the_planner(pipeline, shadow, monkeypatch):
    monkeypatch.setenv("KRITON_PLANNER_SHADOW", "true")
    response, _ = await pipeline.ask("Certify that my company's tax return is legally compliant.")
    await shadow.drain()
    assert response.outcome == "refused"
    shadow.proposals.assert_not_awaited()


async def test_the_log_records_the_comparison_without_the_question(pipeline, shadow, monkeypatch):
    monkeypatch.setenv("KRITON_PLANNER_SHADOW", "true")
    pipeline.answers(AgentOutcome(text="Inventories are measured at the lower of cost and net realisable value.",
                                  tool_calls=[ToolCallRecord(1, "search_web", "h", True, None, 5, 1)]))
    await pipeline.ask(RESEARCH)
    await shadow.drain()
    [record] = shadow.records()
    text = json.dumps(record)
    assert "net realisable" not in text and "inventory" not in text.lower()
    assert record["query_fingerprint"] == intent_planner.query_fingerprint(RESEARCH)
    assert record["executed_tools"] == ["search_web"] and record["router_intent"] == "research_standard"
    assert record["intent_agreement"] is False and record["tools_only_planner"] == ["calculate"]


# ── The model cannot widen policy ──────────────────────────────────────────

def test_tools_the_role_may_not_use_are_removed(monkeypatch):
    # Every tool is open to every role today; a restricted one is simulated.
    from types import SimpleNamespace
    from app.domains.model_gateway import service as gateway_service
    monkeypatch.setattr(gateway_service, "tool_registry", lambda: SimpleNamespace(
        allowed=lambda granted: [SimpleNamespace(name="calculate")]))
    result = intent_planner.PlanResult(PLAN.model_copy(deep=True), 10.0)
    narrowed = intent_planner.apply_policy_invariants(result, CALC, role="Learner")
    assert narrowed.plan.tools == ["calculate"]
    assert narrowed.invariants_applied == ["tools_outside_role_removed:search_web"]


def test_an_evidence_requirement_is_never_dropped():
    result = intent_planner.PlanResult(PLAN.model_copy(deep=True), 10.0)
    floored = intent_planner.apply_policy_invariants(result, "What is the UK VAT registration threshold?")
    assert floored.plan.needs_authoritative_evidence is True
    assert "evidence_floor_applied" in floored.invariants_applied


async def test_an_unconfigured_planner_reports_and_does_not_raise(monkeypatch):
    from app.domains.model_gateway import auxiliary
    monkeypatch.setattr(auxiliary, "may_use", lambda *a, **k: False)
    result = await intent_planner.propose_plan(CALC)
    assert result.plan is None and result.failure == "not_configured"


@pytest.mark.parametrize("facts, expected", [
    (dict(route="CALCULATION", outcome="answered", formulas=["gross_profit"]), "calculation"),
    (dict(route="CALCULATION", outcome="answered", formulas=["output_vat_by_rate"]), "tax_calculation"),
    (dict(route="CALCULATION", outcome="clarification_required"), "clarification"),
    (dict(route="LLM", outcome="answered", tools={"get_exchange_rate"}), "live_data"),
    (dict(route="LLM", outcome="answered", planned_reasons=["professional rule or authority named"]), "research_standard"),
])
def test_router_intent_matches_the_benchmark_derivation(facts, expected):
    base = dict(route=None, outcome=None, answer_text="", tools=set(), planned_reasons=[], formulas=[],
                has_chart=False, has_documents=False)
    assert intent_planner.router_intent(**{**base, **facts}) == expected


# ── Planner robustness (still shadow-only) ─────────────────────────────────

def test_a_model_refusal_is_classified_not_raised():
    refusal = RuntimeError("Error code: 400 - {'code': 'json_validate_failed', "
                           "'failed_generation': 'I’m sorry, but I can’t help with that.'}")
    garbled = RuntimeError("Error code: 400 - {'code': 'json_validate_failed', 'failed_generation': '{\"intent\": '}")
    assert intent_planner._failure_kind(refusal) == "model_refused"
    assert intent_planner._failure_kind(garbled) == "malformed_output"


async def test_a_refusing_model_gives_no_plan(monkeypatch):
    from app.domains.model_gateway import auxiliary
    monkeypatch.setattr(auxiliary, "may_use", lambda *a, **k: True)
    monkeypatch.setattr(auxiliary, "complete_auxiliary", AsyncMock(side_effect=RuntimeError(
        "json_validate_failed failed_generation: I'm sorry, but I can't help with that.")))
    result = await intent_planner.propose_plan("Sign off my VAT return.")
    assert result.plan is None and result.failure == "model_refused"


def test_a_plan_naming_missing_or_invalid_inputs_is_a_clarification():
    plan = PLAN.model_copy(deep=True)
    plan.invalid_inputs = ["negative VAT rate"]
    assert intent_planner._consistent(plan).intent == "clarification"
    assert intent_planner._consistent(PLAN.model_copy(deep=True)).intent == "calculation"


async def test_the_planner_is_told_about_an_attached_document(monkeypatch):
    from app.domains.model_gateway import auxiliary
    sent = {}

    async def complete(**kwargs):
        sent.update(kwargs)
        return type("C", (), {"text": PLAN.model_dump_json(), "total_tokens": 10})()
    monkeypatch.setattr(auxiliary, "may_use", lambda *a, **k: True)
    monkeypatch.setattr(auxiliary, "complete_auxiliary", complete)
    await intent_planner.propose_plan("Using the attached balance sheet, what is the current ratio?", has_documents=True)
    assert "attached a document" in sent["user"]


async def test_malformed_output_is_retried_once_and_refusals_are_not(monkeypatch):
    from app.domains.model_gateway import auxiliary
    calls = []

    async def flaky(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("json_validate_failed failed_generation: {\"intent\": ")
        return type("C", (), {"text": PLAN.model_dump_json(), "total_tokens": 5})()
    monkeypatch.setattr(auxiliary, "may_use", lambda *a, **k: True)
    monkeypatch.setattr(auxiliary, "complete_auxiliary", flaky)
    result = await intent_planner.propose_plan("Gross margin on £10,000 revenue and £6,000 cost?")
    assert result.plan is not None and len(calls) == 2

    refusals = []

    async def refuse(**kwargs):
        refusals.append(1)
        raise RuntimeError("json_validate_failed failed_generation: I'm sorry, but I can't help with that.")
    monkeypatch.setattr(auxiliary, "complete_auxiliary", refuse)
    result = await intent_planner.propose_plan("Sign off my VAT return.")
    assert result.failure == "model_refused" and len(refusals) == 1


def test_hints_flag_a_correction_and_a_reference_back():
    plan = PLAN.model_copy(deep=True)
    hinted = intent_planner._with_hints(plan, "Revenue was £100,000. Actually revenue was £120,000. "
                                              "Costs £70,000. What's the profit?", None)
    assert hinted.missing_inputs and intent_planner._consistent(hinted).intent == "clarification"
    referred = intent_planner._with_hints(PLAN.model_copy(deep=True), "Explain that with a simple numerical example.",
                                          [{"role": "user", "content": "When is revenue recognised?"}])
    assert referred.uses_conversation is True
    alone = intent_planner._with_hints(PLAN.model_copy(deep=True), "Explain that with an example.", None)
    assert alone.uses_conversation is False          # no earlier turn: nothing to refer back to
