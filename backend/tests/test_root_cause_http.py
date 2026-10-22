"""A–G investigation through POST /ask; original benchmark files stay unchanged."""
from tests.offline_http_support import offline_http  # noqa: F401
from tests.test_paid_manual_transcript import VAT, WHOLESALE, CORRECTION, RECON
from tests.test_agent_request_size import QUESTION
from tests.test_agent_loop import _reply, _call
import pytest

GST = ('Sales ₹2,400,000, sales returns ₹120,000, purchases ₹1,100,000 and purchase returns ₹80,000. '
       'All amounts exclude GST. Apply the supplied 18% GST rate to net sales and net purchases. '
       'The output GST ledger says ₹410,400 and the input tax credit ledger says ₹183,600. '
       'Calculate net GST payable before other adjustments and identify whether both stated ledger figures match.')


def output(response):
    return {item['name']: item['value'] for item in response.body['calculation']['outputs']}


async def test_http_vat_complete_supplied_input(offline_http):
    result = await offline_http.ask(VAT, case_id='A-fresh', conversation='A')
    assert output(result)['vat_amount'] == '25000'
    assert result.body['answer']['completeness'] == 'complete'


async def test_http_gst_returns_and_ledger_matching(offline_http):
    result = await offline_http.ask(GST, case_id='F-after-fix', conversation='F')
    assert output(result)['output_vat_on_sales'] == '410400'
    assert output(result)['input_vat_on_purchases'] == '183600'
    assert output(result)['vat_payable'] == '226800'
    assert 'match' in result.body['answer']['text'].lower()


async def test_http_minimal_derived_cogs(offline_http):
    result = await offline_http.ask('Revenue £960,000, returns £24,000, opening inventory £85,000, '
                                    'purchases £570,000, closing inventory £95,000. '
                                    'Calculate net sales, cost of goods sold and gross profit.',
                                    case_id='B-minimal', conversation='B')
    assert output(result)['net_sales'] == '936000'
    assert output(result)['cost_of_goods_sold'] == '560000'
    assert output(result)['gross_profit'] == '376000'


async def test_http_inventory_correction_uses_durable_user_context(offline_http):
    await offline_http.ask(WHOLESALE, case_id='C-baseline', conversation='C')
    result = await offline_http.ask(CORRECTION, case_id='C-corrected', conversation='C')
    v = output(result)
    assert v['cost_of_goods_sold'] == '570000' and v['gross_profit'] == '366000'
    assert v['operating_expenses'] == '222000' and v['operating_profit'] == '144000'
    assert v['finance_costs'] == '9000' and v['profit_before_tax'] == '135000'


async def test_http_discrepancy_task_and_followup_do_not_inherit_other_figures(offline_http):
    await offline_http.ask(WHOLESALE, case_id='D-unrelated-baseline', conversation='D')
    result = await offline_http.ask(RECON, case_id='D-new-task', conversation='D')
    v = output(result)
    assert v['calculated_gross_profit'] == '180000' and v['difference_reported_minus_calculated'] == '30000'
    assert v['gross_margin_calculated'] == '36.00' and v['gross_margin_reported'] == '42.00'
    assert '936,000' not in result.body['answer']['text']
    followup = await offline_http.ask('Explain the discrepancy using only my supplied figures. '
                                      'Distinguish what the arithmetic proves from what an accountant must investigate.',
                                      case_id='E-durable-followup', conversation='D')
    assert followup.body['answer']['completeness'] == 'complete'
    assert '180,000' in followup.body['answer']['text'] and 'What the accountant must confirm' in followup.body['answer']['text']


async def test_http_long_request_reports_model_failure_and_preserves_verified_results(offline_http):
    result = await offline_http.ask(QUESTION, case_id='G-provider-failure', conversation='G')
    assert result.body['answer']['completeness'] == 'partial'
    assert output(result)['current_operating_profit'] == '191000'
    assert output(result)['current_profit_before_tax'] == '177000'
    assert any(row['event'] == 'composition_failed' for row in result.trace['audit'])


async def test_http_vat_and_gst_after_unrelated_task_use_current_assumptions(offline_http):
    await offline_http.ask(WHOLESALE, case_id='A-F-unrelated', conversation='mixed-tax')
    vat = await offline_http.ask(VAT, case_id='A-multiturn', conversation='mixed-tax')
    gst = await offline_http.ask(GST, case_id='F-multiturn', conversation='mixed-tax')
    assert output(vat)['vat_amount'] == '25000'
    assert output(gst)['vat_payable'] == '226800'
    assert '936,000' not in gst.body['answer']['text']


async def test_http_discrepancy_fresh_and_tenant_scope(offline_http):
    first = await offline_http.ask(RECON, case_id='D-fresh', conversation='shared-name')
    assert output(first)['calculated_gross_profit'] == '180000'
    second = await offline_http.ask('Explain the discrepancy using only my supplied figures.',
                                   case_id='E-other-tenant', conversation='shared-name', actor='actor-b')
    assert '500,000' not in str(second.body) and '180,000' not in str(second.body)
    assert all(not read['turns'] for read in second.trace['history_selection'])
    assert second.body['outcome'] == 'clarification_required'
    assert not second.trace['model_requests']


async def test_http_idempotent_replay_does_not_repeat_calculations_or_change_audit(offline_http):
    first = await offline_http.ask(VAT, case_id='A-replay-first', conversation='replay', key='same-key')
    second = await offline_http.ask(VAT, case_id='A-replay-second', conversation='replay', key='same-key')
    assert first.body == second.body
    assert [a['id'] for a in first.trace['audit']] == [a['id'] for a in second.trace['audit']]
    assert not second.trace['model_requests']


@pytest.mark.parametrize('failure', ['size', 'timeout', 'truncation'])
async def test_http_g_long_failures_never_become_complete(offline_http, failure):
    from app.domains.model_gateway.errors import ProviderRequestTooLarge, ProviderResponseIncomplete
    import asyncio
    offline_http.state.failure = {'size': ProviderRequestTooLarge(), 'timeout': asyncio.TimeoutError(),
                                  'truncation': ProviderResponseIncomplete()}[failure]
    result = await offline_http.ask(QUESTION, case_id='G-' + failure, conversation='long-' + failure)
    assert result.body['answer']['completeness'] == 'partial'
    assert output(result)['current_gross_profit'] == '505000'
    finals = [a['payload'] for a in result.trace['audit'] if a['event'] == 'response_finalised']
    assert finals and finals[-1]['completeness'] == 'partial'


async def test_http_g_scripted_success_covers_all_parts_then_recalculates_followup(offline_http):
    text = ('Net sales = £1,250,000 − £35,000 = £1,215,000.\n'
            'Gross profit = £1,215,000 − £710,000 = £505,000.\n'
            'Gross margin = £505,000 ÷ £1,215,000 × 100 = 41.56%.\n'
            'Operating expenses = £165,000 + £48,000 + £32,000 + £41,000 + £28,000 = £314,000.\n'
            'Operating profit = £505,000 − £314,000 = £191,000.\n'
            'Operating margin = £191,000 ÷ £1,215,000 × 100 = 15.72%.\n'
            'Profit before tax = £191,000 − £14,000 = £177,000.\n\n'
            '| Current-year measure | Result |\n| --- | --- |\n'
            '| Net sales | £1,215,000 |\n| Gross profit | £505,000 |\n| Gross margin | 41.56% |\n'
            '| Operating expenses | £314,000 |\n| Operating profit | £191,000 |\n'
            '| Operating margin | 15.72% |\n| Profit before tax | £177,000 |\n\n'
            '| Measure | Previous | Current | Increase | Increase % |\n| --- | --- | --- | --- | --- |\n'
            '| Gross profit | £440,000 | £505,000 | £65,000 | 14.77% |\n'
            '| Operating profit | £155,000 | £191,000 | £36,000 | 23.23% |\n\n'
            'Higher net sales and the change in cost of goods sold explain the gross-profit change. '
            'Operating expenses increased; the figures do not establish why individual costs changed.\n\n'
            'Management questions: what explains the returns? Which expense movements need review? '
            'What do working-capital records show about cash conversion?')
    offline_http.state.responses = [_reply(tool_calls=[_call('calculate', {'expression': '1250000-35000-710000'})]), _reply(text)]
    result = await offline_http.ask(QUESTION, case_id='G-scripted-complete', conversation='long-success')
    assert result.body['answer']['completeness'] == 'complete'
    for phrase in ('505,000', '191,000', '177,000', '14.77%', '23.23%', 'Management questions'):
        assert phrase in result.body['answer']['text']
    assert '| Operating margin | 15.72% |' in result.body['answer']['text']
    follow = await offline_http.ask('Increase current-year gross sales by 8%. Keep sales returns at £35,000 and '
                                   'cost of goods sold at £710,000.', case_id='G-followup', conversation='long-success')
    assert output(follow)['revised_operating_profit'] == '291000.00'


async def test_http_g_truncated_provider_response_is_detected_at_real_adapter(offline_http, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), 'KRITON_AGENT_MODE', False)
    response = _reply('The answer ends halfway through a sentence')
    response.choices[0].finish_reason = 'length'
    offline_http.state.responses = [response]
    result = await offline_http.ask(QUESTION, case_id='G-real-length-response', conversation='length')
    assert result.body['answer']['completeness'] == 'partial'
    failures = [a['payload'] for a in result.trace['audit'] if a['event'] == 'composition_failed']
    assert failures and failures[-1]['error'] == 'provider_response_incomplete'
    assert any(choice['finish_reason'] == 'length' for exchange in result.trace['model_exchanges']
               for choice in exchange.get('response', {}).get('choices', []))
