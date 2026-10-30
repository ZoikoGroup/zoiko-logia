"""VAT calculation, clarification, verification and audit consistency
(reliability brief, 24 Oct 2026).

Root causes reproduced here:
- A "Calculation check" said an answer stated £3 when it stated £1,000: the
  source marker in "claimed as input tax [REF-3]" was read as the figure the
  label governed (the logged sentence, aud-401da590523f).
- Engine answers were labelled "calculated and verified" and any cited answer
  "source grounded", so correct arithmetic or one citation read as proof of
  the whole answer.
- The canonical calculation was recorded only after the calculation route had
  already returned, so engine answers carried no calculation id.
- "£14,000 is payable" assumed all the input VAT recoverable without saying so.
No model, database or network.
"""
from decimal import Decimal

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.accounting_validation import calculation_discrepancies
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.calculations.schemas import CalculationOutput
from app.orchestration.input_requirements import missing_vat_country, missing_vat_inputs
from app.orchestration.verification_service import EvidenceFinding, verification_breakdown
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

QUARTER = ("In a VAT quarter a UK business has sales of £120,000 excluding VAT and purchases of £60,000 including VAT, "
           "all at 20%. What VAT does it pay to HMRC?")
INPUT = "A UK business buys supplies for £6,000 including VAT at 20%. How much input VAT can it reclaim?"
PENNIES = "A UK business buys supplies for £99.99 including VAT at 20%. How much VAT is in it?"


def shown(question):
    result = calculate_from_query(question)
    assert result.status == "success", result.message
    return {o.name: o.display_value for o in result.outputs}


# ── 1. The three calculations ─────────────────────────────────────────────

@pytest.mark.parametrize("question, expected", [
    (QUARTER, {"output_vat_on_sales": "£24,000.00", "input_vat_on_purchases": "£10,000.00",
               "vat_payable": "£14,000.00"}),
    (INPUT, {"vat_amount": "£1,000.00", "amount_excluding_vat": "£5,000.00"}),
    (PENNIES, {"vat_amount": "£16.67", "amount_excluding_vat": "£83.32"}),
])
def test_the_three_vat_calculations(question, expected):
    assert shown(question) == expected


def test_inclusive_and_exclusive_formulas_and_exact_values():
    result = calculate_from_query(QUARTER)
    assert result.steps[:2] == ["Output VAT = £120,000.00 × 20 ÷ 100 = £24,000.00",
                                "Input VAT = £60,000.00 × 20 ÷ (100 + 20) = £10,000.00"]
    pennies = calculate_from_query(PENNIES).outputs[0]
    assert pennies.value == Decimal("99.99") * 20 / 120          # kept exact, rounded only for display


def test_displayed_parts_tie_when_exact_rounding_differs_by_a_penny():
    question = ("A UK business has sales of £100.00 excluding VAT and purchases of £50.01 including VAT, all at 20%. "
                "What VAT does it pay?")
    result = calculate_from_query(question)
    figures = {o.name: o.display_value for o in result.outputs}
    assert figures == {"output_vat_on_sales": "£20.00", "input_vat_on_purchases": "£8.34", "vat_payable": "£11.66"}
    assert any("figures shown add up" in note for note in result.notes)
    # Either rounding of the payable figure is the result; another figure is not.
    assert calculation_discrepancies("The VAT payable is £11.66.", result) == []
    assert calculation_discrepancies("The VAT payable is £11.67.", result) == []
    assert calculation_discrepancies("The VAT payable is £11.76.", result)[0].expected == str(Decimal("11.665"))


# ── 2. Clarification ──────────────────────────────────────────────────────

@pytest.mark.parametrize("question, asks", [
    ("A business buys supplies for €6,000 including VAT at 20%. How much input VAT can it reclaim?", "which country"),
    ("A UK business buys supplies for £6,000 at 20%. How much input VAT can it reclaim?",
     "whether the amounts include VAT or exclude VAT"),
    ("Calculate VAT on £72,000 including VAT", "the VAT rate or rates that apply"),
])
def test_an_essential_unknown_is_asked_for(question, asks):
    assert asks in missing_vat_inputs(question)


def test_a_rate_question_in_a_foreign_currency_asks_the_country():
    assert missing_vat_country("What VAT rate applies to my €5,000 sale?").startswith("Which country")


def test_country_rate_and_treatment_given_means_no_question():
    assert missing_vat_inputs(INPUT) is None and calculate_from_query(INPUT).status == "success"


def test_a_currency_symbol_alone_is_not_taken_as_a_country():
    result = calculate_from_query("A business buys supplies for £6,000 including VAT at 20%. How much input VAT?")
    assert any("names no country" in note for note in result.notes)
    assert not any("names no country" in note for note in calculate_from_query(INPUT).notes)


# ── Partial recovery and adjustments ──────────────────────────────────────

def test_a_stated_recoverable_share_is_applied():
    result = calculate_from_query(QUARTER.replace("What VAT", "It is partially exempt and 60% of its input VAT is "
                                                  "recoverable. What VAT"))
    figures = {o.name: o.display_value for o in result.outputs}
    assert figures["recoverable_input_vat"] == "£6,000.00" and figures["vat_payable"] == "£18,000.00"
    assert any("60% of the input VAT, as you stated, is recoverable" in note for note in result.notes)


def test_partial_exemption_without_a_share_is_asked_for():
    result = calculate_from_query("A UK business is partially exempt. Sales of £120,000 excluding VAT and purchases of "
                                  "£60,000 including VAT, all at 20%. What VAT does it pay?")
    assert result.status == "clarification_required" and "What percentage of its input VAT is recoverable" in result.message


@pytest.mark.parametrize("adjustment", ["claims bad debt relief of £2,000", "has a reverse charge on imported services",
                                        "must correct an error from an earlier period"])
def test_an_adjustment_the_engine_does_not_apply_gets_no_full_recovery_result(adjustment):
    question = (f"A UK business has sales of £120,000 excluding VAT and purchases of £60,000 including VAT, all at "
                f"20%, and {adjustment}. What VAT does it pay?")
    assert calculate_from_query(question).status != "success"


def test_the_quarter_states_what_it_assumes():
    notes = calculate_from_query(QUARTER).notes
    assert any("assumes all of the input VAT is recoverable" in note and "no other VAT adjustments" in note
               and "does not establish legal eligibility" in note for note in notes)


def test_a_gst_quarter_states_its_assumptions_in_gst_terms():
    result = calculate_from_query("Sales ₹2,400,000 and purchases ₹1,100,000, all excluding GST at 18% for an Indian "
                                  "business. Calculate net GST payable.")
    note = next(n for n in result.notes if "assumes" in n)
    assert "all of the input tax credit is recoverable" in note and "no other GST adjustments" in note
    assert "VAT" not in note


# ── 3. Verification statuses ──────────────────────────────────────────────

def test_correct_arithmetic_with_stated_assumptions_is_not_fully_verified():
    result = calculate_from_query(QUARTER)
    status = verification_breakdown(completeness="complete", citations=0, limitations=[], calculation=result)
    assert (status.arithmetic, status.sources, status.assumptions, status.overall) == (
        "verified", "not_applicable", "stated", "partially_verified")
    assert status.calculation_id == result.fingerprint()


def test_plain_arithmetic_on_given_figures_is_fully_verified():
    result = calculate_from_query("What is the present value of £10,000 received in 3 years at 5%?")
    status = verification_breakdown(completeness="complete", citations=0, limitations=[], calculation=result)
    assert (status.arithmetic, status.assumptions, status.overall) == ("verified", "confirmed", "fully_verified")


@pytest.mark.parametrize("evidence, limitations", [
    ([EvidenceFinding("figure_not_in_cited_source", "s", ("REF-1",), "m")], []),          # unsupported
    ([EvidenceFinding("conflicting_sources", "s", ("REF-1", "REF-2"), "m")], []),        # conflicting
    ([], ["Partly source-verified. Statements with a source reference are supported by that source; …"]),
])
def test_a_cited_answer_with_unsupported_or_conflicting_evidence_is_only_partly_sourced(evidence, limitations):
    status = verification_breakdown(completeness="complete", citations=2, limitations=limitations, evidence=evidence)
    assert status.sources == "partial" and status.overall == "partially_verified"


def test_an_answer_with_no_sources_and_no_calculation_is_not_verified():
    status = verification_breakdown(completeness="complete", citations=0, limitations=[])
    assert (status.sources, status.overall) == ("unsupported", "not_verified")


# ── 4. The answer is compared with the canonical result ───────────────────

LOGGED = ("Calculation: VAT = £6,000 × 20 ÷ (100 + 20) = £1,000\n"
          "Further, the guidance on what can be claimed as input tax [REF-3] confirms that input VAT may be reclaimed "
          "on supplies that are liable to the standard, reduced, or zero rate.")


def test_the_logged_false_mismatch_does_not_recur():
    assert calculation_discrepancies(LOGGED, calculate_from_query(INPUT)) == []


def test_a_correct_answer_against_a_wrong_canonical_value_is_flagged_not_hidden():
    wrong = calculate_from_query(INPUT).model_copy(deep=True)
    wrong.outputs[0] = CalculationOutput(name="vat_amount", value=Decimal(3), display_value="£3.00", kind="money")
    [finding] = calculation_discrepancies("The input VAT you can reclaim is £1,000.", wrong)
    assert (finding.stated, finding.expected) == ("1000", "3")


def test_an_incorrect_answer_against_the_correct_value_is_flagged():
    [finding] = calculation_discrepancies("The input VAT you can reclaim is £1,200.", calculate_from_query(INPUT))
    assert (finding.output, finding.stated, finding.expected) == ("vat_amount", "1200", "1000")


def test_the_fingerprint_names_one_calculation():
    assert calculate_from_query(INPUT).fingerprint() == calculate_from_query(INPUT).fingerprint()
    assert calculate_from_query(INPUT).fingerprint() != calculate_from_query(INPUT.replace("6,000", "7,000")).fingerprint()


# ── Through the pipeline: page, calculation, status and audit agree ───────

def _recorded():
    calls = service.audit_answer_verification_recorded.await_args_list
    return calls[-1].kwargs if calls else None


async def test_an_engine_answer_page_calculation_status_and_audit_agree(pipeline):
    response, audited = await pipeline.ask(QUARTER)
    canonical = calculate_from_query(QUARTER)
    verification = response.answer.verification
    record = _recorded()
    assert verification.calculation_id == canonical.fingerprint() == record["calculation"]["calculation_id"]
    assert record["verification"] == verification.model_dump() and record["mismatches"] == []
    assert {o["name"]: o["display_value"] for o in record["calculation"]["outputs"]}["vat_payable"] == "£14,000.00"
    assert "£14,000.00" in response.answer.text
    # Correct arithmetic, eligibility assumed: not presented as fully verified.
    assert (verification.arithmetic, verification.assumptions, verification.overall) == (
        "verified", "stated", "partially_verified")
    assert record["answer_hash"] == service._hash_query(response.answer.text)
    assert audited.completeness == response.answer.completeness


MIXED = ("A UK business buys supplies for £6,000 including VAT at 20%. How much input VAT can it reclaim, and why can a "
         "business reclaim input VAT at all?")


async def test_a_wrong_model_figure_is_a_recorded_mismatch_and_blocks_verified(pipeline):
    pipeline.answers(AgentOutcome(text="Input VAT is the VAT paid on purchases. The input VAT you can reclaim is £1,200 "
                                       "(20% of £6,000)."))
    response, _ = await pipeline.ask(MIXED)
    record = _recorded()
    assert response.answer.verification.arithmetic == "mismatch"
    assert response.answer.verification.overall != "fully_verified"
    assert record["mismatches"][0]["stated"] == "1200" and record["mismatches"][0]["expected"] == "1000"
    assert "£1,200" in response.answer.text                              # disclosed, not altered


async def test_the_right_model_figure_records_no_mismatch(pipeline):
    pipeline.answers(AgentOutcome(text="Input VAT is the VAT paid on purchases. The input VAT you can reclaim is £1,000 "
                                       "(one-sixth of £6,000)."))
    response, _ = await pipeline.ask(MIXED)
    assert _recorded()["mismatches"] == [] and response.answer.verification.arithmetic == "verified"


async def test_a_model_answer_around_the_quarter_states_its_assumptions(pipeline):
    pipeline.answers(AgentOutcome(text="Output VAT is £24,000 and input VAT is £10,000, so £14,000 is payable to HMRC."))
    response, _ = await pipeline.ask(QUARTER.replace("What VAT does it pay to HMRC?",
                                                      "What VAT does it pay to HMRC, and why?"))
    assert any("assumes all of the input VAT is recoverable" in item
               for item in [*response.answer.limitations, response.answer.text])


async def test_no_calculation_carries_over_to_a_separate_conversation(pipeline):
    # Two requests with no shared history: each is checked against its own result.
    first, _ = await pipeline.ask(INPUT)
    first_id = _recorded()["calculation"]["calculation_id"]
    second, _ = await pipeline.ask(QUARTER)
    second_id = _recorded()["calculation"]["calculation_id"]
    assert first_id == calculate_from_query(INPUT).fingerprint()
    assert second_id == calculate_from_query(QUARTER).fingerprint() != first_id
    assert second.answer.verification.calculation_id == second_id


async def test_a_question_without_a_calculation_has_no_calculation_id(pipeline):
    await pipeline.ask(INPUT)
    pipeline.answers(AgentOutcome(text="Prices rose because input costs rose."))
    response, _ = await pipeline.ask("Why did our supplier raise prices?")
    assert response.answer.verification.calculation_id is None and _recorded()["calculation"] is None


@pytest.mark.parametrize("answer", [
    "Profit before tax increases by £10,000.00 after the correction.",
    "The gross margin falls from 40.17% to 39.10%.",
    "The original gross margin was 40.17%.",
])
def test_a_change_or_an_earlier_value_is_not_compared_with_the_result(answer):
    result = calculate_from_query("Revenue £800,000 and cost of sales £487,200. Calculate gross profit and gross margin.")
    assert result.status == "success"
    assert calculation_discrepancies(answer, result) == []


def test_a_wrong_percentage_is_named_without_a_currency_sign():
    result = calculate_from_query("Revenue £800,000 and cost of sales £487,200. Calculate gross profit and gross margin.")
    [finding] = calculation_discrepancies("The gross margin is 42.50%.", result)
    assert "states 42.50% for the gross margin" in finding.message and "£42" not in finding.message
