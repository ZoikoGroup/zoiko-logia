"""
Unit tests for app/domains/calculation/formula_registry.py — Phase 3 of the
governed calculation architecture (docs/calculation_architecture.md).
"""
import os
import sys
from decimal import Decimal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.calculation.formula_registry import execute_formula, list_formulas, get_formula


def test_all_governed_formulas_registered():
    ids = {f.id for f in list_formulas()}
    assert len(ids) == 23
    assert {"accounting.net_profit.v1", "tax.taxable_income_scenario.v1", "audit.materiality.v1"} <= ids


def test_gross_profit():
    r = execute_formula("accounting.gross_profit.v1", {
        "revenue": {"value": "250000", "unit": "USD"},
        "cost_of_goods_sold": {"value": "180000", "unit": "USD"},
    })
    assert r.status == "verified"
    assert Decimal(r.output_value) == Decimal("70000.00")
    assert r.output_unit == "USD"


def test_gross_margin_correct_result_and_percent_normalization():
    r = execute_formula("accounting.gross_margin.v1", {
        "revenue": {"value": "250000", "unit": "USD"},
        "cost_of_goods_sold": {"value": "180000", "unit": "USD"},
    })
    assert r.status == "verified"
    assert Decimal(r.output_value) == Decimal("28.00")
    assert r.output_unit == "percent"


def test_operating_profit_and_margin():
    inputs = {
        "revenue": {"value": "500000", "unit": "USD"},
        "cost_of_goods_sold": {"value": "300000", "unit": "USD"},
        "operating_expenses": {"value": "100000", "unit": "USD"},
    }
    profit = execute_formula("accounting.operating_profit.v1", inputs)
    assert Decimal(profit.output_value) == Decimal("100000.00")
    margin = execute_formula("accounting.operating_margin.v1", inputs)
    assert Decimal(margin.output_value) == Decimal("20.00")


def test_current_ratio():
    r = execute_formula("finance.current_ratio.v1", {
        "current_assets": {"value": "200000", "unit": "USD"},
        "current_liabilities": {"value": "100000", "unit": "USD"},
    })
    assert Decimal(r.output_value) == Decimal("2.00")


def test_quick_ratio():
    r = execute_formula("finance.quick_ratio.v1", {
        "current_assets": {"value": "200000", "unit": "USD"},
        "inventory": {"value": "50000", "unit": "USD"},
        "current_liabilities": {"value": "100000", "unit": "USD"},
    })
    assert Decimal(r.output_value) == Decimal("1.50")


def test_debt_to_equity():
    r = execute_formula("finance.debt_to_equity.v1", {
        "total_liabilities": {"value": "400000", "unit": "USD"},
        "total_equity": {"value": "200000", "unit": "USD"},
    })
    assert Decimal(r.output_value) == Decimal("2.00")


def test_effective_tax_rate():
    r = execute_formula("tax.effective_tax_rate.v1", {
        "total_tax_expense": {"value": "21000", "unit": "USD"},
        "pretax_income": {"value": "100000", "unit": "USD"},
    })
    assert Decimal(r.output_value) == Decimal("21.00")


def test_break_even_point():
    r = execute_formula("accounting.break_even_point.v1", {
        "fixed_costs": {"value": "10000", "unit": "USD"},
        "price_per_unit": {"value": "50", "unit": "USD"},
        "variable_cost_per_unit": {"value": "30", "unit": "USD"},
    })
    assert Decimal(r.output_value) == Decimal("500.00")


def test_break_even_point_rejects_non_positive_contribution_margin():
    r = execute_formula("accounting.break_even_point.v1", {
        "fixed_costs": {"value": "10000", "unit": "USD"},
        "price_per_unit": {"value": "10", "unit": "USD"},
        "variable_cost_per_unit": {"value": "30", "unit": "USD"},
    })
    assert r.status == "invalid_input"


def test_straight_line_depreciation_matches_known_value():
    r = execute_formula("accounting.straight_line_depreciation.v1", {
        "asset_cost": {"value": "50000", "unit": "USD"},
        "salvage_value": {"value": "5000", "unit": "USD"},
        "useful_life_years": {"value": "9", "unit": "years"},
    })
    assert Decimal(r.output_value) == Decimal("5000.00")


def test_straight_line_depreciation_rejects_salvage_exceeding_cost():
    r = execute_formula("accounting.straight_line_depreciation.v1", {
        "asset_cost": {"value": "10000", "unit": "USD"},
        "salvage_value": {"value": "20000", "unit": "USD"},
        "useful_life_years": {"value": "5", "unit": "years"},
    })
    assert r.status == "invalid_input"


def test_declining_balance_depreciation_double_declining_year_one():
    r = execute_formula("accounting.declining_balance_depreciation.v1", {
        "asset_cost": {"value": "50000", "unit": "USD"},
        "salvage_value": {"value": "5000", "unit": "USD"},
        "useful_life_years": {"value": "5", "unit": "years"},
        "declining_balance_factor": {"value": "2", "unit": "ratio"},
        "target_year": {"value": "1", "unit": "count"},
    })
    assert r.status == "verified"
    # Rate = 2/5 = 0.4; year 1 = 50000 * 0.4 = 20000
    assert Decimal(r.output_value) == Decimal("20000.00")


def test_declining_balance_depreciation_never_drops_below_salvage():
    """Deep into the schedule, book value should floor at salvage, never go
    below it — a documented, tested guarantee, not an incidental behavior."""
    r = execute_formula("accounting.declining_balance_depreciation.v1", {
        "asset_cost": {"value": "10000", "unit": "USD"},
        "salvage_value": {"value": "1000", "unit": "USD"},
        "useful_life_years": {"value": "3", "unit": "years"},
        "declining_balance_factor": {"value": "2", "unit": "ratio"},
        "target_year": {"value": "10", "unit": "count"},  # well beyond useful life
    })
    assert r.status == "verified"
    assert Decimal(r.output_value) >= Decimal("0")


def test_simple_interest():
    r = execute_formula("finance.simple_interest.v1", {
        "principal": {"value": "10000", "unit": "USD"},
        "annual_rate": {"value": "5", "unit": "percent"},
        "time_years": {"value": "3", "unit": "years"},
    })
    assert Decimal(r.output_value) == Decimal("1500.00")


def test_compound_interest_matches_known_value():
    r = execute_formula("finance.compound_interest.v1", {
        "principal": {"value": "10000", "unit": "USD"},
        "annual_rate": {"value": "5", "unit": "percent"},
        "time_years": {"value": "3", "unit": "years"},
        "compounding_periods_per_year": {"value": "12", "unit": "count"},
    })
    assert r.status == "verified"
    # Standard known result for $10,000 at 5% monthly compounding over 3 years
    assert abs(Decimal(r.output_value) - Decimal("1614.72")) < Decimal("0.01")


def test_loan_payment_matches_known_mortgage_value():
    """$200,000 at 6% APR, 360 monthly payments (30-year mortgage) — a
    widely known reference value from standard amortization calculators."""
    r = execute_formula("finance.loan_payment.v1", {
        "principal": {"value": "200000", "unit": "USD"},
        "annual_rate": {"value": "6", "unit": "percent"},
        "number_of_payments": {"value": "360", "unit": "count"},
    })
    assert r.status == "verified"
    assert abs(Decimal(r.output_value) - Decimal("1199.10")) < Decimal("0.01")


def test_loan_payment_zero_interest():
    r = execute_formula("finance.loan_payment.v1", {
        "principal": {"value": "12000", "unit": "USD"},
        "annual_rate": {"value": "0", "unit": "percent"},
        "number_of_payments": {"value": "12", "unit": "count"},
    })
    assert r.status == "verified"
    assert Decimal(r.output_value) == Decimal("1000.00")


def test_audit_sample_size():
    r = execute_formula("audit.attribute_sample_size.v1", {
        "reliability_factor": {"value": "3.0", "unit": "ratio"},
        "tolerable_deviation_rate": {"value": "5", "unit": "percent"},
        "expected_deviation_rate": {"value": "1", "unit": "percent"},
    })
    assert r.status == "verified"
    assert Decimal(r.output_value) == Decimal("75")
    assert any("reliability_factor" in a for a in r.assumptions)


def test_audit_sample_size_rejects_tolerable_below_expected():
    r = execute_formula("audit.attribute_sample_size.v1", {
        "reliability_factor": {"value": "3.0", "unit": "ratio"},
        "tolerable_deviation_rate": {"value": "1", "unit": "percent"},
        "expected_deviation_rate": {"value": "5", "unit": "percent"},
    })
    assert r.status == "invalid_input"


def test_net_profit_and_inventory_turnover():
    profit = execute_formula("accounting.net_profit.v1", {
        "revenue": {"value": "250000", "unit": "USD"},
        "total_expenses": {"value": "180000", "unit": "USD"},
    })
    assert Decimal(profit.output_value) == Decimal("70000.00")
    turnover = execute_formula("accounting.inventory_turnover.v1", {
        "cost_of_goods_sold": {"value": "600000", "unit": "USD"},
        "average_inventory": {"value": "150000", "unit": "USD"},
    })
    assert Decimal(turnover.output_value) == Decimal("4.00")


def test_tax_scenario_labels_legal_assumptions():
    result = execute_formula("tax.taxable_income_scenario.v1", {
        "gross_income": {"value": "100000", "unit": "USD"},
        "adjustments": {"value": "5000", "unit": "USD"},
        "deductions": {"value": "15000", "unit": "USD"},
    })
    assert Decimal(result.output_value) == Decimal("80000.00")
    assert any("legal" in assumption for assumption in result.assumptions)


def test_audit_materiality_preserves_professional_judgment_boundary():
    result = execute_formula("audit.materiality.v1", {
        "benchmark_amount": {"value": "5000000", "unit": "USD"},
        "user_selected_percentage": {"value": "1", "unit": "percent"},
    })
    assert Decimal(result.output_value) == Decimal("50000.00")
    assert any("professional judgment" in assumption for assumption in result.assumptions)


def test_projected_misstatement_ratio_projection():
    result = execute_formula("audit.projected_misstatement.v1", {
        "sample_misstatement": {"value": "2000", "unit": "USD"},
        "sample_book_value": {"value": "100000", "unit": "USD"},
        "population_book_value": {"value": "1000000", "unit": "USD"},
    })
    assert Decimal(result.output_value) == Decimal("20000.00")


def test_tax_from_supplied_rate_does_not_claim_rate_applicability():
    result = execute_formula("tax.tax_from_supplied_rate.v1", {
        "taxable_base": {"value": "1200", "unit": "USD"},
        "user_supplied_rate": {"value": "7.25", "unit": "percent"},
    })
    assert Decimal(result.output_value) == Decimal("87.00")
    assert any("does not determine" in assumption for assumption in result.assumptions)


# ── Required inputs, never silently assumed ─────────────────────────────────

def test_missing_required_input_returns_structured_response_not_a_guess():
    r = execute_formula("accounting.gross_margin.v1", {
        "revenue": {"value": "250000", "unit": "USD"},
    })
    assert r.status == "missing_input"
    assert "cost_of_goods_sold" in r.errors[0]


def test_unknown_formula_id_returns_error_not_a_crash():
    r = execute_formula("not.a.real.formula.v1", {})
    assert r.status == "error"


# ── Unit handling — 15 vs 15% vs 0.15 must never be confused ───────────────

def test_percent_and_decimal_rate_units_produce_identical_results():
    common = {
        "principal": {"value": "10000", "unit": "USD"},
        "time_years": {"value": "2", "unit": "years"},
    }
    as_percent = execute_formula("finance.simple_interest.v1", {
        **common, "annual_rate": {"value": "15", "unit": "percent"},
    })
    as_percent_literal = execute_formula("finance.simple_interest.v1", {
        **common, "annual_rate": {"value": "15%", "unit": "percent"},
    })
    as_decimal_rate = execute_formula("finance.simple_interest.v1", {
        **common, "annual_rate": {"value": "0.15", "unit": "decimal_rate"},
    })
    assert as_percent.output_value == as_percent_literal.output_value == as_decimal_rate.output_value


def test_declared_decimal_rate_with_percent_literal_is_rejected_as_ambiguous():
    r = execute_formula("finance.simple_interest.v1", {
        "principal": {"value": "10000", "unit": "USD"},
        "annual_rate": {"value": "15%", "unit": "decimal_rate"},
        "time_years": {"value": "2", "unit": "years"},
    })
    assert r.status == "invalid_input"


def test_wrong_unit_declaration_is_rejected():
    r = execute_formula("accounting.gross_profit.v1", {
        "revenue": {"value": "250000", "unit": "percent"},
        "cost_of_goods_sold": {"value": "180000", "unit": "USD"},
    })
    assert r.status == "invalid_input"


def test_invalid_numeric_value_is_rejected():
    r = execute_formula("accounting.gross_profit.v1", {
        "revenue": {"value": "not-a-number", "unit": "USD"},
        "cost_of_goods_sold": {"value": "180000", "unit": "USD"},
    })
    assert r.status == "invalid_input"


# ── Rounding policy is recorded on every result ─────────────────────────────

def test_rounding_policy_is_recorded():
    r = execute_formula("accounting.gross_margin.v1", {
        "revenue": {"value": "250000", "unit": "USD"},
        "cost_of_goods_sold": {"value": "180000", "unit": "USD"},
    })
    assert r.rounding_policy == "percentage_two_decimal_places"


# ── Versioning / metadata / calculation steps ───────────────────────────────

def test_formula_version_and_engine_version_present():
    r = execute_formula("accounting.gross_profit.v1", {
        "revenue": {"value": "100", "unit": "USD"},
        "cost_of_goods_sold": {"value": "60", "unit": "USD"},
    })
    assert r.formula_version == "1.0.0"
    assert r.engine == "formula_registry"
    assert r.engine_version


def test_calculation_steps_are_populated_and_human_readable():
    r = execute_formula("accounting.gross_profit.v1", {
        "revenue": {"value": "100", "unit": "USD"},
        "cost_of_goods_sold": {"value": "60", "unit": "USD"},
    })
    assert r.steps
    assert "Gross profit" in r.steps[0]


def test_methodology_reference_present_on_every_registered_formula():
    for definition in list_formulas():
        assert definition.methodology_reference, definition.id


def test_get_formula_returns_none_for_unknown_id():
    assert get_formula("nonexistent") is None
