"""Deterministic calculations (reliability plan phase 2, 24 Oct 2026).

The engine (calculations/engine.py) computes from the user's own figures in
exact decimals. Four of the reviewed accounting questions were left to the
model because their wording was not read ("buys supplies for £6,000",
"takings … are £1,440", sales excluding and purchases including VAT in one
question), and present value and a conversion at a stated rate had no
formula. Where the engine computed a result, a different figure in a model
answer for the same quantity is disclosed and sent for review, never silently
replaced. No model, database or network.
"""
import inspect
from decimal import Decimal

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.accounting_validation import (
    CALCULATION_PREFIX, calculation_discrepancies, calculation_note,
)
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.input_requirements import missing_vat_inputs
from tests.test_answer_status_pipeline import page_status, pipeline  # noqa: F401


def outputs(question):
    result = calculate_from_query(question)
    assert result.status == "success", result.message
    return {o.name: o.display_value for o in result.outputs}


# ── The reviewed questions are calculated, not left to the model ──────────

@pytest.mark.parametrize("question, expected", [
    ("A UK VAT-registered business buys supplies for £6,000 including VAT at the standard rate of 20%. "
     "How much input VAT can it reclaim?", {"vat_amount": "£1,000.00", "amount_excluding_vat": "£5,000.00"}),
    ("A UK business sells goods for £10,000 excluding VAT at the standard rate of 20%. What output VAT does it "
     "charge, and what does the customer pay?", {"vat_amount": "£2,000.00", "total_including_vat": "£12,000.00"}),
    ("A UK shop's takings for the day are £1,440 including VAT at 20%. How much is VAT and how much are net sales?",
     {"vat_amount": "£240.00", "amount_excluding_vat": "£1,200.00"}),
    ("In a VAT quarter a UK business has sales of £120,000 excluding VAT and purchases of £60,000 including VAT, "
     "all standard-rated at 20%. What VAT does it pay to HMRC?",
     {"output_vat_on_sales": "£24,000.00", "input_vat_on_purchases": "£10,000.00", "vat_payable": "£14,000.00"}),
    ("Record the journal entry for a credit sale of £5,000 plus VAT at 20% by a UK VAT-registered business.",
     {"vat_amount": "£1,000.00", "total_including_vat": "£6,000.00"}),
])
def test_vat_in_everyday_wording_is_calculated(question, expected):
    assert outputs(question) == expected


def test_each_amount_is_taken_as_its_own_clause_states_it():
    result = calculate_from_query("Sales of £120,000 excluding VAT and purchases of £60,000 including VAT, all at 20%, "
                                  "for a UK business. What VAT is payable?")
    assert result.notes[0] == ("The amounts are taken as stated, sales excluding VAT and purchases including VAT, "
                               "at a single rate of 20%.")
    assert result.steps[:2] == ["Output VAT = £120,000.00 × 20 ÷ 100 = £24,000.00",
                                "Input VAT = £60,000.00 × 20 ÷ (100 + 20) = £10,000.00"]


def test_an_amount_whose_treatment_is_not_stated_is_not_guessed():
    assert calculate_from_query("UK sales of £120,000 excluding VAT and purchases of £60,000, all at 20%, and "
                                "some figures including VAT. What VAT is payable?").status != "success"


# ── No tax treatment without the jurisdiction and assumptions ─────────────

@pytest.mark.parametrize("question, asks", [
    ("A business buys supplies for €6,000 including VAT at 20%. How much input VAT can it reclaim?", "which country"),
    ("A business buys supplies for 6,000 including VAT at 20%. How much input VAT can it reclaim?", "which country"),
    ("A UK business buys supplies for £6,000 at 20%. How much input VAT can it reclaim?",
     "whether the amounts include VAT or exclude VAT"),
])
def test_a_missing_country_or_treatment_is_asked_for_not_assumed(question, asks):
    assert asks in missing_vat_inputs(question)


def test_the_pound_is_read_as_the_uk_as_before():
    assert missing_vat_inputs("A business buys supplies for £6,000 including VAT at 20%. How much input VAT?") is None


# ── Present value and a conversion at a stated rate ──────────────────────

def test_present_value_is_discounted_exactly():
    result = calculate_from_query("What is the present value of £10,000 received in 3 years at a discount rate of 5% "
                                  "a year?")
    assert {o.name: o.display_value for o in result.outputs} == {"present_value": "£8,638.38",
                                                                  "discount_factor": "0.863838"}
    assert result.steps == ["Present value = £10,000.00 ÷ (1 + 5%)^3 = £10,000.00 ÷ 1.157625 = £8,638.38"]
    assert result.notes == ["Discounted annually at 5% for 3 whole year(s), the amount received at the end of year 3."]
    assert [i.name for i in result.inputs] == ["future_amount", "discount_rate", "years"]
    assert outputs("What is the present value of $5,000 due in 2 years at 8%?")["present_value"] == "$4,286.69"


@pytest.mark.parametrize("question, converted", [
    ("Convert $2,500 to pounds at an exchange rate of £1 = $1.25.", "£2,000.00"),
    ("Convert £2,000 to dollars at £1 = $1.25.", "$2,500.00"),
])
def test_a_conversion_at_the_stated_rate_goes_the_right_way(question, converted):
    result = calculate_from_query(question)
    assert outputs(question)["converted_amount"] == converted
    assert "not a live market rate" in result.notes[0]


@pytest.mark.parametrize("question", ["Convert $2,500 to pounds.", "What is the present value of £10,000?"])
def test_without_a_stated_rate_nothing_is_computed(question):
    assert calculate_from_query(question).status != "success"


def test_every_result_states_its_rounding():
    result = calculate_from_query("What is the present value of £10,000 received in 3 years at 5%?")
    assert result.rounding == ("Exact decimal arithmetic with intermediate values unrounded; amounts and percentages "
                               "are shown rounded half-up to 2 decimal places.")


# ── A model figure that differs from the engine's ────────────────────────

INPUT_VAT = calculate_from_query("A UK business buys supplies for £6,000 including VAT at 20%. How much input VAT?")


@pytest.mark.parametrize("answer", [
    "The input VAT you can reclaim is £1,000 (one-sixth of £6,000).",
    "Input VAT: £1,000.00. The VAT rate is 20%.",
    "VAT at 20% applies to the £6,000; the net cost is £5,000.",
    "Input VAT is the VAT paid on business purchases.",
])
def test_the_engines_own_figures_and_the_users_are_not_flagged(answer):
    assert calculation_discrepancies(answer, INPUT_VAT) == []


def test_a_different_figure_for_a_calculated_quantity_is_flagged():
    [finding] = calculation_discrepancies("The input VAT you can reclaim is £1,200 (20% of £6,000).", INPUT_VAT)
    assert finding.rule == "calculation_mismatch"
    assert calculation_note([finding]) == (
        f"{CALCULATION_PREFIX}: the answer states £1,200 for the VAT; the application's exact calculation from your "
        "figures gives £1,000.00. Have the figure reviewed before relying on it.")


def test_a_rounded_statement_of_the_result_is_not_a_mismatch():
    pv = calculate_from_query("What is the present value of £10,000 received in 3 years at 5%?")
    assert calculation_discrepancies("The present value is about £8,638.", pv) == []
    assert calculation_discrepancies("The present value is £8,500.", pv)[0].message.endswith("gives £8,638.38")


def test_no_engine_result_means_nothing_to_compare():
    assert calculation_discrepancies("Input VAT is £1,200.", None) == []
    assert calculation_discrepancies("Input VAT is £1,200.", calculate_from_query("hello")) == []


MIXED = ("A UK business buys supplies for £6,000 including VAT at 20%. How much input VAT can it reclaim, and why can "
         "a business reclaim input VAT at all?")


async def test_through_the_pipeline_a_wrong_model_figure_is_disclosed_not_replaced(pipeline):
    pipeline.answers(AgentOutcome(text="Input VAT is the VAT paid on purchases. The input VAT you can reclaim is "
                                       "£1,200 (20% of £6,000)."))
    response, audited = await pipeline.ask(MIXED)
    assert any(item.startswith(f"{CALCULATION_PREFIX}: the answer states £1,200") for item in response.answer.limitations)
    assert page_status(response) == "Partially answered" and audited.completeness == "partial"
    assert "£1,200" in response.answer.text                              # disclosed, never silently changed
    assert service.audit_accounting_review_flagged.await_args.kwargs["findings"][0]["rule"] == "calculation_mismatch"


async def test_through_the_pipeline_the_right_figure_raises_nothing(pipeline):
    pipeline.answers(AgentOutcome(text="Input VAT is the VAT paid on purchases. The input VAT you can reclaim is "
                                       "£1,000 (one-sixth of £6,000)."))
    response, _ = await pipeline.ask(MIXED)
    assert not any(item.startswith(CALCULATION_PREFIX) for item in response.answer.limitations)
    assert not service.audit_accounting_review_flagged.await_args_list


def test_a_deterministic_answer_never_reaches_the_model():
    # The engine's own result is the answer; the comparison guards answers the
    # model writes around it.
    assert "authoritative_calculation[:] = [calculation_result]" in inspect.getsource(service.ask_kriton)


def test_decimal_exactness():
    assert calculate_from_query("What is the present value of £10,000 received in 3 years at 5%?").outputs[0].value \
        == Decimal(10000) / Decimal("1.05") ** 3


# ── Review of 24 Oct 2026: like with like, rounding, no rule from a symbol ──

def test_the_pound_never_supplies_a_rate_or_a_treatment():
    # The £ only spares asking for the country once the user has given the
    # rate and the treatment; the arithmetic is then the same anywhere.
    assert "the VAT rate or rates that apply" in missing_vat_inputs("Calculate VAT on £72,000 including VAT")
    assert "whether the amounts include VAT" in missing_vat_inputs("Calculate VAT on £72,000 at 20%")


@pytest.mark.parametrize("question, vat, other", [
    ("A UK business buys supplies for £99.99 including VAT at 20%. How much input VAT?", "£16.67", "£83.32"),
    ("A UK business sells goods for £0.05 excluding VAT at 20%. What VAT does it charge?", "£0.01", "£0.06"),
])
def test_rounding_is_half_up_on_the_exact_result_only(question, vat, other):
    shown = outputs(question)
    assert shown["vat_amount"] == vat and other in shown.values()


OUTPUT_VAT = calculate_from_query("A UK business sells goods for £6,000 excluding VAT at 20%. What VAT and total?")
PV = calculate_from_query("What is the present value of £10,000 received in 3 years at 5%?")


@pytest.mark.parametrize("result, answer", [
    (OUTPUT_VAT, "The VAT-inclusive total is £7,000."),        # another basis, not the VAT
    (INPUT_VAT, "Input VAT rate 20% applies."),                # a rate, not the amount
    (INPUT_VAT, "Input VAT is €1,200 at today's rate."),       # another currency
    (PV, "The present value per month is £720."),              # another period
])
def test_a_figure_for_a_different_quantity_is_not_compared(result, answer):
    assert calculation_discrepancies(answer, result) == []


@pytest.mark.parametrize("result, answer, message", [
    (OUTPUT_VAT, "The customer pays £7,000 in total.",
     "the answer states £7,000 for the total including VAT; the application's exact calculation from your figures "
     "gives £7,200.00"),
    (calculate_from_query("In a VAT quarter a UK business has sales of £120,000 excluding VAT and purchases of £60,000 "
                          "including VAT, all standard-rated at 20%. What VAT does it pay to HMRC?"),
     "VAT payable to HMRC is £12,000.",
     "the answer states £12,000 for the VAT payable; the application's exact calculation from your figures gives "
     "£14,000.00"),
])
def test_the_same_quantity_with_another_value_is_named_exactly(result, answer, message):
    assert [f.message for f in calculation_discrepancies(answer, result)] == [message]


# ── Decision 1 (24 Oct 2026): "£ means UK" kept, with its limits ──────────
# The symbol spares a redundant question once the rate and the treatment are
# given; it is never evidence of jurisdiction or authority for UK tax law.

from app.orchestration.source_taxonomy import detect_jurisdictions  # noqa: E402
from app.orchestration.verification_service import requires_authoritative_evidence  # noqa: E402


@pytest.mark.parametrize("question", ["What rate applies to my £5,000 sale?", "What tax applies to my £5,000 sale?"])
def test_a_pound_sign_is_not_evidence_of_jurisdiction(question):
    assert detect_jurisdictions(question) == []


def test_a_missing_rate_or_treatment_is_still_asked_for_beside_a_pound():
    assert "the VAT rate or rates that apply" in missing_vat_inputs("Calculate VAT on £72,000 including VAT")
    assert "whether the amounts include VAT" in missing_vat_inputs("Calculate VAT on £72,000 at 20%")


def test_do_not_ask_again_is_respected_when_every_input_is_given():
    question = ("Sales were £150,000, including VAT at 20%. Calculate sales excluding VAT and the VAT amount. "
                "Do not ask for a jurisdiction because I have supplied the rate and treatment.")
    assert missing_vat_inputs(question) is None
    assert outputs(question)["vat_amount"] == "£25,000.00"


def test_a_tax_law_answer_still_needs_its_jurisdictions_authority():
    # Stating a rate or rule is held to cited, authoritative evidence whatever
    # currency the question uses; the evidence checks then test that source's
    # jurisdiction (test_evidence_validation.py).
    assert requires_authoritative_evidence("What VAT rate applies to my £5,000 sale?",
                                           "What VAT rate applies to my £5,000 sale?")


# ── "VAT" alone means the UK only when no other country's currency is used ──

@pytest.mark.parametrize("question, jurisdictions", [
    ("What VAT rate applies to my €5,000 sale?", []),
    ("VAT on $5,000 of sales", []),
    ("GST on £5,000", []),
    ("Corporation tax on €100,000 profit", []),
    ("What VAT rate applies to my sale?", ["UK"]),            # unchanged: no currency
    ("What VAT applies to my £5,000 sale?", ["UK"]),         # unchanged: its own currency
    ("GST on ₹50,000", ["INDIA"]),
    ("GST on $5,000 in Australia", ["AUSTRALIA"]),           # a named country always wins
])
def test_a_tax_word_does_not_override_the_currency_used(question, jurisdictions):
    assert detect_jurisdictions(question) == jurisdictions


# ── Live check on 3000, 24 Oct 2026 ───────────────────────────────────────

from types import SimpleNamespace  # noqa: E402

from app.orchestration.calculations.engine import calculation_markdown  # noqa: E402
from app.orchestration.input_requirements import missing_vat_country  # noqa: E402
from app.orchestration.verification_service import calculated_figures, verify_for_release  # noqa: E402

RETURN_Q = ("In a VAT quarter a UK business has sales of £120,000 excluding VAT and purchases of £60,000 including "
            "VAT, all at 20%. What VAT does it pay to HMRC?")
RETURN_FIGURES = calculated_figures(calculate_from_query(RETURN_Q), question=RETURN_Q)

UK_TURN = [SimpleNamespace(role="user", content="A UK business buys supplies for £6,000 including VAT at 20%.")]


def test_an_earlier_uk_turn_does_not_carry_over_to_a_euro_question():
    question = "A business buys supplies for €6,000 including VAT at 20%. How much input VAT can it reclaim?"
    assert "which country" in missing_vat_inputs(question, UK_TURN)
    # The same currency as before: the country is not asked again.
    assert missing_vat_inputs("A business buys supplies for £6,000 including VAT at 20%. How much input VAT?",
                              UK_TURN) is None


@pytest.mark.parametrize("question, asks", [
    ("What VAT rate applies to my €5,000 sale?", True),
    ("Do I need to register for VAT on $95,000 of sales?", True),
    ("What VAT rate applies to my sale?", False),                        # no currency: unchanged
    ("What is the VAT rate in Germany for a €5,000 sale?", False),       # the country is named
    ("What VAT applies to my £5,000 sale?", False),
])
def test_a_rate_question_in_another_countrys_currency_asks_the_country(question, asks):
    assert (missing_vat_country(question) is not None) is asks


def test_a_source_marker_is_not_read_as_a_figure():
    answer = ("Input VAT is the VAT paid on purchases and can be reclaimed [REF-3]. "
              "The input VAT you can reclaim is £1,000.")
    assert calculation_discrepancies(answer, INPUT_VAT) == []


def test_a_bare_number_beside_a_label_is_not_an_amount():
    assert calculation_discrepancies("Input VAT is covered in section 3 of the notice.", INPUT_VAT) == []


def test_calculation_labels_keep_the_tax_names_capitalised():
    table = calculation_markdown(INPUT_VAT)
    assert "| VAT amount | £1,000.00 |" in table and "| Amount excluding VAT | £5,000.00 |" in table
    assert "Vat Amount" not in table


async def test_a_cited_restatement_of_the_calculated_result_is_kept():
    # "…the amount due to HMRC for the quarter is £14,000 [REF-1]" was removed
    # as not in the cited evidence, and the answer marked partial.
    check = await verify_for_release(
        "Therefore the amount due to HMRC for the quarter is £14,000 [REF-1].",
        question=RETURN_Q, evidence=["[REF-1] VAT guidance."], requires_authority=True, calculated=RETURN_FIGURES)
    assert check.passed


async def test_a_cited_rule_beside_a_calculated_figure_is_still_checked():
    check = await verify_for_release(
        "The VAT rate is 20%, so the amount due is £14,000 [REF-1].",
        question=RETURN_Q, evidence=[], requires_authority=True, calculated=RETURN_FIGURES)
    assert not check.passed


@pytest.mark.parametrize("question", [
    "Compare the GBP/USD reference rate published on 15 October 2026 with a bank's executable quote, and cite the VAT "
    "rules that apply.",
    "What is the USD to EUR exchange rate, and is VAT charged on currency exchange?",
])
def test_an_exchange_rate_question_that_mentions_vat_is_not_asked_for_a_country(question):
    assert missing_vat_country(question) is None


@pytest.mark.parametrize("sentence, kept", [
    ("Therefore, based on the figures above, the business must pay **£14,000** to HMRC.", True),
    ("The business has to pay £14,000 to HMRC for the quarter [REF-1].", True),
    ("The business must register for VAT and pay £14,000.", False),           # a rule beside the result
    ("The business must pay £15,000 to HMRC.", False),                        # not the calculated result
])
def test_owing_the_calculated_amount_is_not_a_rule(sentence, kept):
    from app.orchestration.verification_service import _from_verified_calculation
    assert _from_verified_calculation(sentence, RETURN_FIGURES) is kept
