import json
from pathlib import Path
import pytest
from tests.offline_http_support import offline_http  # noqa: F401
from app.orchestration.input_requirements import missing_vat_inputs, missing_tax_inputs

Q = json.loads((Path(__file__).parent/'fixtures/manual_transcript_20261021.json').read_text())['queries']


def values(result):
    return {v['name']: v['value'] for v in result.body['calculation']['outputs']}


def test_shared_gst_assumptions_are_not_requested_again():
    assert missing_vat_inputs(Q['gst']) is None


def test_ignore_vat_does_not_turn_accrual_into_vat_question():
    assert missing_vat_inputs(Q['accrual']) is None


def test_accounting_profit_does_not_establish_corporation_tax():
    assert missing_tax_inputs(Q['corporation'])


@pytest.mark.parametrize('prior', [False, True])
async def test_original_gst_and_one_variable_followup(offline_http, prior):
    if prior:
        await offline_http.ask(Q['income'], conversation='gst', case_id='gst-unrelated')
    first = await offline_http.ask(Q['gst'], conversation='gst', case_id=f'exact-gst-{prior}')
    assert first.body['outcome'] == 'answered'
    assert values(first)['vat_payable'] == '84600'
    assert values(first)['input_ledger_difference'] == '0'
    assert values(first)['output_ledger_difference'] == '0'
    second = await offline_http.ask(Q['gst_followup'], conversation='gst', case_id=f'exact-gst-change-{prior}')
    assert values(second)['vat_payable'] == '86400'
    assert values(second)['input_ledger_difference'] == '-1800'  # calculated minus recorded
    assert values(second)['output_ledger_difference'] == '0'
    assert second.body['answer']['completeness'] == 'complete'
    assert not first.trace['model_requests'] and not second.trace['model_requests']


async def test_full_income_statement_does_not_stop_after_gross_margin(offline_http):
    r = await offline_http.ask(Q['income'], conversation='income', case_id='exact-income')
    v = values(r)
    assert v['net_sales'] == '780000'
    assert v['gross_profit'] == '290000'
    assert v['operating_profit'] == '110000'
    assert v['profit_before_tax'] == '101000'
    assert r.body['answer']['completeness'] == 'complete'
    assert not r.trace['model_requests']
    revised = await offline_http.ask(Q['depreciation_followup'], conversation='income', case_id='exact-depreciation-change')
    assert values(revised)['profit_before_tax'] == '97000'
    assert values(revised)['original_profit_before_tax'] == '101000'
    assert not revised.trace['model_requests']


async def test_month_range_respectively_actually_renders_and_preserves_dataset(offline_http):
    r = await offline_http.ask(Q['monthly'], conversation='monthly', case_id='exact-monthly')
    assert r.body['visualization'] is not None
    assert '576,000' in r.body['answer']['text']
    assert '40%' in r.body['answer']['text']
    revised = await offline_http.ask(Q['bars'], conversation='monthly', case_id='exact-bars')
    assert revised.body['visualization']['type'] == 'BAR'
    assert revised.body['visualization']['data'] == r.body['visualization']['data']
    assert not r.trace['model_requests'] and not revised.trace['model_requests']


async def test_accrual_does_not_require_vat_or_claim_it_was_posted(offline_http):
    r = await offline_http.ask(Q['accrual'], conversation='accrual', case_id='exact-accrual')
    assert r.body['outcome'] == 'answered'
    assert r.body['answer']['completeness'] == 'complete'
    assert '4,800' in r.body['answer']['text']
    assert not r.trace['model_requests']


async def test_six_section_report_retains_supplied_calculations_on_provider_failure(offline_http):
    r = await offline_http.ask(Q['report'], conversation='report', case_id='exact-report')
    assert values(r)['current_profit_before_tax'] == '112000'
    assert values(r)['previous_profit_before_tax'] == '110000'
    assert r.body['outcome'] == 'unavailable'
    assert r.body['next_action']['type'] == 'report_incomplete'


async def test_independent_multi_part_answer_retains_gross_profit_and_margin(offline_http):
    r = await offline_http.ask(Q['multipart'], conversation='multi', case_id='exact-multipart')
    assert '280,000' in r.body['answer']['text']
    assert '35' in r.body['answer']['text']
    assert r.body['answer']['completeness'] == 'partial'


async def test_independent_audit_question_does_not_send_old_statement_to_model(offline_http):
    await offline_http.ask(Q['income'],conversation='audit',case_id='audit-old-income')
    r = await offline_http.ask(Q['cutoff'],conversation='audit',case_id='exact-cutoff-no-old-history')
    calls = [c for c in r.trace['model_requests'] if c.get('tools')]
    assert calls
    assert all('800,000' not in str(c['messages']) for c in calls)


def test_successive_statement_corrections_retain_prior_changes():
    from app.orchestration.schemas import ConversationMessage
    from app.orchestration.calculations.statements import structured_statement_followup
    result = structured_statement_followup('Change only rent to £40,000.',[
        ConversationMessage(role='user',content=Q['income']),
        ConversationMessage(role='user',content=Q['depreciation_followup'])])
    assert {o.name:o.value for o in result.outputs}['profit_before_tax'] == 93000


def test_local_request_size_failure_has_safe_origin_diagnostics():
    from app.domains.model_gateway.agent_budget import GenerationBudget
    from app.domains.model_gateway.errors import ProviderRequestTooLarge
    with pytest.raises(ProviderRequestTooLarge) as failure:
        GenerationBudget(max_total_tokens=64000,max_request_tokens=100).completion_allowance([
            {'role':'user','content':'A sufficiently long local test prompt'}])
    assert failure.value.origin == 'local_preflight'
    assert failure.value.request_limit == 100
    assert failure.value.input_estimate > 100


def test_unknown_statement_expense_is_not_silently_dropped():
    from app.orchestration.calculations.engine import calculate_from_query
    assert calculate_from_query(Q['income']+' Insurance expense £1,000.').status == 'not_matched'


async def test_unsourced_framework_rule_is_not_released_as_verified_audit_advice(offline_http):
    from tests.test_agent_loop import _reply
    offline_http.state.responses = [_reply('IFRS 15 and UK GAAP require a bill-and-hold liability whenever goods remain in the warehouse.')]
    r = await offline_http.ask(Q['cutoff'],conversation='cutoff-rule',case_id='cutoff-unsourced-rule')
    assert 'require a bill-and-hold liability' not in ((r.body.get('answer') or {}).get('text') or '')
