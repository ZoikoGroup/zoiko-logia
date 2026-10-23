"""Offline regressions from the 18-answer manual review (22 Oct 2026).

Three failure types, fixed separately:
1. the figure check deleted correct work (tables, LaTeX, rounded percentages);
2. the evidence policy emptied supplied-scenario answers ("the sources do not
   state this") and forced searches the library could not answer;
3. formatting leaks (tool tags, raw LaTeX, "General explanation:" mid-sentence).
Accounting reasoning errors (Apex NOL ignored, recap coverage, invented DuPont
balances) pass every check; their answer keys are here for an approved live
run, and the grader below is shown to catch them on the saved answers. No
model calls.
"""
import json
import re
from pathlib import Path

import pytest

from app.orchestration import service
from app.orchestration.agent_plan import plan_request
from app.orchestration.answer_formatting import latex_to_plain, separate_headings
from app.orchestration.calculation_service import needs_lookup
from app.orchestration.figure_reconciliation import unreconciled_figures
from app.orchestration.gap_filler import _replace_sentence, explanation_gaps
from app.orchestration.prescreen import run_prescreen
from app.orchestration.verification_service import (
    names_an_authority, remove_tool_mentions, requires_authoritative_evidence,
)

FIXTURES = Path(__file__).parent / "fixtures"
EARLIER = json.loads((FIXTURES / "acceptance_questions_20261022.json").read_text())
REVIEW = json.loads((FIXTURES / "review_questions_20261022.json").read_text())
QUESTIONS = {**EARLIER, **REVIEW["questions"]}
KEYS = REVIEW["answer_keys"]
from tests.answer_key import grade  # noqa: E402
REVIEWED = sorted(KEYS)  # the 18 reviewed questions


def test_the_review_covers_eighteen_questions_and_keeps_the_earlier_fixture():
    # 18 from the 22 Oct review; 8 from the 23 Oct manual tests (pension,
    # segments, TDR, dividend, hedge, Level 3, inventory count, Brazil).
    assert len(REVIEWED) == 26 and set(REVIEWED) <= set(QUESTIONS)
    assert len(EARLIER) == 13  # unchanged


@pytest.mark.parametrize("name", REVIEWED)
def test_every_reviewed_question_is_in_scope(name):
    assert run_prescreen(QUESTIONS[name]).passed
    assert not service._is_deterministically_out_of_scope(QUESTIONS[name])


# ── 2. Evidence policy ────────────────────────────────────────────────────────

# Worked from the user's own facts under a named framework: professional
# knowledge, labelled, not strict citation.
PROFESSIONAL = ["recap", "lbo", "controls", "audit_risk", "vanguard", "vie", "eps", "fx", "nol_va", "benford",
                "dupont", "wacc", "npv", "nexus", "lcnrv", "impairment_group",
                # Its "current underlying stock price" is the $48 the question
                # gives, no longer read as a live lookup (v10, 23 Oct 2026).
                "convertible"]
# Still strict: US tax-code treatment of a spin-off (a jurisdiction-specific rule).
STRICT = ["carveout"]


@pytest.mark.parametrize("name", PROFESSIONAL)
def test_a_supplied_scenario_is_not_forced_into_strict_sourcing(name):
    assert not requires_authoritative_evidence(QUESTIONS[name], QUESTIONS[name])


@pytest.mark.parametrize("name", STRICT)
def test_known_strict_cases_are_recorded(name):
    assert requires_authoritative_evidence(QUESTIONS[name], QUESTIONS[name])


@pytest.mark.parametrize("question", [
    "What is the current corporate tax rate in the UK?",
    "What is the VAT registration threshold?",
    "What's the latest repo rate?",
    "What is the GST threshold of $75,000 in Australia based on?",
    "Explain IFRS 16",
])
def test_genuine_lookups_still_need_sources(question):
    assert requires_authoritative_evidence(question)


@pytest.mark.parametrize("text", [
    "the current year-end spot rate is $1.35",
    "TargetCo's current TTM (Trailing Twelve Months) EBITDA is $2,000,000.",
    "just below a $3,000 manager approval threshold",
    "Calculate Taxable Income and Current Income Tax Payable for 2026.",
])
def test_supplied_figures_are_not_lookups(text):
    assert not needs_lookup(text)


@pytest.mark.parametrize("name", ["vie", "vanguard", "controls", "lbo", "audit_risk", "nol_va"])
def test_framework_scenarios_get_the_professional_application_instruction(name):
    # The service adds PROFESSIONAL_APPLICATION_INSTRUCTION when the policy is
    # not strict but the question names a framework or rule.
    question = QUESTIONS[name]
    assert names_an_authority(question) and not requires_authoritative_evidence(question, question)
    assert "do not say the sources do not state it" in service.PROFESSIONAL_APPLICATION_INSTRUCTION


async def test_a_vie_scenario_is_not_told_to_answer_only_from_searches(pipeline):
    from app.domains.model_gateway.agent import AgentOutcome
    pipeline.answers(AgentOutcome(text="Silo Holdings is a VIE; Titan consolidates it."))
    await pipeline.ask(QUESTIONS["vie"])
    call = pipeline.agent.call_args
    assert call.kwargs["require_evidence"] is False
    assert service.PROFESSIONAL_APPLICATION_INSTRUCTION.strip() in call.args[0]


@pytest.mark.parametrize("name", ["recap", "carveout", "lbo", "wacc", "eps", "vie"])
def test_scenarios_do_not_plan_market_or_economic_lookups(name):
    tools = plan_request(QUESTIONS[name]).tools
    assert "get_market_data" not in tools and "get_economic_indicator" not in tools


def test_converting_a_bond_into_shares_is_not_a_currency_conversion():
    assert "get_exchange_rate" not in plan_request(QUESTIONS["convertible"]).tools
    assert "get_exchange_rate" in plan_request("Convert $5,000 to EUR").tools


@pytest.mark.parametrize("question, tool", [
    ("What is Apple's share price today and its P/E if EPS is 6.1?", "get_market_data"),
    ("I hold Apple shares bought at $150, $160 and $170 - what is my gain at today's price?", "get_market_data"),
    ("How did the Fed interest rate change in 2024?", "get_economic_indicator"),
    ("Show US inflation and interest rate trend", "get_economic_indicator"),
])
def test_real_lookups_still_plan_their_tool(question, tool):
    assert tool in plan_request(question).tools


# ── 1. Figure check: correct work kept, wrong work removed ─────────────────────

LBO_FACTS = QUESTIONS["lbo"]
LBO_SIZING = "Senior Secured Debt = 3.5 × 2,000,000 = 7,000,000\nSubordinated Debt = 1.5 × 2,000,000 = 3,000,000\n"
LBO_TABLE = ("| Tranche | Principal | Rate | Interest |\n|---|---|---|---|\n"
             "| Senior debt | $7,000,000 | 7% | $490,000 |\n| Subordinated debt | $3,000,000 | 10% | $300,000 |\n"
             "| Total pre-tax interest | | | $790,000 |\n")


def test_lbo_interest_table_is_kept():
    assert unreconciled_figures(LBO_SIZING + LBO_TABLE, LBO_FACTS, "", stated=LBO_FACTS) == []


@pytest.mark.parametrize("wrong, figure", [
    ("$490,000", "$495,000"), ("$790,000", "$800,000"), ("$300,000", "$330,000"),
])
def test_lbo_wrong_interest_is_removed(wrong, figure):
    text = LBO_SIZING + LBO_TABLE.replace(wrong, figure)
    assert figure in unreconciled_figures(text, LBO_FACTS, "", stated=LBO_FACTS)


NPV_FACTS = QUESTIONS["npv"]
NPV_ROWS = [
    "| 1 | 500,000 | 200,000 | 160,000 | 140,000 | 29,400 | 270,600 |",
    "| 3 | 500,000 | 200,000 | 153,600 | 146,400 | 30,744 | 269,256 |",
    "| 4 | 500,000 | 200,000 | 92,160 | 207,840 | 43,646.4 | 256,353.6 |",
]
NPV_HEADER = "| Year | Revenue | OpEx | Depreciation | EBIT | Tax | OCF |\n|---|---|---|---|---|---|---|\n"


@pytest.mark.parametrize("row", NPV_ROWS)
def test_npv_operating_cash_flow_rows_are_kept(row):
    assert unreconciled_figures(NPV_HEADER + row, NPV_FACTS, "", stated=NPV_FACTS) == []


@pytest.mark.parametrize("row, figure", [
    (NPV_ROWS[0].replace("270,600", "271,600"), "271,600"),
    # Not 150,000: the one-step rule reaches it as 200,000 − 50,000 (the NWC
    # figure) — a known gap of that rule, recorded in the work log.
    (NPV_ROWS[0].replace("140,000", "141,000"), "141,000"),
])
def test_a_wrong_npv_cell_is_removed(row, figure):
    assert figure in unreconciled_figures(NPV_HEADER + row, NPV_FACTS, "", stated=NPV_FACTS)


def test_a_rounded_percentage_of_a_verified_decimal_is_kept():
    facts = QUESTIONS["wacc"]
    calculations = "0.285714 × 0.059419 = 0.016977\n0.037594 × 0.08 = 0.003008\n0.676692 × 0.123 = 0.083233"
    shown = "WACC = 0.016977 + 0.003008 + 0.083233 = 0.103218\nWACC ≈ 10.32 %"
    assert unreconciled_figures(shown, facts, calculations, stated=facts) == []
    assert "11.32 %" in unreconciled_figures(shown.replace("10.32", "11.32"), facts, calculations, stated=facts)


async def test_latex_money_is_read_as_the_reader_sees_it(pipeline):
    from app.domains.model_gateway.agent import AgentOutcome
    text = "Net Profit Margin = \\frac{\\$468{,}000}{\\$5{,}200{,}000} = 0.09 (9.00%)"
    pipeline.answers(AgentOutcome(text=text))
    response, _audited = await pipeline.ask(QUESTIONS["dupont"])
    assert "468,000" in response.answer.text and "\\frac" not in response.answer.text


def test_eps_bond_shares_written_as_working_are_kept():
    facts = QUESTIONS["eps"]
    assert unreconciled_figures("Shares from conversion = $2,000,000 ÷ $1,000 × 30 = 60,000 shares",
                                facts, "", stated=facts) == []


# ── 3. Formatting ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("saved, cleaned", [
    ("| A | 1,200 × $160 = $192,000 (calculated with tool – see calculation “NRV total A”) |",
     "| A | 1,200 × $160 = $192,000 |"),
    ("| D | 400 × $1,000 = $400,000 (derived manually) |", "| D | 400 × $1,000 = $400,000 |"),
    ("Total = 928,000\n\n(tool – “Total inventory”)", "Total = 928,000\n\n"),
    ("Ratio is 1.5×. The ratio was computed with the exact calculation tool (see the expression above). Next.",
     "Ratio is 1.5×. Next."),
    ("All arithmetic uses the figures supplied and the calculations performed with the exact calculation tool.", ""),
])
def test_kriton_tool_tags_are_removed_and_the_working_kept(saved, cleaned):
    assert remove_tool_mentions(saved) == cleaned


@pytest.mark.parametrize("prose", [
    # D1 (review, 22 Oct 2026): each of these was deleted by the earlier, broader pattern.
    "Use a calculation tool such as Excel to reconcile the ledger.",
    "(machine tool – depreciated over 5 years)",
    "The lathe (a machine tool: cost $50,000) is depreciated over 5 years.",
    "Use a tool (for example a spreadsheet) to track it.",
    "A calculation tool – such as a spreadsheet – helps (see calculation steps below).",
])
def test_ordinary_prose_about_tools_is_never_removed(prose):
    assert remove_tool_mentions(prose) == prose


def test_a_figure_inside_a_tool_parenthesis_survives_with_its_sentence():
    sentence = "The lathe (a machine tool: cost $50,000) is depreciated over 5 years."
    cleaned = remove_tool_mentions(sentence)
    assert cleaned == sentence and "$50,000" in cleaned


@pytest.mark.parametrize("latex, plain", [
    ("OCF = (Revenue - Opex)(1-\\tau) + Depreciation\\tau", "OCF = (Revenue - Opex)(1-τ) + Depreciation τ"),
    ("(70 + (1000-950)/15) \\big/ \\big((1000+950)/2\\big) = 0.075214", "(70 + (1000-950)/15) / ((1000+950)/2) = 0.075214"),
    ("P(d) = \\log_{10}(1 + 1/d)", "P(d) = log_10(1 + 1/d)"),
    ("R_{f} + \\beta \\times MRP", "R_f + β × MRP"),
    ("\\sqrt{x^{2}} \\pm 1", "√(x^2) ± 1"),
])
def test_remaining_latex_becomes_plain_text(latex, plain):
    assert latex_to_plain(latex) == plain


@pytest.mark.parametrize("text, expected", [
    ("Intro. Consequently, the sources provided do not state the VIE criteria.",
     "Intro. General explanation: X."),
    ("The search returned no passage; therefore the sources do not establish the components of the score.",
     "General explanation: X."),
])
def test_a_general_explanation_replaces_the_whole_sentence(text, expected):
    assert _replace_sentence(text, explanation_gaps(text)[0], "General explanation: X.") == expected


def test_a_bold_heading_is_not_run_into_the_next_line():
    assert separate_headings("**Conversion Ratio**\nConversion Ratio = 1000 ÷ 40 = 25") == \
        "**Conversion Ratio**\n\nConversion Ratio = 1000 ÷ 40 = 25"


# ── Reasoning errors: answer keys and a grader that catches them ──────────────

SAVED_APEX = ("Taxable Income = $1,800,000 − $100,000 − $200,000 = $1,500,000\n"
              "Current Income Tax Payable = $1,500,000 × 21% = $315,000\n"
              "DTA = $200,000 × 21% = $42,000\nNet Income Tax Expense = $315,000 − $42,000 = $273,000")
SAVED_NEXUS = "Allocated: $108,000, $54,000, $18,000. Revenue 2026 $153,000; deferred revenue $27,000."


def test_the_grader_flags_the_saved_apex_answer():
    result = grade(SAVED_APEX, "nol_va")
    assert set(result.missing) == {"taxable income 500,000", "tax payable 105,000", "net tax expense 147,000"}
    assert {"NOL ignored: taxable income 1,500,000", "tax payable 315,000",
            "net tax expense 273,000"} <= set(result.contradictions)


def test_the_grader_passes_the_saved_nexus_answer():
    assert grade(SAVED_NEXUS, "nexus").passed


def test_a_number_is_matched_whole():
    # "500,000" inside "1,500,000" is not the expected taxable income.
    assert "taxable income 500,000" in grade("Taxable income is $1,500,000.", "nol_va").missing


@pytest.mark.parametrize("answer", [
    "Conversion ratio 25 shares. Fiscal 2026; coupon 4%; quote 125.",   # a stray "2" is not the premium
    "The premium is $20 per share.",
])
def test_the_convertible_premium_needs_two_dollars_beside_premium(answer):
    assert "premium $2 per share" in grade(answer, "convertible").missing


def test_the_convertible_premium_is_found_where_stated():
    answer = ("Conversion Ratio = 1000 ÷ 40 = 25\nConversion Value = 25 × 48 = 1200\n"
              "Premium per share = 50 − 48 = 2\nNo profit if converted, so no arbitrage opportunity.")
    assert grade(answer, "convertible").passed


@pytest.mark.parametrize("answer, found", [
    ("Senior 7,000,000; Sub 3,000,000; EV 10,000,000.", False),      # "0" in other numbers is not sponsor equity
    ("Sponsor Equity = 10,000,000 – (7,000,000 + 3,000,000) = 0", True),
    ("Sponsor equity required: zero.", True),
    ("Sponsor Equity = $10", False),
])
def test_lbo_sponsor_equity_must_be_stated_as_zero(answer, found):
    assert ("sponsor equity 0" not in grade(answer, "lbo").missing) is found


def test_nonrecognized_is_not_read_as_recognized():
    result = grade("| A | Nonrecognized (Type 2) |\n| B | Nonrecognized (Type 2) |", "vanguard")
    assert "A recognized (Type 1)" in result.missing and "A classified Type 2" in result.contradictions
    assert grade("| A | Recognized (Type 1) | 400,000 |\n| B | Nonrecognized (Type 2) | 650,000 |\n"
                 "| C | Recognized (Type 1) | 250,000 |", "vanguard").passed


def test_the_lcnrv_reporting_date_is_checked():
    saved = "Total inventory value on the balance sheet (12 Dec 2026): 928,000; write-down 15,500."
    result = grade(saved, "lcnrv")
    assert "reporting date 31 Dec 2026" in result.missing and "wrong reporting date 12 Dec" in result.contradictions
    assert grade(saved.replace("12 Dec 2026", "December 31, 2026"), "lcnrv").passed


@pytest.mark.parametrize("name, wrong, contradiction", [
    ("recap", "Interest coverage drops from about 3.33 to about 2.33.", "coverage 3.33 → 2.33"),
    ("dupont", "Total Asset Turnover 2025 = 4,000,000 ÷ ((2.8 M+3.0 M)/2) = 1.33",
     "invented FY2024 balances (2025 averages)"),
])
def test_known_reasoning_errors_are_contradictions(name, wrong, contradiction):
    assert contradiction in grade(wrong, name).contradictions


def test_unresolved_keys_are_marked_awaiting_accountant_review():
    status = REVIEW["review_status"]
    assert set(status) == {"recap", "carveout", "wacc", "npv", "pension", "segments", "tdr", "hedge", "level3",
                           "inventory_count", "brazil"}
    for name, entry in status.items():
        assert entry["status"] == "awaiting accountant review" and entry["assumption"]
        assert all(key in KEYS[name] and "awaiting review" in key for key in entry["keys"])


def test_the_answer_keys_are_arithmetically_consistent():
    # Recap: interest, after-tax cost, coverage (EBIT = NI / (1 − t)).
    assert 3_000_000 * 0.08 == 240_000 and round(240_000 * 0.79) == 189_600 and 800_000 - 189_600 == 610_400
    assert round(610_400 / 2_000_000 * 100, 2) == 30.52 and round(800_000 / 0.79 / 240_000, 2) == 4.22
    # Apex: NOL used in full; VA released as used.
    taxable = 1_800_000 - 100_000 - 200_000 - 1_000_000
    assert taxable == 500_000 and round(taxable * 0.21) == 105_000
    assert round(105_000 + 200_000 * 0.21) == 147_000 == round((1_800_000 - 100_000) * 0.21 - 1_000_000 * 0.21)
    # LBO and FX.
    assert 7_000_000 * 0.07 + 3_000_000 * 0.10 == 790_000 and round(790_000 * 0.79) == 624_100
    assert 1_400_000 - 624_100 == 775_900
    assert round(500_000 * (1.12 - 1.08)) == 20_000 and round(500_000 * (1.10 - 1.12)) == -10_000
    assert round((1_000_000 - 600_000) * (1.35 - 1.25)) == 40_000


from tests.test_answer_status_pipeline import pipeline  # noqa: E402,F401  (fixture)


# ── D2: removal notes are not answer content ──────────────────────────────────

from app.orchestration.claim_verification import FIGURE_DISPROVED_NOTE, FIGURES_REMOVED_NOTE  # noqa: E402
from app.orchestration.review_release import remove_disproved_figures  # noqa: E402

MISMATCH = ["Calculation mismatch: 780,000 ÷ 0.55 equals 1418181.82, not 1560000."]


def test_an_answer_left_with_only_removal_notes_goes_to_review():
    answer = f"### Break-even\n{FIGURES_REMOVED_NOTE}\nBreak-even revenue = £780,000 ÷ 0.55 = £1,560,000."
    cleaned, notes = remove_disproved_figures(answer, MISMATCH)
    assert cleaned == "" and notes  # "" is routed to review by the caller


def test_an_answer_with_content_beside_a_removal_note_is_kept():
    answer = (f"### Break-even\n{FIGURES_REMOVED_NOTE}\nThe contribution margin ratio is 55% of revenue, as stated.\n"
              "Break-even revenue = £780,000 ÷ 0.55 = £1,560,000.")
    cleaned, _notes = remove_disproved_figures(answer, MISMATCH)
    assert "contribution margin ratio is 55%" in cleaned and "1,560,000" not in cleaned


def test_the_agent_does_not_count_removal_notes_as_content():
    from app.domains.model_gateway.agent import _substantive
    assert not _substantive(f"### Interest\n{FIGURES_REMOVED_NOTE}\n{FIGURE_DISPROVED_NOTE}")
    assert _substantive(f"### Interest\n{FIGURE_DISPROVED_NOTE}\nInterest is payable annually in arrears.")


# ── R2: mixed sourced and unsourced answers ───────────────────────────────────

from app.domains.model_gateway.agent import AgentOutcome  # noqa: E402
from app.orchestration.verification_service import uncited_explanations  # noqa: E402
from app.orchestration.websearch import WebSource  # noqa: E402

CITED = "ASC 810 requires the primary beneficiary of a variable interest entity to consolidate it [REF-1]."
UNCITED = "Silo's equity at risk is insufficient because outside investors cannot absorb its expected losses."
WORKING = "Equity at risk = $100,000 ÷ $2,000,000 = 5%"


def test_uncited_explanations_are_found_and_cited_or_calculated_lines_are_not():
    assert uncited_explanations(CITED) == []
    assert uncited_explanations(WORKING) == []
    assert uncited_explanations(f"{CITED}\n{UNCITED}\n{WORKING}") == [UNCITED]


ASC_810 = WebSource(title="FASB ASC 810", url="https://asc.fasb.org/810",
                    snippet="ASC 810 requires the primary beneficiary of a variable interest entity to consolidate it.")


async def _limitations(pipeline, text, sources):
    pipeline.answers(AgentOutcome(text=text, sources=sources))
    response, _audited = await pipeline.ask(QUESTIONS["vie"])
    return response, response.answer.limitations


async def test_an_all_uncited_professional_answer_is_labelled_general(pipeline):
    _response, limitations = await _limitations(pipeline, f"{UNCITED}\n{WORKING}", [])
    assert service.GENERAL_EXPLANATION_NOTE in limitations and service.MIXED_SOURCES_NOTE not in limitations


async def test_a_mixed_answer_marks_its_uncited_parts(pipeline):
    response, limitations = await _limitations(pipeline, f"{CITED}\n{UNCITED}\n{WORKING}", [ASC_810])
    assert "[REF-1]" in response.answer.text
    assert service.MIXED_SOURCES_NOTE in limitations and service.GENERAL_EXPLANATION_NOTE not in limitations


async def test_an_all_cited_answer_is_not_called_unverified(pipeline):
    _response, limitations = await _limitations(pipeline, f"{CITED}\n{WORKING}", [ASC_810])
    assert service.MIXED_SOURCES_NOTE not in limitations and service.GENERAL_EXPLANATION_NOTE not in limitations


# ── R1: confirming a current rate is a lookup; using a supplied one is not ────

from app.orchestration.calculation_service import validate_answer_calculations, verifies_current_fact  # noqa: E402

CONFIRMS_A_CURRENT_FACT = [
    "Is the current repo rate at 6.5%?",
    "Is the current exchange rate of 83 INR per USD correct?",
    "Is the current US federal minimum wage of $7.25 still in force?",
    "Confirm the current SOFR rate is 5.3%.",
    "Is $1.08 per € still the current EUR/USD rate?",
    "The UK VAT threshold is £90,000 — is that still correct?",
    "Is today's gold price $2,400 an ounce?",
    "Check that the latest base rate of 5.25% is right.",
    "We plan to borrow $1,000,000 at the bank's current rate of 7%. Is that rate still correct today?",
]
USES_A_SUPPLIED_FIGURE = [
    "The current year-end spot rate is $1.35. Translate net assets of £400,000.",
    "Using the current repo rate of 6.5%, compute interest on ₹10,00,000 for 90 days.",
    "Our current interest rate is 7%; calculate annual interest on $500,000.",
    "Is the current ratio of 2.5 healthy for a retailer?",
    "Is the price of $45 per share above book value per share of $30?",
    "Is the convertible bond's conversion premium of $2 per share profitable to arbitrage?",
]


@pytest.mark.parametrize("question", CONFIRMS_A_CURRENT_FACT)
def test_confirming_a_current_rate_needs_a_current_source(question):
    assert verifies_current_fact(question) and needs_lookup(question)
    assert requires_authoritative_evidence(question, question)


@pytest.mark.parametrize("question", USES_A_SUPPLIED_FIGURE)
def test_calculating_with_a_supplied_rate_does_not(question):
    assert not verifies_current_fact(question)
    assert not requires_authoritative_evidence(question, question)


@pytest.mark.parametrize("name", REVIEWED)
def test_no_reviewed_scenario_reads_as_a_verification_request(name):
    assert not verifies_current_fact(QUESTIONS[name])


@pytest.mark.parametrize("question", CONFIRMS_A_CURRENT_FACT[:2])
async def test_an_uncited_yes_to_a_current_rate_is_not_released(pipeline, question):
    pipeline.answers(AgentOutcome(text="Yes, it is correct: the rate is 6.5%."))
    response, _audited = await pipeline.ask(question)
    assert "Yes, it is correct" not in response.answer.text
    assert response.answer.completeness != "complete"


# ── R2: citation placement ────────────────────────────────────────────────────

@pytest.mark.parametrize("text, uncited", [
    # A marker on every sentence: nothing is unlabelled.
    ("ASC 810 requires consolidation [REF-1]. The primary beneficiary consolidates the VIE [REF-1].", []),
    # A marker inside the sentence still cites it.
    ("ASC 810 [REF-1] requires the primary beneficiary of a variable interest entity to consolidate it.", []),
    # One marker at the end of a paragraph cites only its own sentence: the
    # sentence before it is counted as uncited (labelled, conservatively).
    ("Silo's outside equity cannot absorb the entity's expected losses on its own. "
     "ASC 810 therefore treats it as a variable interest entity [REF-1].",
     ["Silo's outside equity cannot absorb the entity's expected losses on its own."]),
    # A marker on its own line cites no sentence.
    ("Titan has the power to direct the activities that matter most to Silo's results.\n[REF-1]",
     ["Titan has the power to direct the activities that matter most to Silo's results."]),
    # A table row is one statement: a marker in any cell cites the row.
    ("| Primary beneficiary | Titan holds the power and the obligation to absorb losses | [REF-1] |", []),
])
def test_citation_placement_decides_what_counts_as_uncited(text, uncited):
    assert uncited_explanations(text) == uncited


# ── D3: bold results are checked like plain ones ──────────────────────────────

@pytest.mark.parametrize("text, wrong", [
    ("ROE = $468,000 ÷ $1,750,000 = **27.74 %**", True),
    ("ROE = $468,000 ÷ $1,750,000 = **26.74 %**", False),
    ("**Total** = 5 + 3 = 9", True),
    ("Break-even = 780,000 ÷ 0.55 = **$1,560,000**", True),
    ("Break-even = 780,000 ÷ 0.55 = **$1,418,181.82**", False),
    ("The **key point** is that revenue rose.", False),
])
def test_bold_results_are_checked(text, wrong):
    assert bool(validate_answer_calculations(text)) is wrong


# ── Final review: paraphrased confirmations and short claims ──────────────────

PARAPHRASED_CONFIRMATIONS = [
    "Could you verify whether the current repo rate is 6.5%?",
    "Could you confirm whether the current exchange rate is 83 INR per USD?",
    "Can you check if the latest RBI repo rate is 6.5%?",
    "Please verify that the current UK VAT threshold is £90,000.",
    "I need to know whether the current SOFR rate is still 5.3%.",
    "Would you tell me if the prevailing base rate is 5.25%?",
    "Kindly confirm the current GST rate on restaurants is 5%.",
]
SUPPLIED_WITH_A_VERIFYING_VERB = [
    # The verb checks the user's own working, and the time word comes before it.
    "Using the current repo rate of 6.5%, compute interest on ₹10,00,000 for 90 days and check that the "
    "interest is correct.",
    "The current spot rate is $1.35; please confirm the translated balance of £400,000.",
    "Verify the journal entry total of $15,500 at the current year-end.",
]


@pytest.mark.parametrize("question", PARAPHRASED_CONFIRMATIONS)
def test_paraphrased_confirmations_need_a_current_source(question):
    assert verifies_current_fact(question) and requires_authoritative_evidence(question, question)


@pytest.mark.parametrize("question", SUPPLIED_WITH_A_VERIFYING_VERB)
def test_checking_your_own_working_is_still_a_calculation(question):
    assert not verifies_current_fact(question)


@pytest.mark.parametrize("text, uncited", [
    ("Titan consolidates Silo.", ["Titan consolidates Silo."]),
    ("- Silo is a VIE.", ["Silo is a VIE."]),
    ("Titan consolidates Silo [REF-1].", []),
    ("### Conclusion\n**Primary beneficiary**\nKey points:", []),
    ("Yes.\nSee above.", []),
    # A table's header row names columns; its body rows are claims.
    ("| Asset | Carrying amount | Fair value |\n|---|---|---|\n| Building and land | 3,000,000 | not given |",
     ["| Building and land | 3,000,000 | not given |"]),
])
def test_short_claims_count_and_headings_and_fragments_do_not(text, uncited):
    assert uncited_explanations(text) == uncited


async def test_a_short_uncited_claim_beside_a_cited_one_gets_the_mixed_label(pipeline):
    _response, limitations = await _limitations(pipeline, f"{CITED}\nTitan consolidates Silo.", [ASC_810])
    assert service.MIXED_SOURCES_NOTE in limitations


# ── v3 review: two-word claims versus two-word non-claims ─────────────────────

@pytest.mark.parametrize("claim", [
    "Rates increased.", "Revenue rose.", "Titan qualifies.", "Silo consolidates.", "Profits fell!",
    "Liabilities exceeded.",
])
def test_a_two_word_claim_counts_as_uncited(claim):
    assert uncited_explanations(claim) == [claim]


@pytest.mark.parametrize("non_claim", [
    "See above.", "Not applicable.", "Journal entries.", "Key points.", "Yes.", "Interest payable.",
    "Assets decreased:",  # a lead-in
    "Net income",         # no sentence ending
])
def test_a_two_word_pointer_or_label_does_not(non_claim):
    assert uncited_explanations(non_claim) == []


def test_a_cited_two_word_claim_is_not_uncited():
    assert uncited_explanations("Rates increased [REF-1].") == []


# ── v4 review: R1 in both directions ──────────────────────────────────────────

CONFIRMATIONS_WITHOUT_A_TIME_WORD = [
    "Is the repo rate 6.5%?",
    "Is GST on restaurant meals 5%?",
    "Has RBI changed the repo rate from 6.5%?",
    "The repo rate is 6.5% now, isn't it?",
    "Repo rate still 6.5%?",
    "Is the EUR/USD rate 1.08?",
]
# Each asks about a calculation on a rate the user gives; the v3 detector sent
# five of them to strict sourcing.
CALCULATIONS_ON_A_SUPPLIED_RATE = [
    "I know the current rate is 7%; compute interest on $500,000.",
    "Tell me the interest using the current rate of 7% on $500,000.",
    "Does the current exchange rate of $1.12 create a gain on the €500,000 receivable?",
    "Is the current price of $45 above book value per share of $30?",
    "Was the current year's interest rate of 8% applied correctly in the schedule?",
    "Check that the current spot rate of $1.35 was applied to the translation.",
    "What is the after-tax cost of debt if the tax rate is 21%?",
    "Should the 7% interest rate be capitalised?",
]


@pytest.mark.parametrize("question", CONFIRMATIONS_WITHOUT_A_TIME_WORD)
def test_a_plain_yes_no_confirmation_needs_a_current_source(question):
    assert verifies_current_fact(question) and requires_authoritative_evidence(question, question)


@pytest.mark.parametrize("question", CALCULATIONS_ON_A_SUPPLIED_RATE)
def test_a_calculation_on_a_supplied_rate_is_not_a_confirmation(question):
    assert not verifies_current_fact(question)


@pytest.mark.parametrize("question", CALCULATIONS_ON_A_SUPPLIED_RATE[:4] + CALCULATIONS_ON_A_SUPPLIED_RATE[5:6]
                         + CALCULATIONS_ON_A_SUPPLIED_RATE[7:])
def test_and_is_not_forced_into_strict_sourcing(question):
    # Not "applied correctly in the schedule" or "if the tax rate is 21%":
    # both were strict on the base commit too, by an older route (the words
    # "applied … correctly" and "tax rate"), unchanged here.
    assert not requires_authoritative_evidence(question, question)
