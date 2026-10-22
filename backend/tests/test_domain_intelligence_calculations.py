from decimal import Decimal
import pytest
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.calculations.visuals import calculation_visual
from tests.test_domain_intelligence_http import BANK, INVENTORY, DEPRECIATION


def vals(result):
    return {o.name: o.value for o in result.outputs}


def test_bank_residual_is_not_forced_to_zero():
    r = calculate_from_query(BANK.replace('£12,600', '£12,500'))
    assert vals(r)['unreconciled_difference'] == 100
    assert vals(r)['adjusted_cash_book_balance'] == 12700


@pytest.mark.parametrize('extra', [' Bank error £200.', ' Direct debit £400.', ' Unexplained adjustment £500.'])
def test_bank_additional_items_are_not_silently_ignored(extra):
    assert calculate_from_query(BANK + extra).status != 'success'


def test_bank_mixed_currency_is_not_verified():
    assert calculate_from_query(BANK.replace('£700', '$700')).status != 'success'


@pytest.mark.parametrize('sold', [0, 50, 180, 300])
def test_inventory_conserves_cost_and_units(sold):
    v = vals(calculate_from_query(INVENTORY.replace('sold 180', f'sold {sold}')))
    for method in ['fifo', 'weighted_average']:
        assert v[f'{method}_cost_of_goods_sold'] + v[f'{method}_closing_inventory'] == 3600
    assert v['weighted_average_cost_of_goods_sold'] == Decimal(sold)*12


@pytest.mark.parametrize('change', [lambda q: q.replace('sold 180','sold 301'),
    lambda q: q.replace('£13','$13'), lambda q: q+' Purchase returns £50.',
    lambda q: q.replace('All purchases occurred before the only sale.','Sales interleaved with purchases.')])
def test_inventory_does_not_verify_invalid_or_unsupported_shapes(change):
    assert calculate_from_query(change(INVENTORY)).status != 'success'


@pytest.mark.parametrize('q', [
    'Calculate straight-line depreciation. Asset cost £24,000, residual value £25,000, useful life 6 years.',
    'Calculate straight-line depreciation. Asset cost £24,000, residual value $0, useful life 6 years.',
    'Calculate straight-line depreciation. Asset cost £24,000, residual value £0, useful life 0 years.',
])
def test_depreciation_invalid_inputs_do_not_produce_success(q):
    assert calculate_from_query(q).status != 'success'


def test_depreciation_missing_residual_is_not_assumed_zero():
    r = calculate_from_query(DEPRECIATION.replace('no resale value', ''))
    assert r.status == 'clarification_required'
    assert 'residual value' in r.message


def test_adaptive_profit_comparison_uses_validated_values():
    from tests.test_agent_request_size import QUESTION
    r = calculate_from_query(QUESTION)
    spec, notes = calculation_visual(r, QUESTION, 'profit-comparison')
    assert spec.type == 'GROUPED_BAR'
    assert spec.variant == 'GROUPED_BAR_CHART'
    points = {s.name: {p.x: p.y for p in s.data} for s in spec.series}
    assert points['Current'] == {'Gross Profit': 505000, 'Operating Profit': 191000}
    assert points['Previous'] == {'Gross Profit': 440000, 'Operating Profit': 155000}
    assert not notes


def test_simple_depreciation_does_not_get_an_unhelpful_chart():
    r = calculate_from_query(DEPRECIATION)
    assert calculation_visual(r, DEPRECIATION, 'no-chart') == (None, [])
    spec, notes = calculation_visual(r, DEPRECIATION+' Show a graph.', 'different-time-bases')
    assert spec is None and notes


def test_unverified_outputs_cannot_be_charted():
    r = calculate_from_query(BANK)
    r.verification_status = 'not_run'
    assert calculation_visual(r, 'Show a bar chart.', 'unverified') == (None, [])


def test_profit_waterfall_uses_signed_components_and_conserves_final_profit():
    from tests.test_paid_manual_transcript import WHOLESALE
    r = calculate_from_query(WHOLESALE)
    spec, notes = calculation_visual(r, 'Show a waterfall chart.', 'bridge')
    assert spec.variant == 'WATERFALL_CHART'
    assert [p.y for p in spec.data] == [936000, -560000, -222000, -9000]
    assert sum(p.y for p in spec.data) == vals(r)['profit_before_tax']
    assert not notes


def test_inventory_comparison_charts_methods_without_mixing_unit_cost_and_totals():
    r = calculate_from_query(INVENTORY)
    spec, _ = calculation_visual(r, 'Compare the two methods.', 'methods')
    assert spec.type == 'GROUPED_BAR'
    assert [p.y for p in spec.series[0].data] == [2040, 1560]
    assert [p.y for p in spec.series[1].data] == [2160, 1440]


@pytest.mark.parametrize('q', [BANK.replace('All amounts GBP', 'All amounts USD'),
    INVENTORY.replace('Use periodic FIFO', 'All amounts USD. Use periodic FIFO'),
    DEPRECIATION.replace('no resale value', 'residual value $0')])
def test_declared_currency_cannot_contradict_the_figures(q):
    assert calculate_from_query(q).status != 'success'


def test_duplicate_bank_balance_requires_version_selection():
    r = calculate_from_query(BANK + ' Bank statement balance £13,000.')
    assert r.status == 'clarification_required'
    assert r.error_code == 'AMBIGUOUS_INPUTS'
