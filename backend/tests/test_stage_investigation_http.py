"""Existing exact inputs; missing latest payloads are not reverse-engineered."""
from tests.offline_http_support import offline_http  # noqa: F401
from tests.test_root_cause_http import GST, output
from tests.test_domain_intelligence_http import INVENTORY
from tests.test_paid_manual_transcript import WHOLESALE


async def test_existing_statement_direct_inventory_replacement(offline_http):
    await offline_http.ask(WHOLESALE, conversation='direct-change', case_id='B-existing-baseline')
    result = await offline_http.ask('Change closing inventory to £85,000.', conversation='direct-change', case_id='B-direct-change')
    assert output(result)['cost_of_goods_sold'] == '570000'
    assert output(result)['operating_profit'] == '144000'
    assert output(result)['profit_before_tax'] == '135000'
    assert not result.trace['model_requests']


async def test_exact_existing_gst_request_is_independent_of_retrieval(offline_http, monkeypatch):
    from app.orchestration import service
    from unittest.mock import AsyncMock
    retrieval = AsyncMock(side_effect=AssertionError('No external evidence is needed for supplied arithmetic'))
    monkeypatch.setattr(service, 'build_source_bundle', retrieval)
    result = await offline_http.ask(GST, conversation='GST-supplied', case_id='C-exact-existing-GST')
    v = output(result)
    assert v['net_sales'] == '2280000' and v['net_purchases'] == '1020000'
    assert v['output_vat_on_sales'] == '410400' and v['input_vat_on_purchases'] == '183600'
    assert v['vat_payable'] == '226800'
    assert v['output_ledger_difference'] == '0' and v['input_ledger_difference'] == '0'
    assert result.body['answer']['completeness'] == 'complete'
    assert not result.trace['model_requests']
    retrieval.assert_not_awaited()
    assert 'valid VAT invoices' not in result.body['answer']['text']


async def test_existing_inventory_returns_closing_units_and_cost_reconciliations(offline_http):
    result = await offline_http.ask(INVENTORY, conversation='inventory-completion', case_id='E-existing-inventory')
    v = output(result)
    assert v['fifo_closing_units'] == '120'
    assert v['weighted_average_closing_units'] == '120'
    assert v['total_inventory_cost'] == '3600'
    assert v['fifo_reconciliation_difference'] == '0'
    assert v['weighted_average_reconciliation_difference'] == '0'
    assert result.body['answer']['completeness'] == 'complete'


async def test_gst_legal_eligibility_still_requires_evidence(offline_http, monkeypatch):
    from app.orchestration import service
    from unittest.mock import AsyncMock
    retrieval = AsyncMock(side_effect=RuntimeError('synthetic evidence unavailable'))
    monkeypatch.setattr(service, 'build_source_bundle', retrieval)
    result = await offline_http.ask(GST + ' Explain whether these purchases legally qualify for input tax credit under Indian law, with an official source.',
                                    conversation='GST-eligibility', case_id='C-legal-evidence')
    retrieval.assert_awaited()
    assert result.body['answer']['completeness'] == 'partial'
    assert output(result)['vat_payable'] == '226800'


async def test_explicit_from_to_inventory_revision_uses_active_version(offline_http):
    await offline_http.ask(WHOLESALE, conversation='inventory-from-to', case_id='B-from-to-baseline')
    result = await offline_http.ask('Change only closing inventory from £95,000 to £85,000.',
                                    conversation='inventory-from-to', case_id='B-from-to')
    assert output(result)['cost_of_goods_sold'] == '570000'
    inconsistent = await offline_http.ask('Change only closing inventory from £95,000 to £80,000.',
                                          conversation='inventory-from-to', case_id='B-wrong-version')
    assert inconsistent.body['outcome'] == 'clarification_required'
    assert inconsistent.body['calculation']['error_code'] == 'AMBIGUOUS_INPUTS'
    assert not inconsistent.trace['model_requests']
    corrected = await offline_http.ask('Change only closing inventory from £85,000 to £80,000.',
                                       conversation='inventory-from-to', case_id='B-after-rejected-version')
    assert output(corrected)['cost_of_goods_sold'] == '575000'
    assert output(corrected)['profit_before_tax'] == '130000'


async def test_provider_timeout_retains_specific_failure_code_without_standard_fallback(offline_http):
    import asyncio
    from tests.test_agent_request_size import QUESTION
    offline_http.state.failure = asyncio.TimeoutError()
    result = await offline_http.ask(QUESTION, conversation='provider-timeout', case_id='F-timeout')
    assert result.body['answer']['completeness'] == 'partial'
    assert output(result)['current_profit_before_tax'] == '177000'
    failures = [a['payload']['error'] for a in result.trace['audit'] if a['event'] == 'composition_failed']
    assert failures == ['provider_timeout']
    # One initial call and the existing reserved final-answer attempt; no
    # fresh standard-composition fallback after those bounded attempts.
    assert len([e for e in result.trace['model_exchanges'] if 'error' in e]) == 2
    assert not next(a['payload']['fell_back'] for a in result.trace['audit'] if a['event'] == 'agent_completed')
    assert 'timed out' in ' '.join(result.body['answer']['limitations']).lower()


async def test_generic_service_failure_is_not_misreported_as_truncation(offline_http):
    from tests.test_agent_request_size import QUESTION
    offline_http.state.failure = RuntimeError('synthetic_service_unavailable')
    result = await offline_http.ask(QUESTION, conversation='provider-service', case_id='F-service')
    assert result.body['answer']['completeness'] == 'partial'
    assert output(result)['current_operating_profit'] == '191000'
    errors = [a['payload']['error'] for a in result.trace['audit'] if a['event'] == 'composition_failed']
    assert errors == ['model_provider_unavailable']
    assert 'output limit' not in str(result.body['answer']['limitations']).lower()
