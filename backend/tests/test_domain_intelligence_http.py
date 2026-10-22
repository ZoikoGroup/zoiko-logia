"""Isolated authenticated domain workflows; no provider calls."""
from tests.offline_http_support import offline_http  # noqa: F401

DEPRECIATION = 'bought machine 24000 gbp lasts 6 years no resale value straight line depreciation yearly and monthly how much'
BANK = ('Prepare a bank reconciliation. All amounts GBP. Bank statement balance £12,000, '
        'cash book balance £12,600, deposits in transit £1,500, outstanding cheques £700, '
        'bank charges £100, interest received £300. There are no other reconciling items. '
        'Calculate both adjusted balances and any remaining discrepancy. Show adjustment directions.')
INVENTORY = ('Use periodic FIFO and periodic weighted average. All purchases occurred before the only sale. '
             'Opening inventory 100 units at £10 each; purchases 200 units at £13 each; units sold 180. '
             'Calculate cost of goods sold and closing inventory for both methods. Show formulas.')


def values(r):
    return {x['name']: x['value'] for x in (r.body.get('calculation') or {}).get('outputs', [])}


async def test_depreciation_natural_language_all_inputs_and_periods(offline_http):
    r = await offline_http.ask(DEPRECIATION, case_id='depreciation-natural')
    assert values(r)['annual_depreciation'] == '4000'
    assert values(r)['monthly_depreciation'].startswith('333.333')
    assert r.body['answer']['completeness'] == 'complete'
    assert not r.trace['model_requests']


async def test_bank_reconciliation_directions_and_residual(offline_http):
    r = await offline_http.ask(BANK, case_id='bank-reconciliation')
    assert values(r)['adjusted_bank_balance'] == '12800'
    assert values(r)['adjusted_cash_book_balance'] == '12800'
    assert values(r)['unreconciled_difference'] == '0'
    assert r.body['answer']['completeness'] == 'complete'


async def test_periodic_inventory_completes_both_methods(offline_http):
    r = await offline_http.ask(INVENTORY, case_id='inventory-two-methods')
    assert values(r)['fifo_cost_of_goods_sold'] == '2040'
    assert values(r)['fifo_closing_inventory'] == '1560'
    assert values(r)['weighted_average_cost_of_goods_sold'] == '2160'
    assert values(r)['weighted_average_closing_inventory'] == '1440'
    assert r.body['answer']['completeness'] == 'complete'


async def test_inventory_revisions_accumulate_only_on_target(offline_http):
    from tests.test_paid_manual_transcript import WHOLESALE, CORRECTION
    await offline_http.ask(WHOLESALE, case_id='inventory-revision-base', conversation='revision')
    await offline_http.ask(CORRECTION, case_id='inventory-revision-first', conversation='revision')
    result = await offline_http.ask('Closing inventory was understated by £2,000. Correct only that figure and update the results.',
                                    case_id='inventory-revision-second', conversation='revision')
    assert values(result)['cost_of_goods_sold'] == '568000'
    assert values(result)['operating_profit'] == '146000'
    assert values(result)['finance_costs'] == '9000'
    changed = {i['name']: i for i in result.body['calculation']['inputs']}
    assert changed['closing_inventory']['value'] == '87000'
    assert changed['closing_inventory']['source_location'] == 'query'
    assert changed['purchases']['value'] == '570000'
    assert changed['purchases']['source_location'] == 'conversation_history'


async def test_chart_and_task_state_have_durable_provenance(offline_http):
    import hashlib
    import json
    from sqlalchemy import select
    from app.domains.orchestration_state.models import ConversationTurn
    question = ('Revenue £900,000, cost of sales £500,000, operating expenses £150,000. '
                'Calculate operating profit. Show a bar chart.')
    result = await offline_http.ask(question, case_id='chart-audit', conversation='chart-task')
    visual = result.body['visualization']
    assert visual['type'] == 'BAR'
    receipt = next(a['payload'] for a in result.trace['audit'] if a['event'] == 'answer_receipt')
    provenance = receipt['visualization_provenance']
    dataset = {key: visual[key] for key in ['data', 'series', 'donut', 'scatter', 'rows', 'columns', 'sources', 'unit']}
    assert provenance['dataset_sha256'] == hashlib.sha256(json.dumps(dataset, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert provenance['formula_ids']
    async with offline_http.sessions() as db:
        turn = await db.scalar(select(ConversationTurn).where(ConversationTurn.query_id == result.body['query_id']))
        state = turn.snapshot['task_state']
    assert state['response_completion'] == 'complete'
    assert state['figure_version'] == result.body['query_id']
    assert state['visualization_id'] == visual['id']
    assert state['requested_sections'] == ['visual']
    assert not result.trace['model_requests']
