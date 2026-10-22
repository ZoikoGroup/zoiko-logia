"""Adversarial checks of figure verification: chance arithmetic matches,
self-vouching figures, and verified figures in the wrong period or scenario.

Measured 2026-10-17 on the financial-performance evidence: the gate accepted
70–84% of fabricated figures. £77,777 was a running total of fourteen
unrelated numbers across the question and the prompt, divided by 100;
£48,213.57 was rent (£48,000) plus an instruction example's 122, inside the
fixed 0.2% tolerance. Every figure must now trace to the user's facts, a
source or the calculator, at the precision it is written to, by a formula
whose operands are verified."""
import random

from app.domains.model_gateway.agent import AGENT_TOOL_INSTRUCTIONS, AgentOutcome
from app.orchestration.figure_attribution import misattributed_figures
from app.orchestration.figure_reconciliation import tolerance_for, unreconciled_figures
from tests.test_answer_status_pipeline import pipeline  # noqa: F401 — full-pipeline fixture
from tests.test_operating_forecast_answerability import FORECAST, FOLLOW_UP
from tests.test_schedule_and_period_answerability import FINANCIALS
from tests.test_statement_removal_audit import ask, entries, verifier  # noqa: F401 — audit-capturing fixtures

CALCULATIONS = ("1250000-35000 = 1215000\n1215000-710000 = 505000\n505000/1215000*100 = 41.563786\n"
                "165000+48000+32000+41000+28000 = 314000\n505000-314000 = 191000")
# The question, the agent's own instructions (their numbers are the noise
# that produced chance matches) and the calculator's results.
EVIDENCE = FINANCIALS + "\n" + AGENT_TOOL_INSTRUCTIONS + "\n" + CALCULATIONS
ANSWER = ("Net sales £1,215,000; gross profit £505,000 (gross margin 41.56%). Operating expenses £314,000; "
          "operating profit £191,000 (operating margin 15.72%); profit before tax £177,000.\n"
          "Prior year: gross profit £440,000 (40.00%); operating profit £155,000 (14.09%).\n"
          "Gross profit rose £65,000 (14.77%); operating profit rose £36,000 (23.23%); "
          "gross margin +1.56 pp; operating margin +1.63 pp.")


def unverified(text: str) -> list[str]:
    return unreconciled_figures(text, EVIDENCE, CALCULATIONS, stated=FINANCIALS)


# ── Coincidental arithmetic matches ─────────────────────────────────────────

def test_every_figure_of_a_correct_analysis_is_verified():
    assert unverified(ANSWER) == []


def test_fabricated_figures_beside_a_correct_analysis_are_caught():
    rng = random.Random(7)
    fakes = ([f"£{rng.randint(10_000, 9_999_999):,}" for _ in range(100)]
             + [f"£{rng.uniform(1_000, 999_999):,.2f}" for _ in range(100)]
             + [f"{rng.uniform(0.5, 60):.2f}%" for _ in range(100)])
    accepted = [fake for fake in fakes if fake not in unverified(ANSWER + f" A further item is {fake}.")]
    assert len(accepted) <= 3, accepted                  # measured 2/300; before this change 240/300


def test_a_running_total_does_not_span_unrelated_lines():
    # Salaries … depreciation, interest, prior-year sales: summed, then ÷ 100.
    assert unverified("A one-off rebate of £77,777 was received.") == ["£77,777"]


def test_a_penny_figure_must_match_to_the_penny():
    assert tolerance_for("£48,213.57", 48213.57) < 0.01
    assert unverified("Rent and service charges came to £48,213.57.") == ["£48,213.57"]


def test_the_prompts_own_numbers_are_never_operands():
    # 48,000 (rent) + 122 (an instruction example) is exact arithmetic, and still unverified.
    assert unverified("Rent of £48,000 plus a fee makes £48,122.") == ["£48,122"]


def test_a_rounded_amount_in_millions_is_not_derived_by_chance():
    assert unverified("The total is about £4.8m.") == ["£4.8m"]        # £48,000 × 100 is not a fact
    assert unverified("Net sales were £1.215m.") == []                 # £1,215,000, restated in millions
    # The existing 0.2% bound is not loosened for a coarser display (as before this change).
    assert unverified("Net sales were £1.2m.") == ["£1.2m"]


def test_two_unverified_figures_cannot_vouch_for_each_other():
    evidence = "Revised profit 1478400 - 840000 = 638400"
    shown = "Profit rose from £540,000 to £638,400, by £98,400."
    assert unreconciled_figures(shown, evidence, "1478400 - 840000 = 638400") == ["£540,000", "£98,400"]


def test_a_worked_equation_on_verified_operands_is_verified_and_a_made_up_operand_is_not():
    facts = "Selling price £18 per unit, fixed costs £72,000. What profit would 6,000 units give?"
    assert unreconciled_figures("Profit = 6,000 × £18 − £72,000 = £36,000.", facts) == []
    assert unreconciled_figures("Profit = 6,000 × £19 − £72,000 = £42,000.", facts) == ["£19", "£42,000"]


# ── Cross-period leakage ────────────────────────────────────────────────────

PERIOD_TABLE = ("| Measure | Current year | Previous year | Change |\n|---|---|---|---|\n"
                "| Net sales | £1,215,000 | £1,100,000 | £115,000 |\n"
                "| Cost of goods sold | £710,000 | £660,000 | £50,000 |")
RECEIPTS = [{"calculation_id": "c1", "formula_version": "expression-evaluator-1.0",
             "expression": "1250000-35000", "result": "1215000"}]


def test_a_correct_two_period_table_is_not_flagged():
    assert misattributed_figures(PERIOD_TABLE, FINANCIALS, [], RECEIPTS) == []


def test_the_prior_years_figure_in_the_current_year_column_is_flagged():
    leaked = PERIOD_TABLE.replace("| £710,000 | £660,000 |", "| £660,000 | £660,000 |")
    [(row, figure, why)] = misattributed_figures(leaked, FINANCIALS, [], RECEIPTS)
    assert figure == "£660,000" and "prior period" in why and row.startswith("| Cost of goods sold")


def test_a_sentence_naming_one_period_with_the_others_figure_is_flagged():
    found = misattributed_figures("For the current year, cost of goods sold was £660,000.", FINANCIALS, [], RECEIPTS)
    assert [figure for _, figure, _ in found] == ["£660,000"]
    # A comparison naming both periods is not.
    assert misattributed_figures("Cost of goods sold rose from £660,000 last year to £710,000 this year.",
                                 FINANCIALS, [], RECEIPTS) == []


async def test_a_leaked_row_is_removed_audited_and_reported(ask):
    leaked = PERIOD_TABLE.replace("| £710,000 | £660,000 |", "| £660,000 | £660,000 |")
    response, audited, payload = await ask(leaked, sources=(), question=FINANCIALS, calculation_receipts=RECEIPTS)
    assert "| Net sales | £1,215,000 | £1,100,000 |" in response.answer.text
    assert "| Cost of goods sold | £660,000 | £660,000 |" not in response.answer.text
    [removed] = entries(payload, "figure_attribution")
    assert removed["reason_code"] == "figure_misattributed"
    assert any("wrong period or scenario" in item for item in response.answer.limitations)
    assert response.answer.completeness == audited.completeness == "partial"


# ── Cross-scenario leakage ──────────────────────────────────────────────────

SCENARIO_RECEIPTS = [{"expression": "780000+60000", "result": "840000"},
                     {"expression": "2400000*1.12", "result": "2688000"}]
SCENARIO_TABLE = ("| Item | Original | Revised |\n|---|---|---|\n| Revenue | £2,400,000 | £2,688,000 |\n"
                  "| Fixed operating costs | £780,000 | £840,000 |\n| Variable-cost % | 45% | 45% |")


def test_a_correct_scenario_comparison_is_not_flagged():
    assert misattributed_figures(SCENARIO_TABLE, FOLLOW_UP, [FORECAST], SCENARIO_RECEIPTS) == []


def test_the_original_fixed_costs_in_the_revised_scenario_are_flagged():
    leaked = SCENARIO_TABLE.replace("| £780,000 | £840,000 |", "| £780,000 | £780,000 |")
    found = misattributed_figures(leaked, FOLLOW_UP, [FORECAST], SCENARIO_RECEIPTS)
    assert [figure for _, figure, _ in found] == ["£780,000"] and "original scenario" in found[0][2]


def test_the_original_revenue_in_the_revised_scenario_is_flagged():
    leaked = SCENARIO_TABLE.replace("| £2,400,000 | £2,688,000 |", "| £2,400,000 | £2,400,000 |")
    assert [f for _, f, _ in misattributed_figures(leaked, FOLLOW_UP, [FORECAST], SCENARIO_RECEIPTS)] == ["£2,400,000"]


def test_an_item_the_revision_does_not_change_carries_over():
    carried = SCENARIO_TABLE + "\n| Variable-cost share of revenue | 45% | 45% |"
    assert misattributed_figures(carried, FOLLOW_UP, [FORECAST], SCENARIO_RECEIPTS) == []


async def test_a_scenario_leak_is_removed_through_the_pipeline(pipeline):
    from app.orchestration.schemas import ConversationMessage
    leaked = SCENARIO_TABLE.replace("| £780,000 | £840,000 |", "| £780,000 | £780,000 |")
    pipeline.answers(AgentOutcome(text=leaked, calculation_receipts=[
        {"calculation_id": f"c{i}", "formula_version": "expression-evaluator-1.0", **r}
        for i, r in enumerate(SCENARIO_RECEIPTS)]))
    response, audited = await pipeline.ask(FOLLOW_UP, [ConversationMessage(role="user", content=FORECAST),
                                                       ConversationMessage(role="assistant", content="…")])
    assert "| Revenue | £2,400,000 | £2,688,000 |" in response.answer.text
    assert "£780,000 | £780,000" not in response.answer.text
    assert response.answer.completeness == audited.completeness == "partial"


def test_an_exchange_rate_written_without_a_currency_figure_is_an_operand():
    # FX benchmark, 2026-10-17: "US$1.30" is not a material figure, so the
    # conversion £96,153.85 (125,000 ÷ 1.30) was removed as unverified.
    facts = ("We expect to pay US$125,000 in 60 days. Our approved budget rate is £1 = US$1.25. Explain the impact "
             "if the exchange rate moves to £1 = US$1.20 or £1 = US$1.30.")
    shown = "At £1 = US$1.30 the sterling cost is £96,153.85; at £1 = US$1.20 it is £104,166.67."
    assert unreconciled_figures(shown, facts, "", stated=facts) == []
    assert unreconciled_figures("At £1 = US$1.30 the sterling cost is £96,153.84.", facts, "", stated=facts) == [
        "£96,153.84"]                                     # a penny out is still not verified


# ── Rounded figures (2026-10-17) ────────────────────────────────────────────

def test_an_unmarked_rounding_of_the_same_figure_is_accepted():
    # "Operating profit rose 23%" after "operating profit rose £36,000 (23.23%)".
    assert unverified(ANSWER + " In short, operating profit rose 23%; gross profit rose 15%.") == []


def test_a_rounding_that_misstates_the_figure_is_not():
    # 23.23% is not "25%", 14.77% is not "13%".
    assert unverified(ANSWER + " Operating profit rose 25% and gross profit rose 13%.") == ["25%", "13%"]


def test_a_whole_number_percentage_is_not_verified_by_a_date():
    # "31%" once matched the 31 of "31 March 2026".
    assert "31 March" in FINANCIALS
    assert unverified("A further 31% of costs are fixed.") == ["31%"]
