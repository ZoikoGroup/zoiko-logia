from tests.offline_http_support import offline_http  # noqa: F401
from tests.test_agent_request_size import QUESTION
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.calculations.visuals import calculation_visual


def test_explicit_table_preference_wins_over_automatic_comparison():
    result = calculate_from_query(QUESTION)
    spec, _ = calculation_visual(result, QUESTION+' Use only text and tables, no charts.', 'explicit-table')
    assert spec is None
    for preference in ['Do not include charts.', 'Do not include any charts.', 'Tables only.']:
        assert calculation_visual(result, QUESTION+' '+preference, 'preference')[0] is None


async def test_exact_message_and_turn_identity_survive_normalisation(offline_http):
    result = await offline_http.client.post('/api/v1/orchestration/ask', json={
        'query': 'Revenue £100 and cost of sales £60. Calculate gross profit.',
        'conversation_id': 'identity', 'turn_id': 'turn-test', 'request_id': 'client-test'},
        headers={'Authorization': 'Bearer offline-actor-a', 'Idempotency-Key': 'client-test'})
    assert result.status_code == 200, result.json()
    identity = result.json()['request_integrity']
    assert identity['turn_id'] == 'turn-test' and identity['request_id'] == 'client-test'
    assert identity['conversation_id'] == 'identity'
    assert identity['relation'] == 'independent'


async def test_chart_view_followup_reuses_server_dataset_without_model(offline_http):
    initial = await offline_http.ask('Show monthly revenue as a line chart: January 2025 £100, February 2025 £120, March 2025 £90.',
                                      case_id='visual-initial', conversation='visual-follow')
    assert initial.body['visualization'], initial.body
    revised = await offline_http.ask('Make it a bar chart.', case_id='visual-view-change', conversation='visual-follow')
    assert revised.body['visualization']['type'] == 'BAR'
    assert revised.body['visualization']['data'] == initial.body['visualization']['data']
    assert revised.body['visualization']['unit'] == initial.body['visualization']['unit']
    assert not revised.trace['model_requests']
    assert revised.body['visualization_intent']['output_type'] == 'bar_chart'


def test_report_sections_and_unfinished_table_are_checked():
    from app.orchestration.answer_coverage import check_requested_deliverables
    question = 'Prepare a report with these sections:\n1. Executive summary\n2. Financial analysis\n3. Next steps'
    checks = check_requested_deliverables(question, '## Executive summary\nFigures provided.\n## Next steps\nReview records.')
    assert [c.description for c in checks if c.status == 'incomplete'] == ['Financial analysis']
    assert any(c.status == 'incomplete' for c in check_requested_deliverables('Show results.', '| Item | Amount |\n| --- | --- |\n| Revenue'))


def test_original_message_remains_exact_after_internal_normalisation():
    from app.orchestration.schemas import AskKritonRequest
    request = AskKritonRequest(query='IAS 1and explain')
    assert request.query == 'IAS 1 and explain'
    assert request.original_message == 'IAS 1and explain'
    assert request.model_copy(update={'jurisdiction':'GB'}).original_message == 'IAS 1and explain'


async def test_chart_history_cannot_cross_tenants(offline_http):
    await offline_http.ask('Show revenue as a line chart: January 2025 £100, February 2025 £120, March 2025 £90.', case_id='chart-tenant-a', conversation='shared-chart')
    other = await offline_http.ask('Make it a bar chart.', case_id='chart-tenant-b', conversation='shared-chart', actor='actor-b')
    assert other.body['visualization'] is None
    assert not any(r['turns'] for r in other.trace['history_selection'])


async def test_missing_report_section_is_partial_through_http(offline_http):
    from tests.test_agent_loop import _reply, _call
    question = 'Revenue £100, cost of sales £60. Calculate gross profit. Prepare a report with these sections:\n1. Calculation\n2. Explanation\n3. Next steps'
    offline_http.state.responses = [_reply(tool_calls=[_call('calculate', {'expression':'100-60'})]), _reply('## Calculation\nGross profit = £100 - £60 = £40.\n## Next steps\nReview the supplied records.')]
    result = await offline_http.ask(question, case_id='missing-section', conversation='report-sections')
    assert result.body['answer']['completeness'] == 'partial'
    assert any(d['description']=='Explanation' and d['status']=='incomplete' for d in result.body['requested_deliverables'])
    assert 'Explanation' in result.body['visualization_intent']['fallback_reason']


async def test_correction_typed_state_names_only_changed_input(offline_http):
    from tests.test_paid_manual_transcript import WHOLESALE
    await offline_http.ask(WHOLESALE, case_id='typed-state-before', conversation='typed-state')
    changed = await offline_http.ask('Change closing inventory to £85,000.', case_id='typed-state-after', conversation='typed-state')
    assert changed.body['request_integrity']['relation'] == 'correction'
    assert changed.body['calculation_state']['changed_inputs'] == ['closing_inventory']
    assert {i['name']:i['value'] for i in changed.body['calculation_state']['original_inputs']}['closing_inventory'] == '95000'


async def test_idempotency_is_bound_to_exact_original_message(offline_http):
    body={'query':'Revenue £100, cost of sales £60and calculate gross profit.', 'conversation_id':'original-hash'}
    headers={'Authorization':'Bearer offline-actor-a','Idempotency-Key':'exact-original'}
    first=await offline_http.client.post('/api/v1/orchestration/ask',json=body,headers=headers)
    assert first.status_code==200
    import hashlib
    assert first.json()['request_integrity']['current_message_sha256'] == hashlib.sha256(body['query'].encode()).hexdigest(), first.json()['request_integrity']
    second=await offline_http.client.post('/api/v1/orchestration/ask',json={**body,'query':body['query'].replace('60and','60 and')},headers=headers)
    assert second.status_code==409


async def test_monthly_performance_selects_real_chart_without_chart_instruction(offline_http):
    result=await offline_http.ask('Monthly revenue: January 2025 £100, February 2025 £120, March 2025 £90. Summarize changes.',
                                  case_id='automatic-monthly',conversation='monthly-default')
    assert result.body['visualization']['type']=='LINE'
    assert [p['y'] for p in result.body['visualization']['data']]==[100,120,90]
    assert result.body['visualization_intent']['currency']=='GBP'
    assert not result.trace['model_requests']


def test_existing_inline_families_have_truthful_structured_selection():
    from app.orchestration.supplied_charts import build_supplied_chart
    from app.orchestration.visualization.router import describe_visualization
    query='Show a pie chart: Payroll £60, Rent £40.'
    chart=build_supplied_chart(query)
    intent=describe_visualization(query,None,legacy_text=chart.markdown())
    assert intent.output_type=='pie_chart'
    assert intent.renderer_payload==chart.chart
    assert intent.dataset==chart.chart['data']


async def test_older_unbound_cached_answer_cannot_replace_current_question(offline_http):
    from app.orchestration.identifiers import store_idempotency, scope_idempotency_key
    key=scope_idempotency_key('legacy-unbound',None,'actor-a')
    async with offline_http.sessions() as db:
        await store_idempotency(db,key,'synthetic-a',{'query_id':'older-unbound-response'})
        await db.commit()
    response=await offline_http.client.post('/api/v1/orchestration/ask',json={'query':'Revenue £100, cost of sales £60. Calculate gross profit.'},
        headers={'Authorization':'Bearer offline-actor-a','Idempotency-Key':'legacy-unbound'})
    assert response.status_code==409
    assert 'older-unbound-response' not in response.text


async def test_multiple_corrections_retain_root_original_inputs(offline_http):
    from tests.test_paid_manual_transcript import WHOLESALE
    await offline_http.ask(WHOLESALE,case_id='root-state-base',conversation='root-state')
    await offline_http.ask('Change closing inventory to £85,000.',case_id='root-state-first',conversation='root-state')
    second=await offline_http.ask('Change closing inventory to £80,000.',case_id='root-state-second',conversation='root-state')
    state=second.body['calculation_state']
    assert {i['name']:i['value'] for i in state['original_inputs']}['closing_inventory']=='95000'
    assert {i['name']:i['value'] for i in state['inputs']}['closing_inventory']=='80000'
    assert state['changed_inputs']==['closing_inventory']
