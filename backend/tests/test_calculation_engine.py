from decimal import Decimal

from app.orchestration.calculations.engine import calculate_from_query, calculation_markdown


def test_gross_profit_and_margin():
    result = calculate_from_query(
        "Revenue is £850,000 and cost of sales is £527,000. Calculate gross profit and gross margin."
    )
    assert result.status == "success"
    assert result.formula_ids == ["gross_profit", "gross_margin"]
    assert result.outputs[0].value == Decimal("323000")
    assert result.outputs[1].value == Decimal("38.00")


def test_zero_revenue_returns_undefined_not_infinity():
    result = calculate_from_query(
        "Calculate gross margin where revenue is £0 and gross profit is £10,000."
    )
    assert result.status == "undefined"
    assert result.error_code == "DIVISION_BY_ZERO"
    assert result.outputs == []


def test_vat_and_gross_total():
    result = calculate_from_query(
        "An invoice has a net amount of £100 and VAT is 20%. Calculate the VAT and gross total."
    )
    assert result.status == "success"
    assert [item.value for item in result.outputs] == [Decimal("20"), Decimal("120")]


def test_reverse_vat():
    result = calculate_from_query(
        "An invoice total of £12,000 includes VAT at 20%. Calculate reverse VAT and the net amount."
    )
    assert result.status == "success"
    assert result.formula_ids == ["reverse_vat"]
    assert result.outputs[0].value == Decimal("10000")
    assert result.outputs[1].value == Decimal("2000")


def test_current_ratio():
    result = calculate_from_query(
        "Current assets are £420,000 and current liabilities are £210,000. Calculate the current ratio."
    )
    assert result.status == "success"
    assert result.outputs[0].value == Decimal("2")


def test_quick_ratio():
    result = calculate_from_query(
        "Current assets are £420,000, inventory is £120,000, and current liabilities are £210,000. Calculate quick ratio."
    )
    assert result.status == "success"
    assert result.outputs[0].value == Decimal("300000") / Decimal("210000")


def test_debt_to_equity_zero_equity_is_undefined():
    result = calculate_from_query(
        "Total liabilities are £780,000 and equity is £0. Calculate debt-to-equity ratio."
    )
    assert result.status == "undefined"
    assert result.error_code == "DIVISION_BY_ZERO"


def test_straight_line_depreciation():
    result = calculate_from_query(
        "An asset cost is £96,000, residual value is £6,000, and useful life is 5 years. Calculate straight-line depreciation."
    )
    assert result.status == "success"
    assert result.outputs[0].value == Decimal("18000")


def test_break_even_units():
    result = calculate_from_query(
        "Selling price is £80, variable cost is £48, and fixed costs are £160,000. Calculate break-even units."
    )
    assert result.status == "success"
    assert result.outputs[0].value == Decimal("32")
    assert result.outputs[1].value == Decimal("5000")


def test_missing_input_requests_clarification():
    result = calculate_from_query("Revenue is £200. Calculate gross margin.")
    assert result.status == "clarification_required"
    assert result.error_code == "MISSING_INPUT"


def test_currency_mismatch_requests_clarification():
    result = calculate_from_query(
        "Revenue is £200 and cost of sales is $100. Calculate gross profit."
    )
    assert result.status == "clarification_required"
    assert result.error_code == "CURRENCY_MISMATCH"


def test_non_calculation_does_not_intercept_existing_orchestration():
    result = calculate_from_query("Explain revenue recognition under IFRS 15.")
    assert result.matched is False
    assert result.status == "not_matched"


def test_answer_markdown_does_not_repeat_verification_acknowledgement():
    result = calculate_from_query(
        "An invoice has a net amount of £100 and VAT is 20%. Calculate the VAT and gross total."
    )
    answer = calculation_markdown(result)
    assert "Calculated deterministically" not in answer
    assert "Verification passed" not in answer
