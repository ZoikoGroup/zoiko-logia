from decimal import Decimal

from app.domains.calculation.formula_extraction import extract_named_formula, identify_missing_formula_inputs
from app.domains.calculation.router import CalculationRequest, route
from app.domains.reference_data.user_provided_data import compose_user_provided_results, extract_inline_dataset
from app.orchestration.educational_answers import compose_accounting_fundamentals
from app.orchestration.retrieve import infer_category_rule
from app.orchestration.service import _visual_data_clarification


def _calculated(query: str) -> str:
    extracted = extract_named_formula(query)
    assert extracted is not None
    decision = route(CalculationRequest(calculation_type=extracted.calculation_type, inputs=extracted.inputs))
    assert decision.status == "executed"
    return decision.result.output_value


def test_captured_calculation_phrasings_use_governed_formulas():
    assert _calculated("Calculate gross profit if revenue is $850,000 and cost of sales is $510,000.") == "340000.00"
    assert _calculated("Calculate the profit margin when profit is $120,000 and revenue is $600,000.") == "20.00"
    assert _calculated("Revenue increased from $400,000 to $475,000. Calculate the percentage increase.") == "18.75"
    assert _calculated("Marketing budget was $75,000 and actual spending was $82,500. Calculate the variance.") == "7500.00"


def test_definition_of_materiality_is_not_treated_as_missing_calculation():
    query = "What does materiality mean in an audit?"
    assert extract_named_formula(query) is None
    assert identify_missing_formula_inputs(query) is None
    assert "not defined by one universal fixed percentage" in compose_accounting_fundamentals(query, "REF-1")


def test_captured_core_education_prompts_route_to_reviewed_answers():
    expected = {
        "What is accrual accounting?": "## Accrual accounting",
        "What is the difference between revenue and profit?": "## Revenue and profit compared",
        "Explain how the accounts-payable process works.": "## Accounts-payable process",
        "What is the difference between accounts payable and accounts receivable?": "## Accounts payable and accounts receivable",
        "Compare a balance sheet and an income statement.": "## Balance sheet and income statement",
        "Compare internal audit and external audit.": "## Internal and external audit compared",
        "Create a flowchart showing the invoice-approval process.": "## Accounts-payable process",
        "what are intelectual properites": "## Intellectual property",
    }
    for query, heading in expected.items():
        assert infer_category_rule(query) == "accounting-fundamentals"
        assert heading in compose_accounting_fundamentals(query, "REF-1")


def test_cash_flow_explanation_does_not_equate_cash_balance_with_cash_flow():
    answer = compose_accounting_fundamentals(
        "Explain why cash flow can be positive when a company reports a loss.", "REF-1"
    )
    assert "cash balance at one date does not prove" in answer
    assert "Receivables are collected" in answer


def test_review_budget_variance_uses_current_turn_data():
    query = (
        "Review this budget variance and explain which department needs attention: "
        "Sales budget $90,000 actual $105,000; Marketing budget $80,000 actual $76,000; "
        "Operations budget $120,000 actual $128,000."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Budget", "Actual", "Variance")
    assert dataset.rows[0][-1] == Decimal("15000")


def test_largest_change_analysis_reports_adjacent_change_not_largest_value():
    query = (
        "Analyze these monthly expenses and identify the largest change: "
        "January $80,000, February $92,000, March $87,000 and April $105,000."
    )
    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None
    assert "$18,000 increase from March to April" in answer


def test_private_balance_and_undated_fx_conversion_ask_specific_questions():
    bank = _visual_data_clarification("What is our company's current bank balance?")
    assert bank and "authorized connected bank or accounting source" in bank
    fx = _visual_data_clarification("convert 500 usd to india")
    assert fx and "exchange-rate date" in fx and "INR" in fx
