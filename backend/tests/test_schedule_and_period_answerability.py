"""Worked schedules and period comparisons on the user's own figures.

Traced 2026-10-17 with the real model and a faked database:

- IFRS 15 (qry-04252db473fe): the model wrote "£2 000" (narrow no-break
  space grouping), read as £2, and cited [REF-1] on calculator rows, so every
  schedule row was removed and the answer kept an empty table.
- Financial performance (qry-f7c7ad8f72ff): "for the current year … and the
  previous financial year using the figures provided" was read as a lookup of
  today's rates, so the analysis needed citations and was answered "no factual
  answer verified"; forced to search first, it then ran out of steps.
- Pruning one sentence marked an untouched title "The sources provided do not
  confirm this." and an honest "(no tax rate or provision given)" was removed.

Model output is scripted; nothing depends on a live model."""
import json

from app.domains.model_gateway.agent import AgentOutcome, run_agent
from app.orchestration import service
from app.orchestration.calculation_service import is_self_contained_calculation, needs_lookup
from app.orchestration.figure_reconciliation import material_figures, unreconciled_figures
from app.orchestration.verification_service import (
    calculated_figures, prune_rejected_claims, unbind_calculated_rows, unsourced_rule_statements, verify_for_release,
)
from tests.test_agent_loop import ScriptedClient, _call, _reply
from tests.test_answer_status_pipeline import pipeline  # noqa: F401 — full-pipeline fixture
from tests.test_operating_forecast_answerability import calculator

CONTRACT = ("Our software company entered into a 12-month customer contract on 1 October 2025. The customer paid "
            "£24,000 upfront. There is also a separate implementation service; the implementation fee is £6,000. "
            "Explain how IFRS 15 applies and provide a worked schedule.")
SCHEDULE = """| Period ending | Subscription | Cumulative | Contract liability | Implementation |
|---|---|---|---|---|
| 31 Oct 2025 | £2 000 [REF-1] | £2 000 | £22 000 | – |
| 30 Nov 2025 | £2 000 | £4 000 | £20 000 | – (assessment pending) |
| 31 Dec 2025 | £2 000 [REF-1] | £6 000 | £18 000 | – |
| Implementation | – | – | – | £6,000 if distinct, at a point in time [REF-7] |"""

FINANCIALS = (
    "I am the finance manager of a UK-based manufacturing company, and I need a detailed financial perfor"
    "mance analysis for our management meeting.\n\nFor the financial year ended 31 March 2026, our figures "
    "were:\n- Sales revenue: £1,250,000\n- Sales returns: £35,000\n- Cost of goods sold: £710,000\n- Salaries"
    " and wages: £165,000\n- Rent and utilities: £48,000\n- Marketing expenses: £32,000\n- Administrative ex"
    "penses: £41,000\n- Depreciation: £28,000\n- Interest expense: £14,000\n\nFor the previous financial year"
    ", net sales were £1,100,000, cost of goods sold was £660,000, and operating expenses excluding inter"
    "est were £285,000.\n\nPlease calculate net sales, gross profit, gross margin, operating expenses, oper"
    "ating profit, operating margin, and profit before tax for the current year. Calculate the same compa"
    "rable gross profit, gross margin, operating profit and operating margin for the previous year using "
    "the figures provided.\n\nThen calculate the year-on-year changes in revenue, gross profit, operating p"
    "rofit, and margins. Explain which areas improved or deteriorated, identify any figures that cannot b"
    "e confirmed from the information supplied, and give five practical management recommendations.\n\nFina"
    "lly, present a comparison table and a chart showing the current and previous year's gross and operat"
    "ing margins. Do not invent missing figures or treat recommendations as established facts.")


def contract_figures():
    return calculated_figures(None, question=CONTRACT, receipts=[{"expression": "24000/12", "result": "2000"}])


# Space-grouped thousands are read as the amount written.
def test_space_grouped_amounts_are_read_whole():
    assert [value for _, value in material_figures("£2 000 and £18 000, £1 418 181.82")] == [
        2000.0, 18000.0, 1418181.82]
    assert material_figures("12 months from 1 October 2025") == []           # dates and counts are not grouped
    # The gate now checks £18,000 itself, not "£18".
    assert unreconciled_figures("Remaining £18 000.", "Paid 24,000; recognised 6,000.") == []
    assert unreconciled_figures("Remaining £17 500.", "Paid 24,000; recognised 6,000.") == ["£17,500"]


# A schedule of calculator figures is released; a treatment claim is still checked.
def test_schedule_rows_of_calculated_figures_lose_their_research_citations():
    released = unbind_calculated_rows(SCHEDULE, contract_figures())
    assert "[REF-1]" not in released                                          # the calculator is their source
    assert "£6,000 if distinct, at a point in time [REF-7]" in released       # a treatment claim keeps its citation


async def test_a_running_balance_schedule_passes_the_release_check():
    calculated = contract_figures()
    rows = "\n".join(SCHEDULE.splitlines()[:5])                               # the calculator rows only
    check = await verify_for_release(unbind_calculated_rows(rows, calculated), question=CONTRACT,
                                     evidence=["[REF-1] IFRS 15 contract liabilities"], requires_authority=True,
                                     calculated=calculated)
    assert check.passed


async def test_a_schedule_figure_no_verified_figure_produces_still_fails():
    calculated = contract_figures()
    row = "| 30 Nov 2025 | £2,000 | £7,777 | £20,000 | – |"
    assert unbind_calculated_rows(row + " [REF-1]", calculated).endswith("[REF-1]")
    check = await verify_for_release(row, question=CONTRACT, evidence=[], requires_authority=True,
                                     calculated=calculated)
    assert not check.passed


# A planned calculation worked by hand is sent back to the calculator once.
async def test_hand_worked_arithmetic_is_sent_to_the_calculator():
    by_hand = "Monthly revenue = £24,000 ÷ 12 = £2,000"
    client = ScriptedClient([_reply(by_hand), _reply(tool_calls=[_call("calculate", {"expression": "24000/12"})]),
                             _reply(by_hand)])
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt=CONTRACT, registry=calculator(),
                              granted_permissions=frozenset(), planned_tools=("calculate",))
    assert "computed without the calculator" in client.requests[1]["messages"][-1]["content"]
    assert [c.tool for c in outcome.tool_calls] == ["calculate"] and outcome.text == by_hand


async def test_hand_working_is_not_questioned_when_no_calculation_was_planned():
    client = ScriptedClient([_reply("Monthly revenue = £24,000 ÷ 12 = £2,000")])
    await run_agent(client, model="m", system_prompt="", user_prompt=CONTRACT, registry=calculator(),
                    granted_permissions=frozenset(), planned_tools=("search_web",))
    assert len(client.requests) == 1


# "Current year" beside the user's own prior-year figures is a label.
def test_a_comparison_of_the_users_own_years_is_self_contained():
    assert not needs_lookup(FINANCIALS) and is_self_contained_calculation(FINANCIALS)
    for lookup in ("What is the VAT threshold for the current year compared with the previous year?",
                   "Compare the personal allowance for the current and previous year.",
                   "What is the personal allowance for the current year?"):
        assert needs_lookup(lookup), lookup


async def test_a_self_contained_analysis_is_not_forced_to_search_first(pipeline):
    pipeline.answers(AgentOutcome(text="Gross profit = £1,215,000 − £710,000 = £505,000"))
    await pipeline.ask(FINANCIALS)
    assert pipeline.agent.await_args.kwargs["require_evidence"] is False


def test_a_calculation_heavy_request_gets_more_steps_but_a_bounded_tool_cap():
    assert service.deliverable_step_allowance(FINANCIALS) == 8
    assert service.deliverable_step_allowance("Calculate gross margin on £100 and £60.") == 0


# Removals mark only what they emptied, and keep disclosures of missing facts.
def test_only_a_heading_the_removal_emptied_is_marked():
    answer = ("**Analysis**\n\n**1. Net sales**\nNet sales = £1,250,000 − £35,000 = £1,215,000\n\n"
              "**Tax**\nCorporation tax is 25%.\n\n**End**\nDone.")
    pruned = prune_rejected_claims(answer, ["Corporation tax is 25%."])
    assert pruned.startswith("**Analysis**\n\n**1. Net sales**")             # the title was already empty
    assert "**Tax**\nThe sources provided do not confirm this." in pruned


def test_a_disclosure_that_a_tax_figure_is_missing_is_kept():
    calculated = calculated_figures(None, question=FINANCIALS, receipts=[])
    kept = "- Tax expense and net profit after tax (no tax rate or provision given)."
    added = "5. Evaluate available reliefs (e.g., R&D tax credits, capital allowances) to lower the tax charge."
    assert unsourced_rule_statements(kept + "\n" + added, calculated) == [added]


def test_the_stored_questions_are_as_traced():
    # The traced prompts are the user's stored questions; keep the fixtures honest.
    assert "previous financial year" in FINANCIALS and "current year" in FINANCIALS
    assert json.dumps(SCHEDULE).count("\\u202f") == 9
