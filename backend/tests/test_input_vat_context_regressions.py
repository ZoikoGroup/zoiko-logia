"""Kriton regression fix: supplied values are parsed and used, invalid values
are rejected rather than treated as missing, VAT intents are kept apart,
standalone questions do not inherit earlier figures, a withheld answer is not
labelled complete, and a question naming no standard still reads the one its
topic belongs to."""
from decimal import Decimal

import pytest

from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.figure_reconciliation import unreconciled_figures
from app.orchestration.input_requirements import missing_vat_inputs
from app.orchestration.official_standards import best_passages, standards_for
from app.orchestration.service import _standalone_with_figures


def out(result, name):
    return next(o.value for o in result.outputs if o.name == name)


# ── Phase 2: deterministic input handling ──────────────────────────────────

def test_cost_and_selling_price_give_profit_margin_and_markup():
    result = calculate_from_query("A product costs £84 and sells for £126. What are the gross profit, gross margin and markup?")
    assert result.status == "success"
    assert out(result, "gross_profit") == Decimal("42")
    assert round(out(result, "gross_margin"), 2) == Decimal("33.33")
    assert out(result, "markup") == Decimal("50")


def test_break_even_gives_units_revenue_and_units_for_a_target_profit():
    result = calculate_from_query(
        "Fixed costs are £72,000, the selling price is £45 per unit and variable cost is £27 per unit. What is the "
        "break-even point in units and revenue, and how many units are needed for a profit of £18,000?")
    assert out(result, "break_even_units") == Decimal("4000")
    assert out(result, "break_even_revenue") == Decimal("180000")
    assert out(result, "units_for_target_profit") == Decimal("5000")


@pytest.mark.parametrize("sign", ["-", "−", "–"])   # hyphen, Unicode minus, en dash
def test_a_negative_vat_rate_is_rejected_not_reported_missing(sign):
    query = f"Calculate VAT at {sign}20% on £500."
    result = calculate_from_query(query)
    assert result.error_code == "INVALID_PERCENTAGE" and "cannot be negative" in result.message
    assert out_names(result) == []
    # Never "please give the VAT rate": the rate was given, and it is invalid.
    assert missing_vat_inputs(query) is None


def out_names(result):
    return [o.name for o in result.outputs]


def test_supplied_values_are_kept_as_user_inputs():
    result = calculate_from_query("A product costs £84 and sells for £126. What is the markup?")
    supplied = {i.value for i in result.inputs if i.source_type == "user"}
    assert {Decimal("84"), Decimal("126")} <= supplied


# ── Phase 3: separate VAT intents ──────────────────────────────────────────

def test_mixed_rate_output_vat_is_calculated_without_asking_about_input_vat():
    query = "A UK business made sales of £8,000 at the standard rate of 20% and £3,000 at 5%. Calculate the output VAT."
    assert missing_vat_inputs(query) is None
    result = calculate_from_query(query)
    assert [out(result, n) for n in ("output_vat_line_1", "output_vat_line_2", "total_output_vat")] == [
        Decimal("1600"), Decimal("150"), Decimal("1750")]


def test_a_vat_payable_question_still_asks_for_what_is_missing():
    # Purchases and "owe" make it a net position: output-only lines must not answer it.
    assert missing_vat_inputs("A business has sales of £120,000 and purchases of £48,000. How much VAT do I owe?")


# ── Phase 4: context isolation ─────────────────────────────────────────────

def test_loss_to_profit_is_an_improvement_with_no_invented_cause():
    result = calculate_from_query("A business went from a loss of £12,000 to a profit of £3,000. What is the improvement?")
    assert out(result, "improvement") == Decimal("15000")
    notes = " ".join(result.notes)
    assert "not meaningful" in notes and "does not say what caused" in notes


@pytest.mark.parametrize("query, standalone", [
    ("A business went from a loss of £12,000 to a profit of £3,000. What is the improvement?", True),
    ("A product costs £84 and sells for £126. What is the markup?", True),
    # Follow-ups keep their history.
    ("What if revenue rises 15%?", False),
    ("Use the same figures but with £5,000 and £9,000", False),
    ("Now compare £4,000 and £6,000", False),
    ("Forecast the next quarter from those figures", False),
])
def test_only_self_contained_figure_questions_drop_the_history(query, standalone):
    assert _standalone_with_figures(query) is standalone


# ── Phase 5: status and figure verification ────────────────────────────────

def test_a_sum_or_difference_of_verified_figures_is_not_withheld():
    evidence = "Original price £20,000. Revised price £22,260."
    assert unreconciled_figures("The revised price is £2,260 more than the original.", evidence) == []
    assert unreconciled_figures("The total of both is £42,260.", evidence) == []
    assert unreconciled_figures("The price rose by £9,999.", evidence) == ["£9,999"]


# ── Phase 6: evidence for questions that name no standard ──────────────────

@pytest.mark.parametrize("question, expected", [
    ("Under IFRS, how is inventory measured when its net realisable value falls below cost?", [("IAS", "2")]),
    ("A company receives £120,000 upfront for a 12-month service contract. When is revenue recognised?",
     [("IFRS", "15")]),
    ("How should a lessee account for a right-of-use asset?", [("IFRS", "16")]),
    ("Under IAS 2, can a write-down be reversed?", [("IAS", "2")]),             # a named standard wins
    ("Under US GAAP, how is inventory measured?", []),                          # never IFRS text for US GAAP
    ("What is accrual accounting?", []),
])
def test_a_topic_names_its_standard(question, expected):
    assert standards_for(question) == expected


STANDARD_TEXT = (
    "Contents\nIAS 2 INVENTORIES – OBJECTIVE: SCOPE; 1: 2\nIAS 2 INVENTORIES – OBJECTIVE: MEASUREMENT; 1: 9\n"
    "IAS 2 INVENTORIES – OBJECTIVE: Effective date; 1: 40\n"
    "8 | Inventories encompass goods purchased and held for resale. "
    "Measurement of inventories\n9 | Inventories shall be measured at the lower of cost [ Refer: paragraphs 10–27 ] "
    "and net realisable value . [ Refer: paragraphs 28–33 ]\n"
    "10 | The cost of inventories shall comprise all costs of purchase, costs of conversion and other costs incurred.\n"
    "Effective date\nC1 | An entity shall apply this Standard for annual periods beginning on or after 1 January 2027. "
    "Earlier application is permitted.\n"
)


def test_the_measurement_rule_is_quoted_clean_and_on_its_own():
    excerpt = best_passages(STANDARD_TEXT, "How is inventory measured when net realisable value falls below cost?", 400)
    assert "Inventories shall be measured at the lower of cost and net realisable value." in excerpt
    assert "Refer" not in excerpt and "OBJECTIVE" not in excerpt


def test_a_matching_later_sentence_brings_its_paragraph_lead():
    excerpt = best_passages(STANDARD_TEXT, "When is it effective and is early application permitted?", 400)
    assert "1 January 2027" in excerpt and "Earlier application is permitted" in excerpt


@pytest.mark.parametrize("limit", [120, 200, 400, 3000])
def test_an_excerpt_stays_within_its_limit(limit):
    # A paragraph too long for the space left was once joined in anyway:
    # IFRS 15 excerpts reached ~90,000 characters against a 3,000 limit.
    long_paragraph = "12 | Revenue shall be recognised over time when control transfers " + "as the service is performed " * 200 + "."
    text = STANDARD_TEXT + long_paragraph + "\n13 | Revenue recognised over time is measured by progress."
    excerpt = best_passages(text, "When is revenue recognised over time as the service is performed?", limit)
    assert len(excerpt) <= limit
    if limit >= 400:
        assert "Revenue recognised over time is measured by progress." in excerpt
