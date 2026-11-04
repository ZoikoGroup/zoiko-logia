"""Supplied-figure arithmetic controls, not accounting/legal ground truth."""
import pytest
from app.orchestration.figure_reconciliation import unreconciled_figures


@pytest.mark.parametrize("term,life,percent", [("5-year","6 years","83%"),("5-year","6 years","83.33%"),("60-month","6 years","83.33%"),("5-year","72 months","83.33%")])
def test_named_lease_duration_ratio_keeps_correct_rounding(term,life,percent):
    facts=f"A {term} equipment lease. The asset has a useful life of {life}. The borrowing rate is 6%."
    assert unreconciled_figures(f"The lease term is {percent} of the economic life.",facts)==[]


@pytest.mark.parametrize("percent", ["6%","80%","83.30%","84%"])
def test_borrowing_rate_or_nearby_number_cannot_replace_term_ratio(percent):
    facts="A 5-year equipment lease. The asset has a useful life of 6 years. The borrowing rate is 6%."
    assert unreconciled_figures(f"The lease term is {percent} of the economic life.",facts)==[percent]


def test_stated_borrowing_rate_is_not_rejected_as_a_lease_term_claim():
    facts="A 5-year equipment lease. The asset has a useful life of 6 years. The borrowing rate is 6%."
    assert unreconciled_figures("The borrowing rate is 6%.",facts)==[]


@pytest.mark.parametrize("small",[1,5,6])
def test_real_money_fee_is_kept_even_when_small_compared_with_principal(small):
    facts=f"Principal $50,000, plus a fee of ${small}."
    assert unreconciled_figures(f"The total is ${50000+small:,.2f}.",facts)==[]


@pytest.mark.parametrize("count",[1,5,6])
def test_an_employee_count_is_not_added_to_principal(count):
    facts=f"Principal $50,000 and {count} employees."
    assert unreconciled_figures(f"The total is ${50000+count:,.2f}.",facts)!=[]


def test_counts_can_still_multiply_a_unit_price():
    assert unreconciled_figures("Sales total £108,000.","Unit price £18 and quantity 6,000 units.")==[]


def test_a_supplied_rate_can_still_multiply_a_money_amount():
    assert unreconciled_figures("Interest is $3,000.00.","Principal $50,000 at 6% interest.")==[]


def test_explicit_supported_equations_keep_financial_arithmetic():
    assert unreconciled_figures("The amount is $50,000 + $1 = $50,001.00.","Principal $50,000. Fee $1.")==[]


def test_a_reference_threshold_cannot_rescue_an_unrelated_duration_claim():
    facts="A 5-year equipment lease. The asset has a useful life of 6 years. The borrowing rate is 6%."
    answer="A finance lease criterion is 75% while the lease term is 6% of the economic life."
    assert "6%" in unreconciled_figures(answer,facts)


def test_an_explicit_reference_criterion_is_not_reinterpreted_as_the_actual_term():
    facts="A 5-year equipment lease. The asset has a useful life of 6 years."
    # Preserve the pre-existing reference-value policy; this is not approval
    # that the threshold applies to any entity, framework or period.
    answer="A finance lease criterion is that the lease term is 75% of the economic life."
    assert unreconciled_figures(answer,facts)==[]
