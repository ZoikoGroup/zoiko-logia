"""
Unit tests for app/domains/calculation/router.py — Phase 4 of the governed
calculation architecture (docs/calculation_architecture.md).

The core property under test throughout: the router decides which engine
runs, never the LLM, and a professional-methodology calculation can never
be silently downgraded to generic arithmetic.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.calculation.router import (
    route,
    CalculationRequest,
    ENGINE_POLICYENGINE,
    ENGINE_FORMULA_REGISTRY,
    ENGINE_EXPRESSION_EVALUATOR,
    ENGINE_UNSUPPORTED,
)
from app.domains.calculation.arithmetic_extraction import extract_arithmetic_expression


def test_statutory_tax_routes_to_policyengine():
    decision = route(CalculationRequest(calculation_type="federal_income_tax"))
    assert decision.engine == ENGINE_POLICYENGINE
    assert decision.status == "routed"


def test_child_tax_credit_routes_to_policyengine():
    decision = route(CalculationRequest(calculation_type="ctc"))
    assert decision.engine == ENGINE_POLICYENGINE


def test_eitc_routes_to_policyengine():
    decision = route(CalculationRequest(calculation_type="eitc"))
    assert decision.engine == ENGINE_POLICYENGINE


def test_named_accounting_formula_routes_to_formula_registry_and_executes():
    decision = route(CalculationRequest(
        calculation_type="gross_margin",
        inputs={
            "revenue": {"value": "250000", "unit": "USD"},
            "cost_of_goods_sold": {"value": "180000", "unit": "USD"},
        },
    ))
    assert decision.engine == ENGINE_FORMULA_REGISTRY
    assert decision.status == "executed"
    assert decision.formula_id == "accounting.gross_margin.v1"
    assert decision.result.output_value == "28.00"


def test_named_formula_by_fully_qualified_id_also_routes_correctly():
    decision = route(CalculationRequest(
        calculation_type="accounting.gross_margin.v1",
        inputs={
            "revenue": {"value": "250000", "unit": "USD"},
            "cost_of_goods_sold": {"value": "180000", "unit": "USD"},
        },
    ))
    assert decision.engine == ENGINE_FORMULA_REGISTRY
    assert decision.status == "executed"


def test_straight_line_depreciation_routes_to_formula_registry():
    decision = route(CalculationRequest(
        calculation_type="straight_line_depreciation",
        inputs={
            "asset_cost": {"value": "50000", "unit": "USD"},
            "salvage_value": {"value": "0", "unit": "USD"},
            "useful_life_years": {"value": "10", "unit": "years"},
        },
    ))
    assert decision.engine == ENGINE_FORMULA_REGISTRY
    assert decision.result.output_value == "5000.00"


def test_plain_arithmetic_routes_to_expression_evaluator():
    decision = route(CalculationRequest(calculation_type="arithmetic", expression="250000 - 180000"))
    assert decision.engine == ENGINE_EXPRESSION_EVALUATOR
    assert decision.status == "executed"
    assert decision.result.result == "70000"


def test_bare_depreciation_without_method_is_missing_input_not_a_guess():
    """'Calculate depreciation' without a method or useful life named must
    never silently pick straight-line or fall back to raw arithmetic — it's
    simply not a recognized calculation_type on its own."""
    decision = route(CalculationRequest(calculation_type="depreciation"))
    assert decision.engine == ENGINE_UNSUPPORTED


def test_unsupported_jurisdiction_specific_tax_is_unsupported_not_guessed():
    decision = route(CalculationRequest(calculation_type="uk_vat"))
    assert decision.engine == ENGINE_UNSUPPORTED
    assert decision.status == "unsupported"


def test_no_calculation_type_and_no_expression_is_unsupported():
    decision = route(CalculationRequest())
    assert decision.engine == ENGINE_UNSUPPORTED


# ── The critical downgrade-prevention property ──────────────────────────────

def test_named_formula_type_is_never_downgraded_to_a_supplied_expression():
    """A caller (or an LLM) supplying calculation_type='gross_margin' AND a
    distractor expression must still get the governed formula result, never
    the raw expression — the professional methodology always wins."""
    decision = route(CalculationRequest(
        calculation_type="gross_margin",
        expression="999999999",  # deliberately wrong, must be ignored
        inputs={
            "revenue": {"value": "250000", "unit": "USD"},
            "cost_of_goods_sold": {"value": "180000", "unit": "USD"},
        },
    ))
    assert decision.engine == ENGINE_FORMULA_REGISTRY
    assert decision.result.output_value == "28.00"


def test_statutory_tax_type_is_never_downgraded_even_with_an_expression_present():
    decision = route(CalculationRequest(calculation_type="federal_income_tax", expression="1+1"))
    assert decision.engine == ENGINE_POLICYENGINE


def test_unrecognized_calculation_type_never_falls_back_to_arithmetic_even_with_an_expression():
    """An unrecognized calculation_type with an expression attached must
    stay unsupported, not silently execute the expression — only the
    literal 'arithmetic'/'expression' calculation_type reaches the
    evaluator, exactly so a mis-typed or unknown formula name can't be
    quietly routed around."""
    decision = route(CalculationRequest(calculation_type="some_unknown_ratio", expression="1+1"))
    assert decision.engine == ENGINE_UNSUPPORTED


# ── End-to-end with the real query-text extractor ───────────────────────────

def test_real_incident_revenue_minus_expenses_end_to_end():
    query = "If revenue is $250,000 and expenses are $180,000, what is the net profit?"
    expression = extract_arithmetic_expression(query)
    assert expression is not None
    decision = route(CalculationRequest(calculation_type="arithmetic", expression=expression))
    assert decision.engine == ENGINE_EXPRESSION_EVALUATOR
    assert decision.result.result == "70000"


def test_real_incident_sales_tax_end_to_end():
    query = "Calculate the sales tax on a $1,200 purchase at a 7.25% rate."
    expression = extract_arithmetic_expression(query)
    assert expression is not None
    decision = route(CalculationRequest(calculation_type="arithmetic", expression=expression))
    assert decision.engine == ENGINE_EXPRESSION_EVALUATOR
    assert decision.result.result == "87.0000"


def test_missing_formula_inputs_surfaces_as_missing_input_status():
    decision = route(CalculationRequest(
        calculation_type="gross_margin",
        inputs={"revenue": {"value": "250000", "unit": "USD"}},
    ))
    assert decision.engine == ENGINE_FORMULA_REGISTRY
    assert decision.status == "missing_input"
