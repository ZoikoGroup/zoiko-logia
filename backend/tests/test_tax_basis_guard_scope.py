"""Tax-basis guard regressions; pure functions, no database or provider access."""
import pytest
from app.orchestration.input_requirements import missing_vat_inputs


@pytest.mark.parametrize("incidental", [
    "including delivery", "excluding postage", "includes shipping",
    "inclusive service", "exclusive offer", "net of discounts", "gross of commission",
])
def test_non_tax_qualifiers_do_not_establish_tax_basis(incidental):
    query = f"Calculate VAT on £5,000 at 20%, {incidental}."
    message = missing_vat_inputs(query)
    assert message is not None
    assert "whether the amounts include VAT or exclude VAT" in message
    assert "which country" not in message
    assert "the VAT rate or rates" not in message


@pytest.mark.parametrize("basis", [
    "including VAT", "excluding VAT", "includes VAT", "excludes VAT",
    "inclusive of VAT", "exclusive of VAT", "net of VAT", "gross of VAT",
    "VAT-inclusive", "VAT-exclusive", "ex-VAT", "inc-VAT", "plus VAT", "before VAT", "after VAT",
])
def test_explicit_vat_basis_does_not_trigger_unnecessary_clarification(basis):
    assert missing_vat_inputs(f"Calculate VAT on £5,000 at 20%, {basis}.") is None


@pytest.mark.parametrize("basis", ["including GST", "excluding GST", "inclusive of GST", "GST-inclusive"])
def test_explicit_gst_basis_is_recognized(basis):
    assert missing_vat_inputs(f"Calculate GST on ₹5,000 at 18%, {basis}.") is None


@pytest.mark.parametrize("query,missing", [
    ("Calculate VAT on $5,000 at 20%, including VAT.", "which country"),
    ("Calculate VAT on £5,000, including VAT.", "the VAT rate or rates"),
    ("UK sales £5,000 and purchases £2,000 at 20%, including VAT. How much VAT do I owe?",
     "whether all the sales and purchases are at that rate"),
])
def test_explicit_tax_basis_does_not_bypass_other_required_inputs(query, missing):
    assert missing in missing_vat_inputs(query)


def test_user_history_explicit_tax_basis_is_preserved():
    from types import SimpleNamespace
    history = [SimpleNamespace(role="user", content="My UK amounts are excluding VAT at 20%.")]
    assert missing_vat_inputs("Calculate VAT on £5,000, including delivery.", history) is None


@pytest.mark.parametrize("delivery", [
    "delivery charges included",
    "delivery charges excluded",
    "including delivery charges",
    "excluding delivery charges",
])
@pytest.mark.parametrize("basis", [None, "including VAT", "excluding VAT"])
def test_delivery_wording_does_not_override_explicit_or_missing_tax_basis(delivery, basis):
    qualifiers = delivery if basis is None else f"{delivery}, {basis}"
    query = f"Calculate VAT on £5,000 at 20%, {qualifiers}."
    message = missing_vat_inputs(query)
    if basis is None:
        assert message is not None
        assert "whether the amounts include VAT or exclude VAT" in message
        assert "which country" not in message
        assert "the VAT rate or rates" not in message
    else:
        assert message is None
