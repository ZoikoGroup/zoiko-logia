"""The batched calculator (calc_tool.CALCULATE_BATCH_TOOL) and what it
must not change: every result kept and traceable, failed items never shown
as results, the single-expression calculator unchanged, charts agreeing
with the text, and the same limits and policy as before.
docs/kriton-batched-calculator-and-balance-provenance-design.md §1."""
import asyncio
import json
from types import SimpleNamespace as N

import pytest

from app.domains.model_gateway.agent import AgentLimits, AgentOutcome, ToolCallRecord, run_agent, verified_working
from app.domains.model_gateway.tool_registry import ToolRegistry, build_default_registry
from app.domains.model_gateway.tools.calc_tool import (
    CALCULATE_BATCH_TOOL, CALCULATE_TOOL, CalculateArgs, CalculateBatchArgs, _handle, _handle_batch,
)
from app.orchestration import audit_events, service
from app.orchestration.figure_reconciliation import (
    CHART_OMITTED_PREFIX, figure_provenance, reconcile_charts, unreconciled_figures,
)
from tests.test_agent_loop import ScriptedClient, _call, _reply
from tests.test_answer_status_pipeline import pipeline  # noqa: F401 — full-pipeline fixture
from tests.test_schedule_and_period_answerability import FINANCIALS
from app.orchestration.websearch import WebSource
from tests.test_verified_work_fallback import FailingAfter

# A real FX answer carries the retrieved rate: its tool call and a dated
# observation (fx_profit.fresh_fx_sources needs one within 7 days).
from datetime import date

from app.domains.calculations.schemas import LiveObservation

ECB = WebSource(title="ECB GBP/USD reference rate", url="https://www.ecb.europa.eu/stats/eurofxref",
                snippet=f"GBP/USD 1.3335308 on {date.today().isoformat()}", provider="ECB", freshness="daily",
                observation=LiveObservation(observation_id="o1", indicator="GBP/USD exchange rate", value="1.3335308",
                                            unit="USD per GBP", period=date.today().isoformat(), provider="ECB",
                                            source_url="https://www.ecb.europa.eu/stats/eurofxref", freshness="daily"))
RATE_CALL = ToolCallRecord(1, "get_exchange_rate", "h", True, None, 5, 1)

# The stored FX benchmark question (qry-3b42c1c9fc1b), unchanged.
FX_QUESTION = (
    "I am evaluating whether our UK company should hold more cash in US dollars for planned supplier payments.\n\n"
    "We expect to pay US$125,000 in 60 days. Our approved budget rate is £1 = US$1.25. Please calculate the "
    "budgeted sterling cost and explain the financial impact if the exchange rate moves to £1 = US$1.20 or "
    "£1 = US$1.30.\n\nThen obtain the latest available USD/GBP or GBP/USD market reference rate from an available "
    "data source. Clearly state the source, timestamp and quote direction. Do not use the budget rate as if it "
    "were a live market quote.\n\nCompare the budget rate with the actual retrieved reference rate, calculate the "
    "indicative sterling cost of US$125,000 at the retrieved rate, and explain the limitations of using a "
    "reference rate rather than an executable bank quote.\n\nFinally, provide a scenario table and chart showing "
    "the sterling cost at the budget rate, the two specified exchange-rate scenarios, and the retrieved reference "
    "rate. If the live-data tool fails, disclose that and still complete the calculations using the rates I "
    "supplied.")
FX_ITEMS = [{"label": "Budget", "expression": "125000 / 1.25"}, {"label": "At 1.20", "expression": "125000 / 1.20"},
            {"label": "At 1.30", "expression": "125000 / 1.30"}]


def batch(items) -> CalculateBatchArgs:
    return CalculateBatchArgs(expressions=items)


def batch_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CALCULATE_BATCH_TOOL)
    return registry


# 1. Multiple successful expressions in one call.
async def test_several_expressions_each_get_a_result_and_a_receipt():
    result = await _handle_batch(batch(FX_ITEMS))
    assert result.ok and result.items_total == 3 and result.items_failed == 0
    assert [r["result"] for r in result.receipts] == ["100000", "104166.666667", "96153.846154"]
    assert [r["batch_index"] for r in result.receipts] == [1, 2, 3] and {r["batch_size"] for r in result.receipts} == {3}
    assert len({r["calculation_id"] for r in result.receipts}) == 3
    assert result.receipt == result.receipts[0]                       # single-receipt readers still work
    for item in FX_ITEMS:
        assert f"{item['label']}: {item['expression']} = " in result.content


# 2. A mixture of successful and failed expressions.
async def test_a_failed_item_does_not_disturb_the_others_and_is_not_presented_as_a_result():
    items = [FX_ITEMS[0], {"label": "Bad", "expression": "125000 / rate"}, {"label": "Zero", "expression": "1 / 0"},
             FX_ITEMS[2]]
    result = await _handle_batch(batch(items))
    assert result.ok and result.items_total == 4 and result.items_failed == 2
    assert [r["expression"] for r in result.receipts] == ["125000 / 1.25", "125000 / 1.30"]
    assert "2. Bad: 125000 / rate — NOT COMPUTED" in result.content
    assert "3. Zero: 1 / 0 — NOT COMPUTED" in result.content and "Division by zero" in result.content
    assert "Do not state a result for this item." in result.content


async def test_an_all_failed_batch_is_a_failure():
    result = await _handle_batch(batch([{"expression": "a + b"}, {"expression": "1 / 0"}]))
    assert not result.ok and result.receipts == () and result.items_failed == 2


# 3. Complete fallback output for every successful result.
async def test_a_timeout_after_a_batch_keeps_every_verified_result_and_no_failed_one():
    calls = [_call("calculate", {"expressions": [*FX_ITEMS, {"label": "Bad", "expression": "x * 2"}]}, "c1")]
    outcome = await run_agent(FailingAfter([_reply(tool_calls=calls)], asyncio.TimeoutError()), model="m",
                              system_prompt="", user_prompt=FX_QUESTION, registry=batch_registry(),
                              granted_permissions=frozenset())
    for line in ("Budget: 125000 / 1.25 = 100000", "At 1.20: 125000 / 1.20 = 104166.666667",
                 "At 1.30: 125000 / 1.30 = 96153.846154"):
        assert line in outcome.text
    assert "x * 2" not in outcome.text and len(outcome.calculation_receipts) == 3


def test_the_withheld_answer_working_lists_every_item():
    executed = {("calculate", "k"): N(ok=True, content="(not used)", all_receipts=(
        {"label": "Budget", "expression": "125000 / 1.25", "result": "100000"},
        {"label": "At 1.30", "expression": "125000 / 1.30", "result": "96153.846154"}))}
    assert verified_working(executed) == ["Budget: 125000 / 1.25 = 100000", "At 1.30: 125000 / 1.30 = 96153.846154"]


# 4. Audit records containing every relevant calculation ID.
async def test_the_tool_call_record_carries_every_calculation_id():
    client = ScriptedClient([_reply(tool_calls=[_call("calculate", {"expressions": FX_ITEMS}, "c1")]),
                             _reply("Budget £100,000; at 1.20 £104,166.67; at 1.30 £96,153.85.")])
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt=FX_QUESTION,
                              registry=batch_registry(), granted_permissions=frozenset())
    [record] = outcome.tool_calls
    assert record.calculation_ids == tuple(r["calculation_id"] for r in outcome.calculation_receipts)
    assert len(record.calculation_ids) == 3 and record.calculation_id == record.calculation_ids[0]
    assert record.items_total == 3 and record.items_failed == 0


async def test_the_audit_events_record_ids_batch_positions_and_failures(monkeypatch):
    emitted = []

    async def fake_emit(db, event, *args, **kwargs):
        emitted.append((event, args[-1]))
    monkeypatch.setattr(audit_events, "_emit", fake_emit)
    ids = {"query_id": "q", "correlation_id": "c", "tenant_id": "t", "audit_chain_id": "a", "actor_id": "u"}
    await audit_events.audit_agent_tool_called(None, **ids, step=1, tool="calculate", arguments_hash="h", ok=True,
                                               error_code=None, duration_ms=1, source_count=0, calculation_id="c1",
                                               calculation_ids=("c1", "c2"), items_total=3, items_failed=1)
    await audit_events.audit_calculation_receipt(None, **ids, receipt={"calculation_id": "c2", "batch_index": 2,
                                                                       "batch_size": 3, "result": "5"})
    (_, called), (_, receipt) = emitted
    assert called["calculation_ids"] == ["c1", "c2"] and called["items_failed"] == 1
    assert receipt["batch_index"] == 2 and receipt["batch_size"] == 3


def test_each_answer_figure_is_linked_to_the_calculation_that_produced_it():
    receipts = [{"calculation_id": "c1", "result": "100000", "rounded": "100000.00"},
                {"calculation_id": "c2", "result": "104166.666667", "rounded": "104166.67"}]
    found = figure_provenance("| Budget | £100,000 |\n| At 1.20 | £104,166.67 |\nThe rate was 1.25.", receipts)
    assert [(item["figure"], item["calculation_ids"]) for item in found] == [("£100,000", ["c1"]),
                                                                            ("£104,166.67", ["c2"])]


async def test_the_pipeline_audits_figure_provenance_for_the_released_answer(pipeline):
    receipts = [{"calculation_id": "c1", "formula_version": "expression-evaluator-1.0", "expression": "125000/1.25",
                 "result": "100000", "rounded": "100000.00"}]
    pipeline.answers(AgentOutcome(text="Budget cost = US$125,000 ÷ 1.25 = £100,000.", calculation_receipts=receipts))
    await pipeline.ask("We expect to pay US$125,000. Our budget rate is £1 = US$1.25. Calculate the sterling cost.")
    figures = service.audit_answer_figure_provenance.await_args.kwargs["figures"]
    assert {"figure": "£100,000", "calculation_ids": ["c1"]}.items() <= next(
        item for item in figures if item["figure"] == "£100,000").items()
    assert all("statement_hash" in item and "statement" not in item for item in figures)


# 5. Agreement between prose, tables and charts.
CHART = ('```chart\n{"type": "bar", "title": "Sterling cost", "categories": ["Budget", "At 1.20", "At 1.30"], '
         '"series": [{"name": "GBP", "data": [100000.0, 104166.67, 96153.85]}]}\n```')


def test_a_chart_value_the_text_withheld_is_left_out_and_named():
    text = "| Budget | £100,000 |\n| At 1.20 | £104,166.67 |\n" + CHART
    fixed, dropped = reconcile_charts(text, verified=[125000, 1.25, 1.2, 1.3, 100000, 104166.666667])
    assert dropped == ["At 1.30"]
    spec = json.loads(fixed.split("```chart\n", 1)[1].split("\n```", 1)[0])
    assert spec["categories"] == ["Budget", "At 1.20"] and spec["series"][0]["data"] == [100000.0, 104166.67]
    assert f"{CHART_OMITTED_PREFIX} At 1.30" in fixed


def test_a_chart_of_verified_figures_is_unchanged():
    fixed, dropped = reconcile_charts(CHART, verified=[100000, 104166.666667, 96153.846154])
    assert fixed == CHART and dropped == []


async def test_the_pipeline_keeps_text_and_chart_in_agreement(pipeline):
    receipts = [{"calculation_id": f"c{i}", "formula_version": "expression-evaluator-1.0", "expression": e, "result": r}
                for i, (e, r) in enumerate((("125000/1.25", "100000"), ("125000/1.20", "104166.666667")))]
    pipeline.answers(AgentOutcome(text="Budget cost £100,000; at 1.20 it is £104,166.67.\n\n" + CHART,
                                  calculation_receipts=receipts, sources=[ECB], tool_calls=[RATE_CALL]))
    response, audited = await pipeline.ask(FX_QUESTION)
    assert "96153.85" not in response.answer.text and f"{CHART_OMITTED_PREFIX} At 1.30" in response.answer.text
    assert any("chart leaves out At 1.30" in item for item in response.answer.limitations)
    assert response.answer.completeness == audited.completeness == "partial"


# 6. Existing single-expression callers and backward compatibility.
def test_the_production_registry_keeps_the_single_expression_calculator():
    spec = build_default_registry().get("calculate")
    assert spec is CALCULATE_TOOL and "expressions" not in json.dumps(spec.function_schema())
    assert build_default_registry(batch_calculations=True).get("calculate") is CALCULATE_BATCH_TOOL


async def test_the_single_form_of_the_batch_tool_matches_the_existing_calculator():
    old = await _handle(CalculateArgs(expression="505000 / 1215000 * 100", label="Gross margin"))
    new = await _handle_batch(CalculateBatchArgs(expression="505000 / 1215000 * 100", label="Gross margin"))
    assert new.content == old.content and new.receipt["result"] == old.receipt["result"]
    assert new.receipt["formula_version"] == old.receipt["formula_version"] and new.receipts == ()


# 7. Invalid input, execution limits and security boundaries.
@pytest.mark.parametrize("arguments, message", [
    ({"expressions": [{"expression": "1+1"}] * 13}, "at most 12"),
    ({"expression": "1+1", "expressions": [{"expression": "2+2"}]}, "not both"),
    ({}, "not neither"),
    ({"expressions": []}, "at least 1"),
    ({"expressions": [{"expression": "1+1", "code": "x"}]}, "Extra inputs"),
    ({"expressions": [{"expression": "1" * 241}]}, "at most 240"),
])
async def test_malformed_batches_are_rejected_safely(arguments, message):
    result = await batch_registry().execute("calculate", json.dumps(arguments), granted_permissions=frozenset())
    assert not result.ok and result.error_code == "invalid_arguments" and message in result.content


@pytest.mark.parametrize("expression", ["__import__('os').system('id')", "open('/etc/passwd')", "(1).__class__",
                                        "lambda: 1", "9 ** 9 ** 9 ** 9", "[1] * 10"])
async def test_code_and_unbounded_work_are_refused_per_item(expression):
    result = await batch_registry().execute(
        "calculate", json.dumps({"expressions": [{"expression": expression}, {"expression": "2 + 2"}]}),
        granted_permissions=frozenset())
    assert result.ok and result.items_failed == 1 and [r["result"] for r in result.receipts] == ["4"]


def test_the_batch_tool_keeps_the_calculators_policy_and_limits():
    for field in ("allowed_roles", "tenant_scope", "required_permission", "is_write_action", "timeout_seconds",
                  "risk_level", "data_source"):
        assert getattr(CALCULATE_BATCH_TOOL, field) == getattr(CALCULATE_TOOL, field), field


async def test_the_calculation_budget_counts_batch_items():
    twelve = [{"expression": f"{n} + 1"} for n in range(12)]
    client = ScriptedClient([_reply(tool_calls=[_call("calculate", {"expressions": twelve}, "c1")]),
                             _reply(tool_calls=[_call("calculate", {"expressions": twelve[:5]}, "c2")]),
                             _reply("done")])
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt="Add one to 0..11",
                              registry=batch_registry(), granted_permissions=frozenset(),
                              limits=AgentLimits(max_steps=5, max_tool_calls=8, max_calculations=15))
    assert [c.error_code for c in outcome.tool_calls] == [None, "budget_exhausted"]
    assert len(outcome.calculation_receipts) == 12


async def test_a_refused_call_is_refused_for_every_item():
    async def refuse(tool):
        return N(allowed=False, reason_code="no_user_figures", decision_id="d1", tool=tool)
    client = ScriptedClient([_reply(tool_calls=[_call("calculate", {"expressions": FX_ITEMS}, "c1")]), _reply("ok")])
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt="x", registry=batch_registry(),
                              granted_permissions=frozenset(), authorize=refuse)
    assert outcome.calculation_receipts == [] and not outcome.tool_calls[0].ok


async def test_a_long_batch_keeps_every_result_within_the_output_limit():
    items = [{"label": "L" * 120, "expression": "(" + "1+" * 118 + "1)"} for _ in range(12)]
    result = await batch_registry().execute("calculate", json.dumps({"expressions": items}),
                                            granted_permissions=frozenset())
    assert result.ok and len(result.receipts) == 12 and "truncated" not in result.content
    assert result.content.count("= 119") == 12


# 8. The benchmark questions, with batched receipts.
FX_RECEIPTS = [{"calculation_id": f"fx{i}", "formula_version": "expression-evaluator-1.0", "label": label,
                "expression": expression, "result": result, "batch_index": i + 1, "batch_size": 4}
               for i, (label, expression, result) in enumerate((
                   ("Budget", "125000/1.25", "100000"), ("At 1.20", "125000/1.20", "104166.666667"),
                   ("At 1.30", "125000/1.30", "96153.846154"), ("Market", "125000/1.3335308", "93736.12")))]


async def test_the_fx_benchmark_answer_keeps_every_scenario_in_text_and_chart(pipeline):
    chart = CHART.replace('"At 1.30"]', '"At 1.30", "Market"]').replace("96153.85]", "96153.85, 93736.12]")
    text = ("| Scenario | Sterling cost |\n|---|---|\n| Budget (1.25) | £100,000 |\n| At 1.20 | £104,166.67 |\n"
            "| At 1.30 | £96,153.85 |\n| Market (1.3335308) | £93,736.12 |\n\n" + chart)
    pipeline.answers(AgentOutcome(text=text, calculation_receipts=FX_RECEIPTS, sources=[ECB], tool_calls=[RATE_CALL]))
    response, _ = await pipeline.ask(FX_QUESTION)
    for figure in ("£100,000", "£104,166.67", "£96,153.85", "£93,736.12"):
        assert figure in response.answer.text
    assert CHART_OMITTED_PREFIX not in response.answer.text


async def test_the_financial_benchmark_answer_is_released_from_batched_receipts(pipeline):
    pairs = (("1250000-35000", "1215000"), ("1215000-710000", "505000"), ("505000/1215000*100", "41.563786"),
             ("165000+48000+32000+41000+28000", "314000"), ("505000-314000", "191000"),
             ("191000/1215000*100", "15.720165"), ("191000-14000", "177000"), ("1100000-660000", "440000"),
             ("440000-285000", "155000"))
    receipts = [{"calculation_id": f"f{i}", "formula_version": "expression-evaluator-1.0", "expression": e,
                 "result": r, "batch_index": i + 1, "batch_size": len(pairs)} for i, (e, r) in enumerate(pairs)]
    text = ("| Measure | Current year | Previous year |\n|---|---|---|\n| Net sales | £1,215,000 | £1,100,000 |\n"
            "| Gross profit | £505,000 | £440,000 |\n| Operating profit | £191,000 | £155,000 |\n"
            "Gross margin is 41.56%; operating margin is 15.72%; profit before tax is £177,000.")
    pipeline.answers(AgentOutcome(text=text, calculation_receipts=receipts))
    response, audited = await pipeline.ask(FINANCIALS)
    assert response.answer.completeness == audited.completeness == "complete"
    for figure in ("£1,215,000", "£505,000", "£440,000", "£191,000", "£155,000", "41.56%", "15.72%", "£177,000"):
        assert figure in response.answer.text


# Tracked issues.
def test_a_number_only_in_the_instructions_is_not_provenance():
    from app.domains.model_gateway.agent import AGENT_TOOL_INSTRUCTIONS
    assert "1,028,315.04" in AGENT_TOOL_INSTRUCTIONS                  # an example in the instructions
    facts = "Convert US$10,000 at the bank's rate."
    assert unreconciled_figures("The cost is ₹1,028,315.04.", facts, "", stated=facts) == ["₹1,028,315.04"]


async def test_the_agent_gate_reads_figure_evidence_not_the_instructions():
    from app.domains.model_gateway.agent import AGENT_TOOL_INSTRUCTIONS
    client = ScriptedClient([_reply("The cost is ₹1,028,315.04."), _reply("The cost is ₹1,028,315.04.")])
    outcome = await run_agent(client, model="m", system_prompt="", registry=batch_registry(),
                              user_prompt="Convert US$10,000." + AGENT_TOOL_INSTRUCTIONS,
                              granted_permissions=frozenset(), figure_evidence="Convert US$10,000.")
    assert outcome.unreconciled_figures == ["₹1,028,315.04"]


@pytest.mark.parametrize("text, flagged", [
    ("Revenue grew about 10%.", []),                         # 10.45% rounded, marked approximate
    ("Revenue grew 10%.", ["10%"]),                          # unmarked: the strict bound
    ("Revenue grew about 11%.", ["11%"]),                    # not a rounding of 10.45%
    ("Net sales were roughly £1.2m.", []),                   # £1,215,000 to the written precision
    ("Net sales were about £1m.", ["£1m"]),                  # beyond the 5% cap: materially wrong
])
def test_an_approximate_figure_may_round_but_not_misstate(text, flagged):
    evidence = "Revenue grew from 1,100,000 to 1,215,000."
    assert unreconciled_figures(text, evidence, "1215000/1100000*100-100 = 10.454545", stated=evidence) == flagged


def test_a_sourced_rate_is_an_operand_and_an_invented_one_is_not():
    from app.orchestration.verification_service import calculated_figures
    sourced = FX_QUESTION + "\n[REF-1] ECB GBP/USD reference rate\nGBP/USD 1.3335308"
    figures = calculated_figures(None, question=sourced, receipts=[{"expression": "125000/1.3335308", "result": "93736.12"},
                                                                   {"expression": "125000/1.4178", "result": "88165.04"}])
    assert "93736.12" in figures.results and figures.assumed == ["125000/1.4178"]


@pytest.mark.parametrize("separator", [" ", " ", " ", " ", " ", " ", "'", "’",
                                       "٬", "​"])
def test_a_figure_grouped_with_any_space_or_apostrophe_is_read_whole(separator):
    # "£93" (FX benchmark, 2026-10-17): £93,736.12 written with a separator
    # the reader did not know was read as £93.
    from app.orchestration.figure_reconciliation import material_figures
    assert material_figures(f"The indicative cost is £93{separator}736.12.") == [("£93,736.12", 93736.12)]


def test_an_apostrophe_that_is_not_grouping_is_left_alone():
    from app.orchestration.figure_reconciliation import material_figures
    assert material_figures("In '93 it's £1,000; in '24 it was 3'rd.") == [("£1,000", 1000.0)]


# ── Token cap including the final answer; hand-worked figures (2026-10-17) ──

async def test_the_final_answer_turn_stays_within_the_token_cap():
    # Live: the financial analysis reached 163k of 150k because the cap was
    # checked only after a call, and the final answer turn came on top.
    def costly(reply, tokens):
        reply.usage = N(total_tokens=tokens)
        return reply
    # 40k per call: after two steps (80k) a third step and the final turn
    # would need another 80k, so the run stops calling tools and answers.
    calls = [_call("calculate", {"expression": f"{n} + 1"}, f"c{n}") for n in range(2)]
    client = ScriptedClient([costly(_reply(tool_calls=[call]), 40_000) for call in calls] + [costly(_reply("done"), 40_000)])
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt="Add one to each.",
                              registry=batch_registry(), granted_permissions=frozenset(),
                              limits=AgentLimits(max_steps=10, max_tool_calls=10, max_total_tokens=150_000))
    assert outcome.stop_reason == "token_budget" and outcome.tokens_used <= 150_000
    assert outcome.text == "done" and len(outcome.calculation_receipts) == 2


HAND_WORKED = "Budget cost £100,000. At 1.20 the cost is £104,166.67; at 1.30 it is £96,153.85."


async def test_hand_worked_figures_are_sent_to_the_calculator_once():
    client = ScriptedClient([_reply(tool_calls=[_call("calculate", {"expression": "125000 / 1.25"}, "c1")]),
                             _reply(HAND_WORKED), _reply(tool_calls=[_call("calculate", {"expressions": FX_ITEMS[1:]}, "c2")]),
                             _reply(HAND_WORKED)])
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt=FX_QUESTION, registry=batch_registry(),
                              granted_permissions=frozenset(), planned_tools=("calculate",), stated_facts=FX_QUESTION)
    reminder = client.requests[2]["messages"][-1]["content"]
    assert "without the calculator: £104,166.67, £96,153.85" in reminder
    assert len(outcome.calculation_receipts) == 3 and outcome.text == HAND_WORKED


async def test_no_hand_worked_reminder_without_a_planned_calculation_or_budget():
    from tests.test_operating_forecast_answerability import calculator
    for planned, limits in ((("search_web",), AgentLimits()), (("calculate",), AgentLimits(max_total_tokens=100))):
        first = _reply(tool_calls=[_call("calculate", {"expression": "125000/1.25"}, "c1")])
        first.usage = N(total_tokens=70)          # no room for another step and the final answer
        client = ScriptedClient([first, _reply(HAND_WORKED)])
        await run_agent(client, model="m", system_prompt="", user_prompt=FX_QUESTION, registry=calculator(),
                        granted_permissions=frozenset(), planned_tools=planned, stated_facts=FX_QUESTION, limits=limits)
        assert len(client.requests) == (0 if limits.max_total_tokens == 100 else 2), planned
