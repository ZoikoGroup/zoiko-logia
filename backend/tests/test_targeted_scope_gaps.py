"""Reproduced numeric provenance gaps; supplied inputs, no legal assumptions."""
import pytest
from app.orchestration.figure_reconciliation import unreconciled_figures

FACTS="A 5-year equipment lease. The asset has a useful life of 6 years. The borrowing rate is 6%."

@pytest.mark.parametrize("phrase",[
    "The lease term equals {percent} of the economic life.",
    "The term of the lease is {percent} of the economic life.",
    "The lease term is approximately {percent} of the economic life.",
    "The lease term represents {percent} of its useful life.",
])
@pytest.mark.parametrize("percent,unsupported",[("6%",True),("83.33%",False)])
def test_equivalent_lease_share_phrases_use_the_same_supplied_durations(phrase,percent,unsupported):
    actual=unreconciled_figures(phrase.format(percent=percent),FACTS)
    assert bool(actual) is unsupported

@pytest.mark.parametrize("code",["USD","GBP","EUR","INR"])
def test_suffix_currency_does_not_allow_adding_a_person_count(code):
    assert unreconciled_figures(f"The total is {code} 50,001.00.",f"Principal 50,000 {code} and 1 employee.")

@pytest.mark.parametrize("code",["USD","GBP","EUR","INR"])
def test_suffix_currency_keeps_real_fees_and_excludes_additional_counts(code):
    facts=f"Principal 50,000 {code}, fee 1 {code}, and 1 employee."
    assert unreconciled_figures(f"The total is {code} 50,001.00.",facts)==[]
    assert unreconciled_figures(f"The total is {code} 50,002.00.",facts)

@pytest.mark.parametrize("code",["USD","GBP"])
def test_suffix_currency_keeps_quantity_times_unit_price(code):
    assert unreconciled_figures(f"Sales total {code} 108,000.",f"Unit price 18 {code}, quantity 6,000 units.")==[]

def test_suffix_and_prefix_do_not_count_the_same_explicit_amount_twice():
    assert unreconciled_figures("The total is $100,000.","Principal USD 50,000 USD.")
