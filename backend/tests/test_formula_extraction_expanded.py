from app.domains.calculation.formula_extraction import extract_named_formula, identify_missing_formula_inputs
from app.domains.calculation.formula_registry import execute_formula
from app.orchestration.service import _compose_formula_result, _compose_policyengine_result
from app.domains.calculation.household_extraction import HouseholdParams
from app.domains.calculation.policyengine_engine import CalculationResult


def test_extracts_accounting_net_profit():
    result = extract_named_formula("Calculate net profit when revenue is $250,000 and total expenses are $180,000.")
    assert result is not None
    assert result.calculation_type == "net_profit"
    assert result.inputs["revenue"]["value"] == "250000"


def test_depreciation_accepts_natural_asset_costing_and_prefixed_salvage_value():
    result = extract_named_formula(
        "Calculate straight-line depreciation for an asset costing $120,000, "
        "with a $20,000 salvage value and a 5-year useful life."
    )
    assert result is not None
    assert result.calculation_type == "straight_line_depreciation"
    assert result.inputs["asset_cost"]["value"] == "120000"
    assert result.inputs["salvage_value"]["value"] == "20000"
    assert result.inputs["useful_life_years"]["value"] == "5"


def test_depreciation_accepts_transcript_wording_without_redundant_useful():
    result = extract_named_formula(
        "Calculate straight-line depreciation for a $50,000 asset, "
        "$5,000 salvage value, 10-year life."
    )
    assert result is not None
    assert result.inputs["useful_life_years"]["value"] == "10"
    calculated = execute_formula("accounting.straight_line_depreciation.v1", result.inputs)
    assert calculated.output_value == "4500.00"


def test_depreciation_accepts_life_of_years_word_order():
    result = extract_named_formula(
        "Calculate straight-line depreciation for an asset costing $50,000, "
        "salvage value of $5,000, and a life of 10 years."
    )
    assert result is not None
    assert result.inputs["useful_life_years"]["value"] == "10"


def test_depreciation_accepts_an_adjective_between_line_and_depreciation():
    """Real incident (2026-07-29): "straight-line ANNUAL depreciation" never
    matched the trigger pattern at all (it required "line" directly followed
    by "depreciation"), which silently routed the query into the generic
    catch-all fallback (claims all 4 inputs missing regardless of what's
    actually present) instead of this precise extraction path — even though
    every input was cleanly present and extractable."""
    result = extract_named_formula(
        "Calculate straight-line annual depreciation for an asset costing "
        "$120,000, with a $20,000 residual value and a useful life of 10 years."
    )
    assert result is not None
    assert result.calculation_type == "straight_line_depreciation"
    assert result.inputs["asset_cost"]["value"] == "120000"
    assert result.inputs["salvage_value"]["value"] == "20000"
    assert result.inputs["useful_life_years"]["value"] == "10"
    calculated = execute_formula("accounting.straight_line_depreciation.v1", result.inputs)
    assert calculated.output_value == "10000.00"


def test_depreciation_accepts_residual_value_as_salvage_value_synonym():
    """"Residual value" is the same input as "salvage value" (the asset's
    expected value at the end of its useful life) — a real query used the
    synonym and it wasn't recognized at all."""
    result = extract_named_formula(
        "Calculate straight-line depreciation for an asset costing $50,000, "
        "with a $5,000 residual value and a useful life of 10 years."
    )
    assert result is not None
    assert result.inputs["salvage_value"]["value"] == "5000"


def test_depreciation_adjective_tolerance_does_not_break_plain_phrasing():
    """Regression guard: the trigger fix must not require the adjective —
    plain 'straight-line depreciation' (no inserted word) still matches."""
    result = extract_named_formula(
        "Calculate straight-line depreciation for an asset costing $80,000, "
        "with a $10,000 salvage value and a useful life of 5 years."
    )
    assert result is not None


def test_depreciation_definitional_question_still_has_no_calculation_intent():
    """Regression guard: the trigger fix must not make a purely definitional
    question ("what is X") look like a calculation request."""
    assert extract_named_formula("What is straight-line annual depreciation?") is None
    assert identify_missing_formula_inputs("What is straight-line annual depreciation?") is None


def test_genuinely_missing_one_depreciation_input_reports_only_that_one():
    """Regression guard for the trigger fix: when the trigger correctly
    matches and exactly one input is genuinely absent, only that one field
    is reported — not the generic catch-all's blanket 'all 4 missing'."""
    missing = identify_missing_formula_inputs(
        "Calculate straight-line depreciation for an asset costing $50,000 "
        "with a $5,000 salvage value."
    )
    assert missing is not None
    assert missing.calculation_type == "straight_line_depreciation"
    assert missing.missing_inputs == ("useful_life_years",)


def test_generic_depreciation_asks_for_specific_calculation_inputs():
    missing = identify_missing_formula_inputs("Calculate my depreciation.")
    assert missing is not None
    assert missing.calculation_type == "depreciation"
    assert missing.missing_inputs == (
        "depreciation_method", "asset_cost", "salvage_value", "useful_life_years",
    )


def test_extracts_taxable_income_scenario_without_deciding_allowability():
    result = extract_named_formula(
        "Calculate taxable income scenario: gross income $100,000, adjustments $5,000, deductions $15,000."
    )
    assert result is not None
    assert result.calculation_type == "taxable_income_scenario"


def test_extracts_user_selected_audit_materiality():
    result = extract_named_formula(
        "Calculate overall materiality with benchmark amount $5,000,000 and user selected percentage 1%."
    )
    assert result is not None
    assert result.calculation_type == "materiality"
    assert result.inputs["user_selected_percentage"]["unit"] == "percent"


def test_extracts_projected_misstatement():
    result = extract_named_formula(
        "Calculate projected misstatement: sample misstatement $2,000, sample book value $100,000, population book value $1,000,000."
    )
    assert result is not None
    assert result.calculation_type == "projected_misstatement"


def test_missing_required_input_never_guesses():
    assert extract_named_formula("Calculate materiality with benchmark amount $5,000,000.") is None
    missing = identify_missing_formula_inputs("Calculate materiality with benchmark amount $5,000,000.")
    assert missing is not None
    assert missing.calculation_type == "materiality"
    assert missing.missing_inputs == ("user_selected_percentage",)


def test_verified_formula_response_exposes_provenance_and_assumptions():
    result = execute_formula("audit.materiality.v1", {
        "benchmark_amount": {"value": "5000000", "unit": "USD"},
        "user_selected_percentage": {"value": "1", "unit": "percent"},
    })
    answer = _compose_formula_result(result, "REF-1", "Show detailed steps, assumptions, and methodology.")
    assert "### Verified result" in answer
    assert "### Inputs" in answer
    assert "### Calculation steps" in answer
    assert "### Assumptions and judgment boundaries" in answer
    assert result.calculation_id in answer
    assert result.formula_id in answer


def test_extracts_debt_to_equity_instead_of_using_document_retrieval():
    result = extract_named_formula(
        "Calculate the debt-to-equity ratio when total liabilities are $400,000 and total equity is $200,000."
    )
    assert result is not None
    assert result.calculation_type == "debt_to_equity"


def test_extracts_taxable_income_with_explicit_user_supplied_rate():
    result = extract_named_formula(
        "If taxable income is $80,000 and the user-supplied rate is 15%, calculate the scenario tax."
    )
    assert result is not None
    assert result.calculation_type == "tax_from_supplied_rate"


def test_simple_interest_accepts_number_before_years_label():
    result = extract_named_formula("Calculate simple interest on principal $10,000 at annual rate 5% for 3 years.")
    assert result is not None
    assert result.inputs["time_years"]["value"] == "3"


def test_default_calculation_response_is_concise_but_auditable():
    result = execute_formula("accounting.net_profit.v1", {
        "revenue": {"value": "250000", "unit": "USD"},
        "total_expenses": {"value": "180000", "unit": "USD"},
    })
    answer = _compose_formula_result(result, "REF-1", "Calculate net profit.")
    assert "**$70,000.00**" in answer
    assert "### Inputs" not in answer
    assert "### Methodology and audit trail" not in answer
    assert result.calculation_id in answer


def test_policyengine_tax_result_is_rendered_without_personalized_advice_language():
    result = CalculationResult(
        household=HouseholdParams(
            annual_income=75000, filing_status="SINGLE", num_dependents=0,
            tax_year=2026, state_code=None,
        ),
        values={"income_tax": 8123.45},
    )
    answer = _compose_policyengine_result(result, "Calculate my federal income tax.", "REF-1")
    assert "**$8,123.45**" in answer
    assert "you should" not in answer.lower()
    assert "PolicyEngine-US" in answer
