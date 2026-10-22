"""Independent arithmetic and boundary checks for the existing VAT/GST path."""
from decimal import Decimal
from fractions import Fraction

from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.input_requirements import missing_vat_inputs
from tests.test_root_cause_http import GST


def test_return_adjusted_gst_agrees_with_independent_fraction_arithmetic():
    assert missing_vat_inputs(GST) is None
    result = calculate_from_query(GST)
    values = {item.name: item.value for item in result.outputs}
    output = Fraction(2400000-120000) * Fraction(18, 100)
    credit = Fraction(1100000-80000) * Fraction(18, 100)
    assert values['output_vat_on_sales'] == Decimal(output.numerator) / output.denominator
    assert values['input_vat_on_purchases'] == Decimal(credit.numerator) / credit.denominator
    assert values['vat_payable'] == Decimal((output-credit).numerator) / (output-credit).denominator
    assert result.verification_status == 'passed' and result.formula_ids == ['vat_liability']
    assert sum('matches the calculated' in note for note in result.notes) == 2
    inputs = {item.name: item for item in result.inputs}
    assert inputs['sales_returns'].value == 120000 and inputs['purchase_returns'].value == 80000
    assert inputs['sales_rate'].kind == 'percentage' and inputs['sales_rate'].value == 18


def test_incorrect_ledger_amount_is_not_declared_a_match():
    result = calculate_from_query(GST.replace('ledger says ₹410,400', 'ledger says ₹410,401'))
    assert any('does not match' in note for note in result.notes)
    assert any('Input tax credit ledger' in note and 'matches' in note for note in result.notes)


def test_returns_cannot_exceed_corresponding_gross_amount():
    result = calculate_from_query(GST.replace('sales returns ₹120,000', 'sales returns ₹2,500,000'))
    assert result.status == 'clarification_required' and result.error_code == 'INVALID_RETURNS'


def test_ledger_currency_mismatch_is_not_silently_compared():
    result = calculate_from_query(GST.replace('ledger says ₹410,400', 'ledger says £410,400'))
    assert result.status == 'clarification_required' and result.error_code == 'CURRENCY_MISMATCH'
