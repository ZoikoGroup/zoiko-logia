"""Stage 2: written numbers and revenue phrases (27 Oct 2026).

"…over eight years" was not read as the useful life, because only digits
were. Separately, when revenue was worded "total sales came to £800,000",
"£800,000 in revenue" or "revenues were…", the "sales" of "cost of sales
£500,000" was read as revenue, so gross profit £0.00 was shown as a
verified calculation. Positive cases must now compute. Negative cases must
still ask for the missing figure and never guess it. No model, database or
network.
"""
from decimal import Decimal

import pytest

from app.orchestration.calculations.engine import calculate_from_query

_SL = "Calculate straight-line depreciation: asset cost £24,000, residual value £2,000, "


def _inputs(result):
    return {item.name: item.value for item in result.inputs}


@pytest.mark.parametrize("life_text, years", [
    ("over eight years.", 8),
    ("useful life eight years.", 8),
    ("useful life of twelve years.", 12),
    ("lasts ten years.", 10),
    ("life of 8 years.", 8),
    ("over twenty-five years.", 25),
    ("over 5 years.", 5),
])
def test_written_useful_life_is_read(life_text, years):
    result = calculate_from_query(_SL + life_text)
    assert result.status == "success"
    assert _inputs(result)["useful_life"] == Decimal(years)
    assert result.outputs[0].value == Decimal(22_000) / years


def test_written_useful_life_on_costing_wording():
    result = calculate_from_query(
        "Calculate straight-line depreciation on equipment costing £40,000 with residual value £4,000 over eight years.")
    assert result.status == "success"
    assert result.outputs[0].display_value == "£4,500.00"


@pytest.mark.parametrize("life_text", ["", "over several years.", "over many years."])
def test_missing_or_vague_life_still_asks(life_text):
    result = calculate_from_query(_SL + life_text)
    assert result.status == "clarification_required"
    assert "useful life" in result.message


@pytest.mark.parametrize("query", [
    "Calculate gross profit: revenue £800,000, cost of sales £500,000.",
    "Calculate gross profit: total sales came to £800,000 and cost of sales was £500,000.",
    "Calculate the gross profit: we generated £800,000 in revenue and cost of sales was £500,000.",
    "Calculate gross margin: the company earned £800,000 of revenue with cost of sales of £500,000.",
    "Calculate gross profit: revenues were £800,000; cost of sales £500,000.",
    "Calculate gross profit: revenue for the year £800,000, cost of sales £500,000.",
    "Calculate gross profit: sales totalled £800,000 and cost of goods sold £500,000.",
    "Calculate gross profit: cost of revenue was £500,000 and revenue £800,000.",
    "Calculate gross profit: net sales £800,000, cost of goods sold £500,000.",
])
def test_revenue_phrases_are_read(query):
    result = calculate_from_query(query)
    assert result.status == "success"
    assert _inputs(result)["revenue"] == Decimal(800_000)
    assert _inputs(result)["cost_of_sales"] == Decimal(500_000)
    assert next(o for o in result.outputs if o.name == "gross_profit").value == Decimal(300_000)


@pytest.mark.parametrize("query", [
    "Calculate gross profit: cost of sales £500,000.",
    "Calculate the gross margin: we sold goods worth £800,000 and cost of sales was £500,000.",
    "Calculate gross profit: cost of goods sales £500,000.",
])
def test_cost_of_sales_is_never_taken_as_revenue(query):
    result = calculate_from_query(query)
    assert result.status != "success"
    assert _inputs(result).get("revenue") is None
