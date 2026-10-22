"""Selective withholding, and balances built on unsupported premises.

One unverifiable figure used to replace the whole written answer with the
calculator's bare working; it now removes only the statement or table row
that states it, and says so. A contract liability built from a fee the
question never said was paid (the IFRS 15 schedule of 2026-10-17: £28,000,
£26,000, £24,000 from an assumed £30,000) is not reported as a balance,
however correct its arithmetic. Model output is scripted throughout."""
from types import SimpleNamespace as N

from app.domains.model_gateway.agent import AgentOutcome, run_agent
from app.orchestration.claim_verification import FIGURES_REMOVED_NOTE
from app.orchestration.figure_reconciliation import statements_with_figures, unreconciled_figures
from app.orchestration.verification_service import (
    BALANCE_NOT_ESTABLISHED, calculated_figures, prune_rejected_claims, received_consideration,
    unbind_calculated_rows, unsupported_balances, verify_for_release,
)
from tests.test_agent_loop import ScriptedClient, _call, _reply
from tests.test_answer_status_pipeline import page_status, pipeline  # noqa: F401 — full-pipeline fixture
from tests.test_operating_forecast_answerability import calculator
from tests.test_schedule_and_period_answerability import FINANCIALS
from tests.test_statement_removal_audit import ask, entries, verifier  # noqa: F401 — audit-capturing fixtures

QUESTION = ("For the year, sales were £1,215,000 and cost of goods sold £710,000. Last year net sales were "
            "£1,100,000, cost of goods sold £660,000 and operating expenses £285,000. Calculate gross profit for "
            "both years and last year's operating profit.")
CALCS = [_call("calculate", {"expression": "1215000-710000"}, "c1")]
VALID = ("**Gross profit**\nGross profit = £1,215,000 − £710,000 = £505,000.\n\n"
         "| Year | Net sales | Gross profit |\n|---|---|---|\n| Current | £1,215,000 | £505,000 |\n")

CONTRACT = ("Our software company entered into a 12-month customer contract on 1 October 2025. The customer paid "
            "£24,000 upfront. There is also a separate implementation service. The implementation fee is £6,000, "
            "and the implementation work was completed on 31 October 2025. Provide a worked schedule.")
RECEIPTS = [{"expression": "24000/12", "result": "2000"}, {"expression": "2000*3", "result": "6000"}]
ASSUMED_SCHEDULE = (
    "Monthly subscription revenue = £24,000 ÷ 12 = £2,000. Revenue for the quarter = £2,000 × 3 = £6,000.\n\n"
    "| Period | Subscription recognised | Contract liability (unearned) |\n| --- | --- | --- |\n"
    "| Oct 2025 | £2,000 | £28,000 |\n| Nov 2025 | £2,000 | £26,000 |\n| Dec 2025 | £2,000 | £24,000 |\n\n"
    "The contract liability at 1 October 2025 was £30,000.")
SUPPORTED_SCHEDULE = (
    "| Period | Subscription recognised | Contract liability |\n| --- | --- | --- |\n"
    "| Oct 2025 | £2,000 | £22,000 |\n| Nov 2025 | £2,000 | £20,000 |\n| Dec 2025 | £2,000 | £18,000 |")

FINANCIAL_RECEIPTS = [
    {"calculation_id": f"c{i}", "formula_version": "expression-evaluator-1.0", "expression": e, "result": r}
    for i, (e, r) in enumerate((("1250000-35000", "1215000"), ("1215000-710000", "505000")), 1)]


async def agent_answer(text: str):
    client = ScriptedClient([_reply(tool_calls=CALCS), _reply(text), _reply(text)])
    return await run_agent(client, model="m", system_prompt="", user_prompt=QUESTION, registry=calculator(),
                           granted_permissions=frozenset(), planned_tools=("calculate",))


# One unsupported row alongside valid calculation rows.
async def test_one_unsupported_row_is_removed_and_the_valid_rows_stay():
    outcome = await agent_answer(VALID + "| Prior | £1,100,000 | £123,457 |\n")
    assert "£123,457" not in outcome.text and "| Current | £1,215,000 | £505,000 |" in outcome.text
    assert "| Year | Net sales | Gross profit |" in outcome.text                 # the table heading survives
    assert outcome.removed_statements == ["| Prior | £1,100,000 | £123,457 |"]
    assert outcome.unreconciled_figures == ["£123,457"]


# One unsupported sentence alongside a supported explanation.
async def test_one_unsupported_sentence_is_removed_and_the_explanation_stays():
    outcome = await agent_answer(VALID + "\nGross profit rose because costs fell. A rebate added £77,777.")
    assert "Gross profit rose because costs fell." in outcome.text and "£77,777" not in outcome.text
    assert "Gross profit = £1,215,000 − £710,000 = £505,000." in outcome.text


# Multiple unsupported claims without suppressing the entire answer.
async def test_several_unsupported_figures_do_not_suppress_the_answer():
    outcome = await agent_answer(VALID + "\nMarketing cost £31,313.\n\n**Outlook**\nNext year sales reach £2,222,222.")
    assert "£31,313" not in outcome.text and "£2,222,222" not in outcome.text
    assert "£505,000" in outcome.text and len(outcome.removed_statements) == 2
    # The emptied heading says what happened, not a generic evidence refusal.
    assert f"**Outlook**\n{FIGURES_REMOVED_NOTE}" in outcome.text
    assert "do not confirm" not in outcome.text


async def test_with_nothing_verified_left_the_answer_is_still_withheld():
    outcome = await agent_answer("**Outlook**\nNext year sales reach £2,222,222.")
    assert outcome.text.startswith("The answer included figures that could not be matched")
    assert outcome.removed_statements == []


def test_comparison_figures_chained_on_the_answers_own_derived_figures_are_accepted():
    evidence = "Last year net sales 1,100,000; cost of goods sold 660,000; operating expenses 285,000."
    shown = "Prior gross profit £440,000; prior operating profit £155,000."
    assert unreconciled_figures(shown, evidence) == []            # 440,000 = 1,100,000 − 660,000, then − 285,000
    assert unreconciled_figures("Prior operating profit £155,001.", evidence) == ["£155,001"]


def test_each_statement_carrying_a_figure_is_found_verbatim():
    text = "Gross profit is £505,000. Prior profit was £123,457.\n| Prior | £123,457 |"
    assert statements_with_figures(text, ["£123,457"]) == ["Prior profit was £123,457.", "| Prior | £123,457 |"]


# Correct partial-answer status and audit consistency.
async def test_a_selective_removal_is_partial_named_and_audited(ask):
    response, audited, payload = await ask(
        VALID, sources=(), question=FINANCIALS, unreconciled_figures=["£123,457"],
        removed_statements=["| Prior | £1,100,000 | £123,457 |"], calculation_receipts=FINANCIAL_RECEIPTS)
    limitation = next(item for item in response.answer.limitations if "removed" in item)
    assert limitation.startswith("Incomplete answer: 1 statement stating this figure") and "£123,457" in limitation
    assert "The rest of the answer is shown." in limitation and "£505,000" in response.answer.text
    [removed] = entries(payload, "figure_reconciliation")
    assert removed["reason_code"] == "figure_unreconciled" and "£123,457" in removed["excerpt"]
    assert payload["completeness"] == audited.completeness == response.answer.completeness == "partial"
    assert page_status(response) == "Partially answered"


async def test_the_release_figure_gate_also_removes_selectively(pipeline):
    # The agent's own gate is mocked away here: the service's gate catches it.
    pipeline.answers(AgentOutcome(text=VALID + "\nA rebate added £61,803.39.", calculation_receipts=FINANCIAL_RECEIPTS))
    response, audited = await pipeline.ask(FINANCIALS)
    assert "£61,803.39" not in response.answer.text and "£505,000" in response.answer.text
    assert response.answer.completeness == audited.completeness == "partial"
    assert any("£61,803.39" in item and "removed" in item for item in response.answer.limitations)


# Unsupported assumptions feeding otherwise correct arithmetic.
def test_a_calculator_operand_the_user_never_gave_does_not_verify_its_result():
    figures = calculated_figures(None, question=CONTRACT, receipts=[*RECEIPTS, {"expression": "37500-2000",
                                                                                "result": "35500"}])
    assert figures.assumed == ["37500-2000"] and "35500.00" not in figures.results
    assert "2000.00" in figures.results and "6000.00" in figures.results     # the traceable ones still verify


def test_only_amounts_stated_as_paid_are_received():
    assert received_consideration(CONTRACT) == [24000.0]                      # the £6,000 fee is a price


def test_a_liability_built_on_an_unpaid_fee_is_not_reported():
    text, flagged = unsupported_balances(ASSUMED_SCHEDULE, CONTRACT, calculated_figures(None, question=CONTRACT,
                                                                                      receipts=RECEIPTS))
    assert flagged == ["£28,000", "£26,000", "£30,000"]                       # £24,000 alone is what was paid
    assert "| Oct 2025 | £2,000 |" in text and BALANCE_NOT_ESTABLISHED in text   # the revenue column stays
    assert "£30,000" not in text and "Revenue for the quarter = £2,000 × 3 = £6,000." in text


def test_a_liability_the_payment_supports_is_kept():
    # As in the service: the schedule is read top to bottom first, so the
    # cumulative £4,000 behind £20,000 (24,000 − 4,000) is known.
    calculated = calculated_figures(None, question=CONTRACT, receipts=RECEIPTS)
    schedule = SUPPORTED_SCHEDULE.replace("| Contract liability |", "| Cumulative | Contract liability |").replace(
        "| --- | --- | --- |", "| --- | --- | --- | --- |").replace("| £2,000 | £22,000 |", "| £2,000 | £2,000 | £22,000 |"
        ).replace("| £2,000 | £20,000 |", "| £2,000 | £4,000 | £20,000 |").replace("| £2,000 | £18,000 |", "| £2,000 | £6,000 | £18,000 |")
    text, flagged = unsupported_balances(unbind_calculated_rows(schedule, calculated), CONTRACT, calculated)
    assert flagged == [] and "£22,000" in text and "£20,000" in text and "£18,000" in text


def test_with_no_stated_payment_no_liability_is_established():
    _, flagged = unsupported_balances("The contract liability is £5,000.", "A customer signed a £5,000 contract.",
                                      calculated_figures(None, question="", receipts=[]))
    assert flagged == ["£5,000"]


async def test_the_ifrs_schedule_keeps_its_subscription_figures_and_says_what_is_unresolved(pipeline):
    pipeline.answers(AgentOutcome(text=ASSUMED_SCHEDULE, calculation_receipts=RECEIPTS))
    response, audited = await pipeline.ask(CONTRACT)
    text = response.answer.text
    assert "£2,000" in text and "£6,000" in text and "£28,000" not in text and "£30,000" not in text
    note = next(item for item in response.answer.limitations if "contract-liability balance" in item)
    assert "consideration received or due" in note and "remain unresolved" in note
    assert response.answer.completeness == audited.completeness == "partial"


async def test_the_premise_removal_is_audited_with_its_own_reason(ask):
    _, _, payload = await ask(ASSUMED_SCHEDULE, sources=(), question=CONTRACT, calculation_receipts=RECEIPTS)
    reasons = {item["reason_code"] for item in entries(payload, "premise_validation")}
    assert reasons == {"unsupported_premise"}


# Verified calculations are kept when the claims beside them have no source.
async def test_no_evidence_prunes_the_claims_and_keeps_the_calculation():
    calculated = calculated_figures(None, question=QUESTION, receipts=[{"expression": "1215000-710000",
                                                                       "result": "505000"}])
    answer = "Gross profit = £1,215,000 − £710,000 = £505,000.\nUK corporation tax is charged at 25% on this profit."
    check = await verify_for_release(answer, question=QUESTION + " Apply UK tax.", evidence=[],
                                     requires_authority=True, calculated=calculated)
    assert not check.passed and check.prunable
    assert check.rejected_claims == ["UK corporation tax is charged at 25% on this profit."]
    pruned = prune_rejected_claims(answer, check.rejected_claims)
    recheck = await verify_for_release(pruned, question=QUESTION + " Apply UK tax.", evidence=[],
                                       requires_authority=True, calculated=calculated)
    assert recheck.passed and "£505,000" in pruned and "25%" not in pruned


# Token exhaustion after verified calculations.
async def test_token_exhaustion_after_verified_calculations_keeps_them():
    def costly(reply):
        reply.usage = N(total_tokens=200_000)
        return reply
    # The first calculation runs; the second request comes back over budget.
    client = ScriptedClient([_reply(tool_calls=CALCS), costly(_reply(tool_calls=[_call(
        "calculate", {"expression": "1100000-660000"}, "c2")])), _reply(VALID)])
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt=QUESTION, registry=calculator(),
                              granted_permissions=frozenset(), planned_tools=("calculate",))
    assert outcome.stop_reason == "token_budget"
    assert "1215000-710000 = 505000" in outcome.text
    assert [c.tool for c in outcome.tool_calls] == ["calculate"]
    assert len(client.requests) == 2  # No paid final-answer call after exhaustion.


def test_a_straight_line_balance_worked_by_hand_is_supported():
    # Measured 2026-10-17: one calculator call (£6,000 for the quarter); the
    # monthly £2,000 was written by hand, and £22,000 / £20,000 were flagged.
    calculated = calculated_figures(None, question=CONTRACT, receipts=[{"expression": "24000/12*3", "result": "6000"}])
    text = "The contract liability is £22,000 after October, £20,000 after November and £18,000 after December."
    assert unsupported_balances(text, CONTRACT, calculated) == (text, [])
    # Still capped by what was received: the assumed £30,000 opening balance is not.
    assert unsupported_balances("The contract liability was £30,000.", CONTRACT, calculated)[1] == ["£30,000"]


async def test_a_heading_emptied_of_hand_worked_arithmetic_is_not_called_unsourced(ask):
    # FX, measured 2026-10-17: the budgeted sterling cost, worked by hand with
    # no calculator receipt, was pruned and its heading read "The sources
    # provided do not confirm this."
    from tests.test_ifrs15_release_stability import CLAIMS
    text = "\n".join(["**Budgeted cost**", "At the budget rate the sterling cost is £100,000.", "",
                      "**Treatment**", CLAIMS["contract liability"], CLAIMS["over time"]])
    response, _, _ = await ask(text)
    assert "£100,000" not in response.answer.text
    assert f"**Budgeted cost**\n{FIGURES_REMOVED_NOTE}" in response.answer.text
    assert "do not confirm" not in response.answer.text


def test_a_rule_statement_is_not_a_figure_statement():
    from app.orchestration.verification_service import is_figure_statement
    assert is_figure_statement("At the budget rate the sterling cost is £100,000.")
    assert not is_figure_statement("The UK VAT registration threshold is £90,000.")
    assert not is_figure_statement("Revenue is recognised over time.")
