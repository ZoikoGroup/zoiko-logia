"""VAT is calculated only when the country, rate(s) and VAT treatment are
known; otherwise Kriton asks for exactly what is missing ("How much VAT do I
owe?" was answered with "(£120,000 − £48,000) × r")."""
from decimal import Decimal

import pytest

from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.input_requirements import missing_vat_inputs


def out(result, name):
    return next(o.value for o in result.outputs if o.name == name)


@pytest.mark.parametrize("query, asks, does_not_ask", [
    ("A business has sales of £120,000 and purchases of £48,000. How much VAT do I owe?",
     ["VAT rate", "include VAT or exclude VAT"], ["country"]),                 # £ names the UK
    ("Calculate VAT on £72,000", ["VAT rate", "include VAT or exclude VAT"], ["country"]),
    ("Calculate VAT on $5,000 at 20%", ["country", "include VAT or exclude VAT"], ["VAT rate"]),
    ("Calculate VAT on £72,000 at 20%", ["include VAT or exclude VAT"], ["VAT rate", "country"]),
    ("UK sales £120,000 and purchases £48,000 at 20%, excluding VAT. How much VAT do I owe?",
     ["all the sales and purchases are at that rate"], ["VAT rate or rates", "include VAT or exclude VAT"]),
])
def test_only_the_missing_inputs_are_asked_for(query, asks, does_not_ask):
    message = missing_vat_inputs(query)
    assert message and "won't assume" in message
    for item in asks:
        assert item in message
    for item in does_not_ask:
        assert item not in message


@pytest.mark.parametrize("query", [
    "What is the UK VAT registration threshold?",
    "What is the VAT rate in Germany?",
    "Calculate VAT at -18% on £100.",          # the calculator rejects the rate first
    "UK sales £120,000 at 20% and purchases £48,000 at 5%, excluding VAT. How much VAT do I owe?",
])
def test_complete_or_non_amount_questions_are_not_clarified(query):
    assert missing_vat_inputs(query) is None


def test_exclusive_liability():
    r = calculate_from_query("How much VAT do I owe? UK, sales £120,000 and purchases £48,000, all standard-rated "
                             "at 20%, figures exclude VAT.")
    assert (out(r, "output_vat_on_sales"), out(r, "input_vat_on_purchases"), out(r, "vat_payable")) == \
        (Decimal("24000"), Decimal("9600"), Decimal("14400"))
    assert any("valid VAT invoices" in note for note in r.notes)


def test_inclusive_liability():
    r = calculate_from_query("Sales £120,000 including VAT and purchases £48,000 including VAT, all at 20%. "
                             "How much VAT do I owe?")
    assert out(r, "vat_payable") == Decimal("12000")


def test_mixed_rates_per_item():
    r = calculate_from_query("Sales £120,000 at 20% and purchases £48,000 at 5%, excluding VAT. How much VAT do I owe?")
    assert out(r, "input_vat_on_purchases") == Decimal("2400") and out(r, "vat_payable") == Decimal("21600")


def test_single_amount_inclusive_and_exclusive():
    inside = calculate_from_query("What is the VAT in £72,000 including VAT at 20%?")
    assert (out(inside, "vat_amount"), out(inside, "amount_excluding_vat")) == (Decimal("12000"), Decimal("60000"))
    on_top = calculate_from_query("Calculate VAT on £72,000 at 20%, excluding VAT")
    assert (out(on_top, "vat_amount"), out(on_top, "total_including_vat")) == (Decimal("14400"), Decimal("86400"))


def test_unstated_treatment_or_several_unattached_rates_are_not_calculated():
    assert calculate_from_query("How much VAT do I owe on sales of £120,000 at 20%?").status != "success" or \
        missing_vat_inputs("How much VAT do I owe on sales of £120,000 at 20%?")
    assert calculate_from_query("VAT at 20% and 5% on £1,000 excluding VAT").formula_ids[:1] != ["vat_on_net"]
