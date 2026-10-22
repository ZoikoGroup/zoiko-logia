"""A self-contained operating forecast is answered from the user's figures.

Live 2026-10-16 (qry-58ce336ac0d7): "Our current annual revenue is £2,400,000,
variable costs are 45% of revenue … calculate current contribution, operating
profit, contribution margin and break-even revenue" was answered "The sources
provided do not establish an answer to this." Three causes, traced with the
real model and a faked database:

- "current" (a label on the user's own revenue) read as a lookup of today's
  rate, so the forecast was a research question and its formulas needed
  citations (refused or kept depending on how the model formatted them);
- with calculate planned, the model sometimes wrote "The sources provided do
  not state this" for every part without calling it, and that was accepted;
- the follow-up's evidence held 165+ numbers, over the figure gate's pairwise
  limit, so "£98,400 more" (638,400 − 540,000) and "31.82% growth" were
  withheld, or the whole answer replaced with the evidence-gap text.

Model output here is scripted; nothing depends on a live model."""
import asyncio
import re
from unittest.mock import AsyncMock

from pydantic import BaseModel

from app.domains.model_gateway.agent import AgentOutcome, run_agent
from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec
from app.orchestration import service
from app.orchestration.calculation_service import is_self_contained_calculation, needs_lookup
from app.orchestration.calculations.engine import change_followup
from app.orchestration.figure_reconciliation import unreconciled_figures
from app.orchestration.schemas import ConversationMessage
from app.orchestration.verification_service import calculated_figures, verify_for_release
from tests.test_agent_loop import ScriptedClient, _call, _reply
from tests.test_answer_status_pipeline import page_status, pipeline  # noqa: F401 — full-pipeline fixture
from tests.test_verified_work_fallback import FailingAfter

FORECAST = ("We are preparing a 12-month operating forecast. Our current annual revenue is £2,400,000, variable costs "
            "are 45% of revenue, and annual fixed operating costs are £780,000. Ignore interest, tax and depreciation "
            "for this simplified model.\n\nCalculate current contribution, operating profit under these assumptions, "
            "contribution margin and break-even revenue. Show the formulas.")
FOLLOW_UP = ("Now model a scenario where revenue increases by 12%, the variable-cost percentage stays at 45%, and fixed "
             "operating costs increase by £60,000. Calculate the revised operating profit and compare it with the "
             "original result. Then calculate the revenue growth required to achieve £900,000 operating profit if the "
             "variable-cost percentage remains 45% and the new fixed costs stay unchanged.")

# The expected results, from the request's own figures.
REVENUE, VARIABLE_SHARE, FIXED = 2_400_000, 0.45, 780_000
CONTRIBUTION = REVENUE * (1 - VARIABLE_SHARE)                      # 1,320,000
PROFIT = CONTRIBUTION - FIXED                                      # 540,000
BREAK_EVEN = FIXED / (1 - VARIABLE_SHARE)                          # 1,418,181.82
NEW_REVENUE = REVENUE * 1.12                                       # 2,688,000
NEW_FIXED = FIXED + 60_000                                         # 840,000
NEW_PROFIT = NEW_REVENUE * (1 - VARIABLE_SHARE) - NEW_FIXED        # 638,400
TARGET_REVENUE = (900_000 + NEW_FIXED) / (1 - VARIABLE_SHARE)      # 3,163,636.36

ANSWER = ("Variable costs = £2,400,000 × 0.45 = £1,080,000\n"
          "Contribution = £2,400,000 − £1,080,000 = £1,320,000\n"
          "Operating profit = £1,320,000 − £780,000 = £540,000\n"
          "Contribution margin = £1,320,000 ÷ £2,400,000 = 0.55, or 55%\n"
          "Break-even revenue = £780,000 ÷ 0.55 = £1,418,181.82")
RECEIPTS = [("2400000*0.45", "1080000"), ("2400000-1080000", "1320000"), ("1320000-780000", "540000"),
            ("1320000/2400000", "0.55"), ("780000/0.55", "1418181.82")]

FOLLOW_UP_ANSWER = (
    "Revised revenue = £2,400,000 × 1.12 = £2,688,000\n"
    "Variable costs = £2,688,000 × 0.45 = £1,209,600\n"
    "Contribution = £2,688,000 − £1,209,600 = £1,478,400\n"
    "Fixed operating costs = £780,000 + £60,000 = £840,000\n"
    "Revised operating profit = £1,478,400 − £840,000 = £638,400\n\n"
    "| Scenario | Operating profit |\n| --- | --- |\n| Original | £540,000 |\n| Revised | £638,400 |\n\n"
    "The revised operating profit is £98,400 higher than the original, an increase of 18.22%.\n\n"
    "Required contribution = £900,000 + £840,000 = £1,740,000\n"
    "Required revenue = £1,740,000 ÷ 0.55 = £3,163,636.36\n"
    "Required revenue growth = (£3,163,636.36 − £2,400,000) ÷ £2,400,000 = 31.82%")
FOLLOW_UP_RECEIPTS = [("2400000*1.12", "2688000"), ("2688000*0.45", "1209600"), ("2688000-1209600", "1478400"),
                      ("780000+60000", "840000"), ("1478400-840000", "638400"), ("900000+840000", "1740000"),
                      ("1740000/0.55", "3163636.36")]


def receipts(pairs):
    return [{"calculation_id": f"calc-{i}", "formula_version": "expression-evaluator-1.0",
             "expression": expression, "result": result} for i, (expression, result) in enumerate(pairs, 1)]


def history():
    return [ConversationMessage(role="user", content=FORECAST), ConversationMessage(role="assistant", content=ANSWER)]


class _Args(BaseModel):
    expression: str = ""


def calculator() -> ToolRegistry:
    async def calculate(args):
        assert re.fullmatch(r"[\d.+\-*/() ]+", args.expression)
        value = f"{round(eval(args.expression), 2):.2f}".rstrip("0").rstrip(".")  # digits and operators only
        return ToolResult(ok=True, content=f"{args.expression} = {value} (computed by the application, verified)")
    registry = ToolRegistry()
    registry.register(ToolSpec(name="calculate", version="1", description="calculate", args_model=_Args,
                               handler=calculate, data_source="t", risk_level="low", timeout_seconds=1.0))
    return registry


CALLS = [_call("calculate", {"expression": e}, f"c{i}") for i, (e, _) in enumerate(RECEIPTS, 1)]
GAP_ONLY = "**Contribution**\nThe sources provided do not state this.\n\n**Operating profit**\nThe sources provided do not state this."


# 1. A self-contained forecast answers without research.
def test_the_forecast_is_a_self_contained_calculation_not_a_lookup():
    assert not needs_lookup(FORECAST) and is_self_contained_calculation(FORECAST)
    # "current" still asks for today's position when it names an external fact.
    for lookup in ("What is the current UK VAT rate?", "What is the current price of Apple shares?",
                   "What is Tesla's current revenue?", FORECAST + " Then apply the current UK corporation tax rate."):
        assert needs_lookup(lookup), lookup


async def test_a_skipped_calculation_answered_as_missing_sources_is_sent_back_to_the_calculator():
    client = ScriptedClient([_reply(GAP_ONLY), _reply(tool_calls=CALLS), _reply(ANSWER)])
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt=FORECAST, registry=calculator(),
                              granted_permissions=frozenset(), planned_tools=("calculate",))
    reminder = client.requests[1]["messages"][-1]["content"]
    assert "supplies the figures" in reminder and "calculate" in reminder
    assert [c.tool for c in outcome.tool_calls] == ["calculate"] * 5 and outcome.text == ANSWER


async def test_the_reminder_is_only_for_a_planned_calculation():
    # A research question whose evidence is genuinely missing keeps its gap answer.
    client = ScriptedClient([_reply(GAP_ONLY)])
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt="What is the UK VAT threshold?",
                              registry=calculator(), granted_permissions=frozenset(), planned_tools=())
    assert outcome.text == GAP_ONLY and len(client.requests) == 1


async def test_the_forecast_is_released_complete_without_any_search(pipeline, monkeypatch):
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(service, "web_search_each", search)
    pipeline.answers(AgentOutcome(text=ANSWER, calculation_receipts=receipts(RECEIPTS)))
    response, audited = await pipeline.ask(FORECAST)
    assert response.outcome == "answered" and "do not establish" not in response.answer.text
    assert response.answer.completeness == "complete" and not search.await_count
    assert not pipeline.agent.await_args.kwargs["require_evidence"]


# 2. The results match the inputs.
async def test_the_released_figures_are_the_ones_the_inputs_produce(pipeline):
    pipeline.answers(AgentOutcome(text=ANSWER, calculation_receipts=receipts(RECEIPTS)))
    response, _ = await pipeline.ask(FORECAST)
    for value in (REVENUE * VARIABLE_SHARE, CONTRIBUTION, PROFIT):
        assert f"£{value:,.0f}" in response.answer.text
    assert f"£{BREAK_EVEN:,.2f}" in response.answer.text and "55%" in response.answer.text


async def test_a_figure_the_inputs_do_not_produce_is_withheld(pipeline):
    wrong = ANSWER.replace("£1,418,181.82", "£1,560,000.00")
    pipeline.answers(AgentOutcome(text=wrong, calculation_receipts=receipts(RECEIPTS)))
    response, audited = await pipeline.ask(FORECAST)
    # An equation that does not hold is never released: it goes to review.
    assert response.outcome == audited.outcome != "answered"
    assert response.answer is None or "£1,560,000" not in response.answer.text


# 3. The scenario comparison and target-profit calculation are included.
def test_comparison_figures_derive_from_verified_results_however_long_the_conversation():
    # Evidence over the pairwise limit, as the live follow-up's was (165+
    # numbers); the pipeline test below reproduces that failure end to end.
    evidence = FOLLOW_UP + "\n" + ANSWER + "\n" + "7 " * 70
    calculator_results = "\n".join(f"{e} = {r}" for e, r in FOLLOW_UP_RECEIPTS)
    # As the live answers write it: each comparison beside the figures it compares.
    shown = ("Profit rises from £540,000 to £638,400, by £98,400 (18.22%). Required revenue of £3,163,636.36 "
             "is 31.82% above £2,400,000.")
    assert unreconciled_figures(shown, evidence, calculator_results) == []
    # Still bounded: a figure no pair of verified numbers produces is withheld.
    assert unreconciled_figures("Profit rises by £123,457.", evidence, calculator_results) == ["£123,457"]
    # Since 2026-10-17 a comparison with no operand on the page must be a
    # calculator result: summed across the prompt, chance matches passed 84%
    # of fabricated figures.
    assert unreconciled_figures("Profit rises by £98,400.", evidence, calculator_results) == ["£98,400"]


def test_the_previous_answers_figures_are_read_from_the_escaped_conversation():
    # Historical prompts used ASCII-escaped JSON. New prompts retain Unicode
    # to save space; reconciliation must still understand stored old prompts.
    from app.orchestration.conversation import conversation_prompt
    evidence = FOLLOW_UP + conversation_prompt(history()).replace('£', '\\u00a3') + "\n" + "7 " * 70
    assert "\\u00a3540,000" in evidence
    calculator_results = "1478400 - 840000 = 638400"
    # £540,000 is only in the escaped conversation: read wrongly, it is unverified.
    assert unreconciled_figures("Profit rises from £540,000 to £638,400, by £98,400.", evidence,
                                calculator_results) == []


def test_the_target_profit_condition_is_not_judged_as_arithmetic():
    from app.orchestration.calculation_service import validate_answer_calculations
    assert validate_answer_calculations("Required revenue × (1 − 0.45) − £840,000 = £900,000") == []
    # Wrong arithmetic beside a named formula is still caught.
    assert validate_answer_calculations("Profit = Revenue − Costs = £2,400,000 − £1,860,000 = £640,000")


async def test_the_follow_up_releases_the_comparison_and_the_required_growth(pipeline):
    pipeline.answers(AgentOutcome(text=FOLLOW_UP_ANSWER, calculation_receipts=receipts(FOLLOW_UP_RECEIPTS)))
    response, audited = await pipeline.ask(FOLLOW_UP, history())
    text = response.answer.text
    assert f"£{NEW_PROFIT:,.0f}" in text and "£98,400" in text and "18.22%" in text
    assert f"£{TARGET_REVENUE:,.2f}" in text and "31.82%" in text
    assert response.answer.completeness == audited.completeness == "complete"


# 4. The results survive a model timeout.
async def test_a_model_timeout_after_the_forecast_calculations_keeps_them():
    outcome = await run_agent(FailingAfter([_reply(tool_calls=CALLS)], asyncio.TimeoutError()), model="m",
                              system_prompt="", user_prompt=FORECAST, registry=calculator(),
                              granted_permissions=frozenset(), planned_tools=("calculate",))
    assert outcome.incomplete_reason and outcome.stop_reason == "time_budget"
    for line in ("1320000-780000 = 540000", "780000/0.55 = 1418181.82"):
        assert line in outcome.text


# 5. Missing external facts are disclosed without suppressing arithmetic.
async def test_a_missing_tax_rate_is_disclosed_and_the_forecast_working_is_kept(pipeline):
    question = FORECAST.replace(" Ignore interest, tax and depreciation for this simplified model.", "") \
        + " Then apply the current UK corporation tax rate."
    text = ANSWER + "\n\nThe sources provided do not state the current UK corporation tax rate."
    pipeline.answers(AgentOutcome(text=text, calculation_receipts=receipts(RECEIPTS)))
    response, audited = await pipeline.ask(question)
    assert "Operating profit = £1,320,000 − £780,000 = £540,000" in response.answer.text
    assert "do not state the current UK corporation tax rate" in response.answer.text
    assert response.answer.completeness == audited.completeness == "partial"


# 6. Unsupported tax, legal or accounting claims stay blocked.
async def test_an_unsourced_tax_claim_is_not_released_beside_the_forecast():
    calculated = calculated_figures(None, question=FORECAST, receipts=receipts(RECEIPTS))
    claim = "UK corporation tax is charged at 25% on profits above £250,000."
    check = await verify_for_release(ANSWER + "\n" + claim, question=FORECAST + " Apply the current tax rate.",
                                     evidence=[], requires_authority=True, calculated=calculated)
    assert not check.passed


async def test_an_invented_tax_figure_in_a_self_contained_forecast_is_withheld(pipeline):
    text = ANSWER + "\nAfter corporation tax at 19%, profit would be £437,400."
    pipeline.answers(AgentOutcome(text=text, calculation_receipts=receipts(RECEIPTS)))
    response, audited = await pipeline.ask(FORECAST)
    assert "corporation tax" not in response.answer.text and "£437,400" not in response.answer.text
    assert "Operating profit = £1,320,000 − £780,000 = £540,000" in response.answer.text
    assert response.answer.completeness == audited.completeness == "partial"


async def test_a_tax_rate_the_user_supplied_is_arithmetic_and_kept(pipeline):
    question = "Operating profit is £540,000 and corporation tax is 25% of it. Calculate profit after tax."
    text = "Corporation tax = £540,000 × 0.25 = £135,000\nProfit after tax = £540,000 − £135,000 = £405,000"
    pipeline.answers(AgentOutcome(text=text, calculation_receipts=receipts(
        [("540000*0.25", "135000"), ("540000-135000", "405000")])))
    response, audited = await pipeline.ask(question)
    assert "£135,000" in response.answer.text and "£405,000" in response.answer.text
    assert response.answer.completeness == audited.completeness == "complete"


# 7. Earlier-scenario figures cannot leak in.
def test_an_earlier_scenario_is_not_used_for_the_follow_up():
    earlier = [ConversationMessage(role="user", content="Revenue is £1,500,000 and costs are £1,100,000. Profit?"),
               ConversationMessage(role="assistant", content="Profit = £1,500,000 − £1,100,000 = £400,000"),
               *history()]
    result = change_followup(FOLLOW_UP, earlier)
    assert result is None or not any(i.value in (1_500_000, 1_100_000) for i in result.inputs or [])
    verified = calculated_figures(None, question=FOLLOW_UP, receipts=receipts(FOLLOW_UP_RECEIPTS))
    assert not {"1500000.00", "400000.00"} & (verified.results | verified.inputs)


# 8. The answer, verification result and audit status agree.
async def test_answer_verification_and_audit_status_agree(pipeline):
    pipeline.answers(AgentOutcome(text=ANSWER, calculation_receipts=receipts(RECEIPTS)))
    response, audited = await pipeline.ask(FORECAST)
    assert response.outcome == audited.outcome == "answered"
    assert response.answer.completeness == audited.completeness == "complete"
    assert page_status(response) == "Answered" and not any("No factual answer" in i for i in response.answer.limitations)


def test_a_revenue_form_break_even_is_not_asked_for_a_unit_price():
    # 2026-10-17: "revenue £2,400,000, variable costs 45% of revenue, fixed
    # costs £780,000 … break-even revenue" was answered "Please provide:
    # selling price, variable cost". It escaped only when worded with
    # "current", which happened to route it on.
    from app.orchestration.calculations.engine import calculate_from_query
    plain = ("Our annual revenue is £2,400,000, variable costs are 45% of revenue, fixed costs are £780,000. Calculate "
             "contribution, operating profit, contribution margin and break-even revenue. Show the formulas.")
    assert calculate_from_query(plain).status != "clarification_required"
    # The unit form is still the calculator's.
    unit = calculate_from_query("Selling price £25, variable cost £15 per unit, fixed costs £10,000. Break-even units?")
    assert unit.status == "success" and unit.outputs[1].name == "break_even_units"
    assert calculate_from_query("What is the break-even point?").status == "clarification_required"
