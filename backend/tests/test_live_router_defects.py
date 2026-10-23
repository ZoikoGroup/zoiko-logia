"""Regression tests for the verified live-router failures from the 78-case
shadow evaluation of 2026-10-16 (evals/reports/planner-shadow-router-
20261016T074432Z.json). Each test names the case and request it reproduces."""
import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from app.domains.model_gateway.agent import AgentOutcome, ToolCallRecord, run_agent
from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec
from app.orchestration import service
from app.orchestration.agent_plan import GENERAL_GUIDANCE_REASON, plan_request
from app.orchestration.calculations.engine import calculate_from_query, change_followup
from app.orchestration.calculations.visuals import calculation_visual
from tests.test_agent_loop import ScriptedClient, _call, _reply
from tests.test_answer_status_pipeline import pipeline  # noqa: F401 — full-pipeline fixture

N = SimpleNamespace


# ── 1. A calculation is not overwritten by an evidence gap ─────────────────

@pytest.mark.parametrize("question, history", [
    # int-forecast-scenario (qry-2a8ea068a0c7)
    ("Revenue is £1,000,000 growing 8% a year. What would revenue be after three years?", False),
    # int-followup-cost-down-paraphrase (qry-804b8bc2b896)
    ("Suppose our supplier cuts prices so cost of sales drops 10% — where does that leave the margin?", True),
])
def test_figure_projections_and_hypotheticals_plan_a_calculation_not_research(question, history):
    if history:
        assert service._looks_like_contextual_follow_up(question)
    plan = plan_request(question, history=history and service._looks_like_contextual_follow_up(question))
    assert plan.tools == ("calculate",)


def test_rule_questions_still_research():
    assert "search_web" in plan_request("What was the VAT threshold in 2015?").tools
    assert "search_web" in plan_request("When did the VAT threshold increase?").tools


class _Expression(BaseModel):
    expression: str


def _calculator_registry() -> ToolRegistry:
    async def calculate(args):
        return ToolResult(ok=True, content="1000000 * 1.08 ** 3 = 1259712")

    registry = ToolRegistry()
    registry.register(ToolSpec(name="calculate", version="1.0", description="Calculate.", args_model=_Expression,
                               handler=calculate, data_source="test", risk_level="low", timeout_seconds=1.0))
    return registry


async def test_a_search_reminder_keeps_the_calculated_result():
    client = ScriptedClient([
        _reply(tool_calls=[_call("calculate", {"expression": "1000000 * 1.08 ** 3"})]),
        _reply("Revenue after three years is £1,259,712."),
        _reply("Revenue after three years is £1,259,712."),
    ])
    await run_agent(client, model="m", system_prompt="", user_prompt="Revenue £1,000,000 growing 8% for 3 years?",
                    registry=_calculator_registry(), granted_permissions=frozenset(), require_evidence=True,
                    planned_tools=("search_web",))
    reminder = client.requests[2]["messages"][-1]["content"]
    assert "Keep every result the calculate tool already produced" in reminder
    assert "still give the calculated results" in reminder


async def test_a_reminder_without_a_calculation_is_unchanged():
    client = ScriptedClient([_reply("Accrual accounting records revenue when earned."), _reply("Done.")])
    await run_agent(client, model="m", system_prompt="", user_prompt="What is accrual accounting?",
                    registry=_calculator_registry(), granted_permissions=frozenset(), require_evidence=True)
    assert "Keep every result" not in client.requests[1]["messages"][-1]["content"]


# ── 2. Mixed questions keep every part ─────────────────────────────────────

MIXED_VAT = ("Calculate the VAT on £2,400 of UK standard-rated sales at 20%, excluding VAT, and tell me when the "
             "quarterly VAT return is due.")                         # ps-mixed-vat-and-deadline (qry-4ed547219332)
MIXED_DEPRECIATION = ("Calculate straight-line depreciation on a £50,000 machine with a £5,000 residual value over 5 "
                      "years, and explain what IAS 16 says about reviewing the useful life.")  # qry-9914d7c9d502


@pytest.mark.parametrize("question, value, part", [
    (MIXED_VAT, "£480.00", "tell me when the quarterly VAT return is due."),
    (MIXED_DEPRECIATION, "£9,000.00", "explain what IAS 16 says about reviewing the useful life."),
])
def test_a_mixed_question_calculates_its_given_figures_and_keeps_the_other_part(question, value, part):
    result = calculate_from_query(question)
    assert result.status == "success" and value in [o.display_value for o in result.outputs]
    assert service.uncalculated_part(question) == part


async def test_the_research_part_of_a_mixed_question_reaches_the_evidence_path(pipeline):
    pipeline.answers(AgentOutcome(text="VAT = £2,400 × 20% = £480. The return is due one month and seven days "
                                       "after the period ends."))
    response, _ = await pipeline.ask(MIXED_VAT)
    prompt = pipeline.agent.await_args.args[0]
    assert response.route == "LLM" and "£480.00" in prompt


def test_an_amount_without_a_stated_vat_treatment_is_still_asked_about():
    assert calculate_from_query("Calculate VAT on £500 at 20%.").error_code == "MISSING_INPUT"
    gross = calculate_from_query("Calculate VAT on £1,200 including VAT at 20%.")
    assert [o.display_value for o in gross.outputs] == ["£200.00", "£1,000.00"]


# ── 3. Invalid rates are checked before calculating ────────────────────────

@pytest.mark.parametrize("sign", ["-", "−"])
def test_a_negative_interest_rate_is_not_calculated(sign):
    # ps-invalid-negative-interest (qry-ad88ec2cf69e) computed −£600.
    result = calculate_from_query(f"Calculate simple interest on £5,000 at {sign}4% a year for 3 years.")
    assert result.error_code == "INVALID_PERCENTAGE" and "negative" in result.message and not result.outputs


def test_simple_interest_on_valid_inputs():
    result = calculate_from_query("Calculate simple interest on £5,000 at 4% a year for 3 years.")
    assert [o.display_value for o in result.outputs] == ["£600.00", "£5,600.00"]


async def test_a_negative_interest_rate_is_rejected_through_the_pipeline(pipeline):
    response, audited = await pipeline.ask("Calculate simple interest on £5,000 at -4% a year for 3 years.")
    assert audited.outcome == "clarification_required" and response.next_action.type == "calculation_input_invalid"


# ── 4. Follow-ups keep earlier changes when asked, and nothing unrelated ───

TWO_STEP = [N(role="user", content="Revenue £300,000, cost of sales £180,000."), N(role="assistant", content="…"),
            N(role="user", content="Now assume revenue grows by 10%."), N(role="assistant", content="…")]


def test_a_change_on_top_of_an_earlier_change_keeps_both():
    # int-followup-two-step (qry-0ca07ff7de52) gave £111,000.
    result = change_followup("And if cost of sales also rises by 5% on top of that, what is the gross profit?", TWO_STEP)
    values = {o.name: o.value for o in result.outputs}
    assert values["revenue"] == Decimal("330000") and values["gross_profit"] == Decimal("141000")
    assert any("kept" in note for note in result.notes)


def test_instead_replaces_the_earlier_change():
    result = change_followup("What if cost of sales rises by 5% instead?", TWO_STEP)
    assert {o.name: o.value for o in result.outputs}["gross_profit"] == Decimal("111000")


# ── 5. Every measure is reconciled; contradictions are flagged ─────────────

def test_operating_profit_is_reconciled_when_overheads_are_given():
    # int-recon-op-mismatch-paraphrase (qry-2ea1713b089f) checked gross profit only.
    result = calculate_from_query("My junior's P&L says sales £200,000, COGS £125,000, gross profit £75,000, "
                                  "overheads £45,000 and operating profit £40,000. Does that add up?")
    displayed = [o.display_value for o in result.outputs]
    assert "£30,000.00" in displayed and any("£10,000.00 higher" in note for note in result.notes)


def test_a_corrected_figure_is_put_back_to_the_user():
    # int-contradictory-inputs (qry-efb297d2000a) used £120,000 silently.
    result = calculate_from_query("Revenue was £100,000. Actually revenue was £120,000. Costs £70,000. What's the profit?")
    assert result.error_code == "AMBIGUOUS_INPUTS"
    assert "£100,000.00" in result.message and "£120,000.00" in result.message


def test_two_periods_are_not_a_correction():
    assert calculate_from_query("Revenue was £100,000 in 2024 and revenue was £120,000 in 2025. "
                                "Calculate the growth.").error_code != "AMBIGUOUS_INPUTS"


# ── 6. No calculator calls on invented figures ─────────────────────────────

@pytest.mark.parametrize("question, history, expected", [
    # ps-std-depreciation-method-change (qry-8f912ad70d11): four calls on an invented £100,000 asset.
    ("Can we switch from straight-line to reducing-balance depreciation halfway through an asset's life?", [], False),
    ("What does IAS 16 say about useful life reviews in 2026?", [], False),
    ("Explain that with a simple numerical example.", [N(role="user", content="When is revenue recognised?")], True),
    ("Using the same figures, what profit?", [N(role="user", content="Fixed costs £72,000")], True),
])
def test_figures_are_supplied_only_by_the_user(question, history, expected):
    assert service.supplies_figures(question, history) is expected


async def test_calculate_is_refused_and_audited_when_no_figures_were_given():
    db = AsyncMock()
    db.execute.return_value = N(first=lambda: N(role="Admin", is_active=True, tenant_id="t"))
    authorize = service._tool_authorizer(db, lock=asyncio.Lock(), actor_id="u", tenant_id="t", role="Admin",
                                         figures_supplied=False)
    refused, search = await authorize("calculate"), await authorize("search_web")
    assert not refused.allowed and refused.reason_code == "no_user_figures"
    assert search.allowed
    allowed = await service._tool_authorizer(db, lock=asyncio.Lock(), actor_id="u", tenant_id="t", role="Admin")("calculate")
    assert allowed.allowed


async def test_the_figures_rule_never_allows_what_policy_refused():
    db = AsyncMock()
    db.execute.return_value = N(first=lambda: N(role="Admin", is_active=False, tenant_id="t"))
    decision = await service._tool_authorizer(db, lock=asyncio.Lock(), actor_id="u", tenant_id="t", role="Admin",
                                              figures_supplied=True)("calculate")
    assert not decision.allowed and decision.reason_code == "user_not_authorised"


# ── 7. Multi-period charts are calculated in full first ────────────────────

TWO_YEARS = ("Current assets £75,500 and current liabilities £12,700 at year end; last year they were £60,000 and "
             "£15,000. Calculate the current ratio for both years and chart the change.")


def test_both_periods_are_calculated_and_charted():
    # int-multistep-ratio-chart (qry-783063d1518e): one year, no chart.
    result = calculate_from_query(TWO_YEARS)
    assert [o.display_value for o in result.outputs] == ["5.94:1", "4.00:1", "+1.94"]
    spec, _ = calculation_visual(result, TWO_YEARS, "spec")
    assert spec.type == "BAR" and [round(p.y, 2) for p in spec.data] == [5.94, 4.0]


def test_a_chart_of_several_calculated_amounts_validates():
    from app.orchestration.calculations.schemas import CalculationOutput, CalculationResult
    result = CalculationResult(matched=True, status="success", verification_status="passed", outputs=[
        CalculationOutput(name="gross_profit", value=Decimal("42"), display_value="£42", kind="money"),
        CalculationOutput(name="cost", value=Decimal("84"), display_value="£84", kind="money")])
    spec, _ = calculation_visual(result, "show a bar chart", "spec")
    assert spec is not None and spec.encoding is not None


def test_chart_and_graph_are_verbs_but_a_chart_of_accounts_is_not_a_chart():
    from app.orchestration.response_planner import detect_explicit_visual_request
    assert detect_explicit_visual_request("chart the change") and detect_explicit_visual_request("graph the trend")
    assert not detect_explicit_visual_request("Explain the chart of accounts")


# ── 8. Practical guidance is a labelled general explanation (Decision C) ───

def test_practical_guidance_is_not_sent_to_web_research():
    # int-planning-recommendation (qry-104c8cf4ab5f): "the sources do not contain this".
    plan = plan_request("We're a 10-person agency. What month-end close steps should we put in place first?")
    assert plan.tools == () and plan.reasons == (GENERAL_GUIDANCE_REASON,)


@pytest.mark.parametrize("question", [
    "What VAT return steps should we put in place?",        # a tax subject keeps its evidence requirement
    "Month-end close steps for IFRS 15 revenue?",            # so does a standard
])
def test_rules_taxes_and_standards_keep_their_evidence_requirement(question):
    assert GENERAL_GUIDANCE_REASON not in plan_request(question).reasons


# ── 9. A refusal is never complete ─────────────────────────────────────────

async def test_an_off_domain_refusal_is_recorded_as_no_answer(pipeline):
    # int-offdomain-recipe (qry-1729591e1e0a) was recorded as complete.
    response, audited = await pipeline.ask("Give me a recipe for lasagne.")
    assert response.outcome == "refused"
    assert not response.next_action or response.next_action.type != 'composition_failed'
    pipeline.agent.assert_not_awaited()
    if response.answer is not None:
        assert response.answer.completeness == audited.completeness == "none"


async def test_calculate_is_allowed_after_a_data_tool_fetched_the_figures():
    db = AsyncMock()
    db.execute.return_value = N(first=lambda: N(role="Admin", is_active=True, tenant_id="t"))
    authorize = service._tool_authorizer(db, lock=asyncio.Lock(), actor_id="u", tenant_id="t", role="Admin",
                                         figures_supplied=False)
    assert not (await authorize("calculate")).allowed
    assert (await authorize("get_exchange_rate")).allowed
    assert (await authorize("calculate")).allowed


async def test_an_attached_document_counts_as_supplied_figures(pipeline, monkeypatch):
    # int-doc-inconsistent (qry-070bf557cd14, post-fix run): "Review the attached P&L for arithmetic errors"
    # has no digits; calculate was refused and the answer escalated.
    seen = {}
    real = service._tool_authorizer

    def spy(*args, **kwargs):
        seen["figures_supplied"] = kwargs.get("figures_supplied")
        return real(*args, **kwargs)
    monkeypatch.setattr(service, "_tool_authorizer", spy)
    monkeypatch.setattr(service, "resolve_document_ids", AsyncMock(return_value=["doc-1"]), raising=False)
    pipeline.answers(AgentOutcome(text="Gross profit 2026 should be 192,000."))
    from app.orchestration.schemas import AskKritonRequest
    from unittest.mock import MagicMock
    request = AskKritonRequest(query="Review the attached P&L for arithmetic errors.", document_ids=["doc-1"])
    try:
        await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT", request=request)
    except Exception:
        pass  # document loading is not faked here; only the authorizer's input matters
    assert seen["figures_supplied"] is True
    assert service.supplies_figures("Review the attached P&L for arithmetic errors.", []) is False


def test_concept_questions_naming_vat_and_calculate_are_not_a_vat_calculation():
    # Ten concept questions in one message were asked for "vat rate".
    questions = ("How does Value Added Tax (VAT) work in the United Kingdom? "
                 "How do businesses calculate and report corporate income tax?")
    result = calculate_from_query(questions)
    assert result.error_code != "MISSING_INPUT" or "vat" not in (result.message or "").lower()
    assert calculate_from_query("Calculate VAT on £500.").error_code == "MISSING_INPUT"   # an amount still needs its rate
