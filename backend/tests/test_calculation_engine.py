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


def test_vat_rate_a_few_words_after_its_label_is_read():
    # Reported live: asked for the VAT rate it had just been given.
    result = calculate_from_query(
        "An invoice total is £120 including VAT at a supplied rate of 20%. "
        "Calculate the amount before VAT and the VAT amount."
    )
    assert result.status != "clarification_required"
    values = {output.name: output.value for output in result.outputs}
    assert Decimal("100") in values.values() and Decimal("20") in values.values()


def test_negative_money_puts_the_sign_before_the_symbol():
    result = calculate_from_query("Revenue is ₹80,000 and expenses are ₹100,000. Calculate profit and profit margin.")
    text = calculation_markdown(result)
    assert "-₹20,000.00" in text and "₹-" not in text


def test_checking_the_users_own_arithmetic_is_a_self_contained_calculation():
    from app.orchestration.calculation_service import is_self_contained_calculation
    assert is_self_contained_calculation(
        "Subtotal is ₹10,000, tax is ₹1,800 and the stated total is ₹11,500. Check the arithmetic."
    )


def test_a_figure_written_as_zero_counts_toward_a_self_contained_calculation():
    from app.orchestration.calculation_service import is_self_contained_calculation
    assert is_self_contained_calculation("Revenue is zero and expenses are ₹15,000. Calculate profit margin.")


MULTI = (
    "9 Cost £80, selling price £100. Markup and margin? "
    "15 Machine cost £50,000, residual £5,000, life 5 years. Straight-line depreciation?"
)


def test_several_questions_are_not_forced_through_one_formula():
    from app.orchestration.calculation_service import build_calculation
    assert build_calculation(MULTI) is None
    # Each problem is now solved with its own inputs (it used to be refused).
    result = calculate_from_query(MULTI)
    assert [(o.name, o.display_value) for o in result.outputs] == [
        ("Question 9 markup", "25.00%"), ("Question 9 margin", "20.00%"),
        ("Question 15 annual depreciation", "£9,000.00")]


def test_depreciation_needs_cost_above_residual():
    from app.orchestration.calculation_service import build_calculation
    assert build_calculation("Cost £80, residual £5,000, life 5 years. Straight-line depreciation") is None
    calc = build_calculation("Machine cost £50,000, residual £5,000, life 5 years. Straight-line depreciation")
    assert calc is not None and calc.result == Decimal("9000")


def test_current_assets_are_not_a_current_rate_lookup():
    from app.orchestration.calculation_service import needs_lookup
    assert not needs_lookup("Current assets ₹2,50,000, current liabilities ₹1,00,000. Current ratio?")
    assert needs_lookup("What is the current VAT rate?")


def test_current_and_quick_ratio_is_not_a_lookup():
    from app.orchestration.calculation_service import needs_lookup
    assert not needs_lookup("Current assets 2,50,000, inventory 50,000. Current and quick ratio?")


def test_an_exponent_is_not_misread_as_a_mismatch():
    from app.orchestration.calculation_service import validate_answer_calculations
    assert validate_answer_calculations("CAGR = (150,000 ÷ 100,000)^(1/3) − 1 = 0.144714 → 14.47 %") == []
    assert validate_answer_calculations("Future value = 10,000 × (1 + 0.08)**10 = 21,589.25") == []
    # Ordinary lines are still checked.
    assert validate_answer_calculations("Interest = 50,000 × 0.08 × 3 = 13,000")


def test_a_percentage_after_an_operator_is_checked():
    from app.orchestration.calculation_service import validate_answer_calculations
    # Live: "₹40,000 × 12% = ₹2,400" (really ₹4,800) went out unchecked.
    assert validate_answer_calculations("₹40,000 × 12 % = ₹2,400")
    assert validate_answer_calculations("IGST = ₹40,000 × 18% = ₹7,200") == []
    assert validate_answer_calculations("200,000 / 500,000 = 40%") == []


def test_cost_of_sales_is_derived_from_revenue_and_gross_profit():
    result = calculate_from_query("Revenue £180,000, gross profit £72,000. What is the cost of sales and gross margin?")
    values = {output.name: output.value for output in result.outputs}
    assert values["cost_of_sales"] == Decimal("108000") and values["gross_margin"] == Decimal("40")


def test_indian_digit_grouping_in_chart_amounts():
    from app.orchestration.extraction import extract_user_visual_evidence
    evidence = extract_user_visual_evidence(
        "Donut chart of expenses: rent ₹40,000, salaries ₹1,20,000, utilities ₹15,000, travel ₹25,000", "COMPOSITION",
    )
    # Live: salaries read as ₹1 — 0.00125% of an ₹80,001 total.
    assert [(o.dimension, round(o.value, 2)) for o in evidence.composition] == [
        ("rent", 20.0), ("salaries", 60.0), ("utilities", 7.5), ("travel", 12.5),
    ]


def test_a_chart_of_supplied_figures_is_self_contained():
    from app.orchestration.calculation_service import is_self_contained_calculation
    assert is_self_contained_calculation(
        "Waterfall chart from revenue to net profit: revenue 500, cost of sales −300, operating expenses −120, tax −20 (£k)"
    )
    assert not is_self_contained_calculation("Line chart of UK GDP growth for the last 10 years")


def test_org_chart_and_decision_structures_are_extracted_as_stated():
    from app.orchestration.extraction import extract_graph
    org = extract_graph("Show an org chart: CFO manages Finance Manager and Tax Manager; "
                        "Finance Manager manages two Accountants; Tax Manager manages one Tax Analyst")
    assert [(e.source, e.target) for e in org.edges] == [
        ("CFO", "Finance Manager"), ("CFO", "Tax Manager"), ("Finance Manager", "Accountant 1"),
        ("Finance Manager", "Accountant 2"), ("Tax Manager", "Tax Analyst"),
    ]
    decision = extract_graph("Diagram the UK VAT registration decision: turnover over £90,000 in 12 months → "
                             "must register; expected over £90,000 in next 30 days → must register; "
                             "otherwise → voluntary registration optional")
    assert len(decision.edges) == 3


def test_chart_check_accepts_running_totals_and_signed_figures_but_not_invented_ones():
    import json
    from app.domains.model_gateway.agent import unverified_chart_values

    def spec(values):
        return json.dumps({"type": "line", "series": [{"name": "s", "data": values}]})
    signups = "New sign-ups: Jan 100, Feb 150, Mar 130, Apr 180, May 220, Jun 260"
    assert unverified_chart_values(spec([100, 250, 380, 560, 780, 1040]), signups) == []
    assert unverified_chart_values(spec([20, -5, 15]), "Jan 20, Feb −5, Mar 15") == []
    assert unverified_chart_values(spec([100, 905]), signups) == [905]


def test_tool_meta_sentences_are_removed():
    from app.domains.model_gateway.agent import clean_agent_text
    assert clean_agent_text("Total is 1,040. (No chart is displayed here as tool calls have been halted.)",
                            chart_attached=False) == "Total is 1,040."


def test_org_charts_and_decision_diagrams_are_structured_visuals():
    from app.orchestration.service import _structured_visual_query_is_in_domain
    assert _structured_visual_query_is_in_domain(
        "Show an org chart: CFO manages Finance Manager and Tax Manager; Finance Manager manages two Accountants"
    ) is True
    assert _structured_visual_query_is_in_domain(
        "Diagram the UK VAT registration decision: turnover over £90,000 in 12 months → must register; "
        "otherwise → voluntary registration optional"
    ) is True


def test_scenario_round_fixes():
    from app.orchestration.calculations.engine import calculate_from_query
    from app.orchestration.schemas import ConversationMessage
    from app.orchestration.service import conversation_jurisdiction, figureless_calculation_request
    from app.orchestration.source_taxonomy import detect_jurisdictions
    from app.orchestration.verification_service import requires_authoritative_evidence
    # Figures in a "from … to" shape go to the model, not a clarification.
    assert calculate_from_query("Our revenue grew from £2.4m to £2.9m but gross margin fell from 38% to 33%. "
                                "Calculate gross profit both years.").status == "not_matched"
    # The conversation's country carries into a follow-up that names none.
    history = [ConversationMessage(role="user", content="I'm setting up a UK limited company with profit of £120,000.")]
    assert conversation_jurisdiction("What rate applies at that profit?", history) == "UK"
    assert detect_jurisdictions("What corporation tax rate applies?") == ["UK"]
    assert detect_jurisdictions("What is the Employment Allowance for 2026?") == ["UK"]
    assert detect_jurisdictions("What is the Irish corporation tax rate?") == ["IRELAND"]
    assert requires_authoritative_evidence("Basic salary ₹25,000. Calculate PF and ESI contributions.")
    assert figureless_calculation_request("Calculate my tax")
    assert not figureless_calculation_request("Calculate my tax on £50,000 salary")
