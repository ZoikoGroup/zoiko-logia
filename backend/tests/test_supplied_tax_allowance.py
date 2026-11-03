"""Supplied-rate tax (calculations.engine, "supplied_tax"): a stated
allowance comes off before the rate, and a direct tax is not added to the
amount. "Calculate income tax on £30,000 at 20% after a £12,570 allowance"
was £6,000 with a "total including tax" of £36,000 (3 Nov 2026)."""
from decimal import Decimal

import pytest

from app.orchestration.calculations.engine import calculate_from_query


def _outputs(query):
    result = calculate_from_query(query)
    return result, {o.name: o.value for o in result.outputs}


@pytest.mark.parametrize("query", [
    "Calculate income tax on £30,000 at 20% after a £12,570 allowance.",
    "Calculate income tax on £30,000 at 20% with a personal allowance of £12,570.",
    "Calculate income tax on £30,000 at 20% less £12,570 personal allowance.",
])
def test_the_allowance_comes_off_first(query):
    result, values = _outputs(query)
    assert result.status == "success"
    assert values["taxable_amount"] == Decimal("17430") and values["tax"] == Decimal("3486")
    assert "total_including_tax" not in values


def test_an_allowance_above_the_amount_leaves_nothing_taxable():
    _, values = _outputs("Calculate income tax on £10,000 at 20% after a £12,570 allowance.")
    assert values["taxable_amount"] == 0 and values["tax"] == 0


@pytest.mark.parametrize("query", [
    "Calculate income tax on £30,000 at 20% after the personal allowance.",       # no figure
    "Calculate tax on £30,000 at 20% after a £12,570 allowance and a £1,000 deduction.",  # two
    "Calculate income tax on £30,000 at 20% after a $12,570 allowance.",           # other currency
])
def test_an_allowance_it_cannot_apply_is_left_to_the_model(query):
    assert not calculate_from_query(query).matched


def test_a_direct_tax_is_not_added_to_the_amount():
    _, values = _outputs("Calculate corporation tax on £100,000 at 25%.")
    assert values["tax"] == Decimal("25000") and "total_including_tax" not in values


def test_a_sales_tax_still_shows_the_total():
    _, values = _outputs("Calculate tax on £500 at 10%")
    assert values["tax"] == Decimal("50") and values["total_including_tax"] == Decimal("550")
