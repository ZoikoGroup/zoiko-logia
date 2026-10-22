import json
from pathlib import Path
import pytest
from tests.offline_http_support import offline_http  # noqa: F401

Q=json.loads((Path(__file__).parent/'fixtures/systemic_scenarios_20261021.json').read_text())['queries']


def values(response):
    assert response.body.get('calculation'), response.body
    return {i['name']:i['value'] for i in response.body['calculation']['outputs']}


@pytest.mark.parametrize('prior',[False,True])
async def test_bank_baseline_and_one_variable_revision(offline_http,prior):
    if prior:
        await offline_http.ask('Revenue £100, cost of sales £60. Calculate gross profit.',conversation='bank',case_id='bank-unrelated')
    base=await offline_http.ask(Q['bank'],conversation='bank',case_id=f'bank-{prior}')
    assert values(base)['adjusted_cash_book_balance']=='28500'
    assert values(base)['adjusted_bank_balance']=='28500'
    assert base.body['answer']['completeness']=='complete'
    revised=await offline_http.ask(Q['cheques'],conversation='bank',case_id=f'bank-revised-{prior}')
    assert values(revised)['adjusted_bank_balance']=='28400'
    assert values(revised)['adjusted_cash_book_balance']=='28500'
    assert values(revised)['unreconciled_difference']=='-100'
    assert revised.body['answer']['completeness']=='complete'
    assert not base.trace['model_requests'] and not revised.trace['model_requests']


async def test_vat_refund_returns_final_balances(offline_http):
    base=await offline_http.ask(Q['vat'],conversation='vat',case_id='vat-inclusive-baseline')
    assert values(base)['amount_excluding_vat']=='60000'
    revised=await offline_http.ask(Q['refund'],conversation='vat',case_id='vat-inclusive-refund')
    assert values(revised)['amount_excluding_vat']=='55000'
    assert values(revised)['vat_amount']=='11000'
    assert revised.body['answer']['completeness']=='complete'
    assert not base.trace['model_requests'] and not revised.trace['model_requests']


async def test_cvp_capacity_and_revised_variable_cost(offline_http):
    base=await offline_http.ask(Q['cvp'],conversation='cvp',case_id='cvp-baseline')
    assert values(base)['units_for_target_profit']=='9000'
    assert values(base)['maximum_profit_at_capacity']=='60000'
    revised=await offline_http.ask(Q['variable_cost'],conversation='cvp',case_id='cvp-revised')
    assert values(revised)['units_for_target_profit']=='10000'
    assert values(revised)['break_even_whole_units']=='6667'
    assert values(revised)['maximum_profit_at_capacity']=='36000'
    assert not base.trace['model_requests'] and not revised.trace['model_requests']


async def test_quarterly_grouped_chart_and_table_followup(offline_http):
    r=await offline_http.ask(Q['quarterly'],conversation='quarters',case_id='quarterly-grouped')
    assert r.body['visualization']['type']=='GROUPED_BAR'
    assert len(r.body['visualization']['series'])==2
    assert '350,000' in r.body['answer']['text'] and '358,000' in r.body['answer']['text']
    assert '2.29%' in r.body['answer']['text']
    follow=await offline_http.ask(Q['table_only'],conversation='quarters',case_id='quarterly-table-only')
    assert follow.body['visualization'] is None
    assert '350,000' in follow.body['answer']['text'] and '358,000' in follow.body['answer']['text']
    assert follow.body['answer']['completeness']=='complete'
    assert not r.trace['model_requests'] and not follow.trace['model_requests']


def test_period_identifier_is_not_an_actual_value():
    from app.orchestration.intent_classifier import explicit_target_pair
    assert explicit_target_pair(Q['quarterly']) is None


async def test_income_tax_missing_context_is_local_clarification(offline_http):
    r=await offline_http.ask(Q['income_tax'],case_id='income-tax-missing-context')
    assert r.body['outcome']=='clarification_required'
    assert not r.trace['model_requests']


async def test_loan_payment_journal_from_supplied_assumptions(offline_http):
    r=await offline_http.ask(Q['loan'],case_id='loan-payment')
    assert values(r)['loan_liability_debit']=='15000'
    assert values(r)['interest_expense_debit']=='3000'
    assert values(r)['cash_credit']=='18000'
    assert r.body['answer']['completeness']=='complete'
    assert not r.trace['model_requests']


def test_history_does_not_turn_an_independent_balance_stage_into_a_scenario():
    from app.orchestration.figure_attribution import tagged_facts,REVISED
    assert not any(tag==REVISED for _,tag in tagged_facts(Q['bank'],[Q['tax_adjustment']]))


@pytest.mark.parametrize('key',['cheques','refund','variable_cost'])
async def test_fresh_revision_never_invents_a_baseline(offline_http,key):
    r=await offline_http.ask(Q[key],conversation='no-baseline',case_id='fresh-'+key)
    assert r.body['outcome']=='clarification_required'
    assert not r.trace['model_requests']


async def test_new_task_blocks_reuse_of_an_older_bank_scenario(offline_http):
    await offline_http.ask(Q['bank'],conversation='boundary',case_id='boundary-bank')
    await offline_http.ask(Q['vat'],conversation='boundary',case_id='boundary-vat')
    result=await offline_http.ask(Q['cheques'],conversation='boundary',case_id='boundary-revision')
    assert result.body['outcome']=='clarification_required'
    assert not result.trace['model_requests']


async def test_successive_refunds_keep_the_active_receipts_balance(offline_http):
    await offline_http.ask(Q['vat'],conversation='refunds',case_id='refunds-base')
    await offline_http.ask(Q['refund'],conversation='refunds',case_id='refunds-first')
    revised=await offline_http.ask(Q['refund'].replace('£6,000','£1,200'),conversation='refunds',case_id='refunds-second')
    assert values(revised)['amount_excluding_vat']=='54000'
    assert values(revised)['vat_amount']=='10800'


async def test_mixed_conversation_recalculates_only_the_current_task(offline_http):
    for key in ['vat','refund','bank','cheques','cvp','variable_cost','quarterly','table_only']:
        r=await offline_http.ask(Q[key],conversation='all-scenarios',case_id='mixed-'+key)
        assert r.body['outcome']=='answered',r.body
        assert r.body['answer']['completeness']=='complete'
        assert not r.trace['model_requests']


async def test_inventory_analysis_preserves_unverified_management_claim(offline_http):
    r=await offline_http.ask(Q['inventory'],case_id='inventory-investigation')
    assert values(r)['quantity_difference']=='30'
    assert values(r)['value_difference']=='720'
    assert 'not verified' in r.body['answer']['text']
    assert 'Conditional outcomes' in r.body['answer']['text']
    assert r.body['answer']['completeness']=='complete'
    assert not r.trace['model_requests']


async def test_supplied_approval_policy_does_not_turn_into_fraud_conclusion(offline_http):
    r=await offline_http.ask(Q['invoices'],case_id='invoice-investigation')
    assert values(r)['combined_invoice_amount']=='29700'
    assert 'do not establish' in r.body['answer']['text']
    assert 'Investigation procedures' in r.body['answer']['text']
    assert r.body['answer']['completeness']=='complete'
    assert not r.trace['model_requests']


def test_recovery_does_not_label_unrelated_operands_as_verified():
    from types import SimpleNamespace as N
    from app.domains.model_gateway.agent import verified_working
    receipts=({'expression':'12500+1200-4300','result':'9400','label':'Example'},
              {'expression':'29700+3000-4300','result':'28400','label':'Actual'},
              {'expression':'28450-150+200','result':'28500','label':'Book'},
              {'expression':'28400-28500','result':'-100','label':'Difference'})
    executed={('calculate','k'):N(ok=True,content='',all_receipts=receipts)}
    lines=verified_working(executed,evidence=Q['bank']+'\n'+Q['cheques'])
    assert not any('9400' in line or '12500' in line for line in lines)
    assert any('28400' in line for line in lines)
    assert any('-100' in line for line in lines)


async def test_provider_failure_recovery_filters_ungrounded_receipts():
    import asyncio
    from app.domains.model_gateway.agent import run_agent
    from tests.test_batched_calculator import batch_registry
    from tests.test_verified_work_fallback import FailingAfter
    from tests.test_agent_loop import _call,_reply
    expressions=[{'label':'Unrelated example','expression':'12500+1200-4300'},
                 {'label':'Current bank balance','expression':'29700+3000-4300'}]
    outcome=await run_agent(FailingAfter([_reply(tool_calls=[_call('calculate',{'expressions':expressions})])],asyncio.TimeoutError()),
                            model='m',system_prompt='',user_prompt=Q['bank']+'\n'+Q['cheques'],
                            registry=batch_registry(),granted_permissions=frozenset())
    assert '9400' not in outcome.text and '12500' not in outcome.text
    assert '28400' in outcome.text
    assert len(outcome.calculation_receipts)==1
