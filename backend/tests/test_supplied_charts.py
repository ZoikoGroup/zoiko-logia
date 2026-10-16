"""Failures reported in Kriton's chart acceptance examples."""
import json
from types import SimpleNamespace

import pytest

from app.orchestration.supplied_charts import build_supplied_chart


@pytest.mark.parametrize('query,total', [
    ('Opening cash 50,000; sales +80,000; salaries −45,000; rent −12,000; tax −8,000. Show a waterfall chart and the closing balance.',65000),
    ('Net profit bridge: Revenue 500,000; COGS −220,000; Opex −150,000; Interest −20,000; Tax −27,500. Show a waterfall chart and the net profit.',82500),
])
def test_waterfalls_have_exact_closing_totals(query,total):
    result = build_supplied_chart(query)
    assert result is not None
    assert result.chart['type'] == 'waterfall'
    assert result.chart['series'][0]['data'][-1] == total
    assert f'{total:,}' in result.text
    assert '```chart' in result.markdown()


def test_heatmap_keeps_all_nine_supplied_cells():
    result = build_supplied_chart('Sales heatmap (₹ thousands): North — Jan 120, Feb 135, Mar 150; South — Jan 90, Feb 95, Mar 110; West — Jan 140, Feb 128, Mar 160')
    assert len(result.chart['cells']) == 9
    assert result.chart['cells'][-1] == [2,2,160]
    assert result.chart['categories'] == ['Jan','Feb','Mar']


def test_sankey_allocation_balances():
    result = build_supplied_chart('Show a sankey chart of where revenue goes: Revenue 1,000,000 → Salaries 450,000, Suppliers 300,000, Tax 100,000, Profit 150,000.')
    assert sum(link['value'] for link in result.chart['links']) == 1000000
    assert len(result.chart['nodes']) == 5


def test_scatter_calculates_correlation():
    result = build_supplied_chart('Marketing spend vs sales by month: (10,000, 52,000), (12,000, 58,000), (8,000, 45,000), (15,000, 70,000), (11,000, 55,000). Show a scatter chart. Does higher spend go with higher sales?')
    assert len(result.chart['series'][0]['points']) == 5
    assert '0.998' in result.text


def test_format_followup_preserves_six_observations():
    chart = dict(type='line',title='GBP/USD',categories=['May','Jun','Jul','Aug','Sep','Oct'],series=[dict(name='USD per GBP',data=[1.34,1.32,1.34,1.35,1.33,1.32])])
    history = [SimpleNamespace(role='assistant',content='```chart\n'+json.dumps(chart)+'\n```')]
    result = build_supplied_chart('Now show it as a bar chart.', history)
    assert result.chart == {**chart,'type':'bar'}


def test_missing_march_is_not_invented():
    result = build_supplied_chart('Sales: Jan 100, Feb 120, Apr 140. Show a line chart for Jan to Apr.')
    assert result.chart['series'][0]['data'] == [100,120,140]
    assert 'March is missing' in result.text


def test_region_total_without_invented_currency():
    result = build_supplied_chart('Revenue by region: North 420,000; South 310,000; East 275,000; West 395,000. Show a bar chart and tell me the top region and the total.')
    assert '1,400,000' in result.text
    assert 'North' in result.text
    assert '₹' not in result.text


@pytest.mark.parametrize('query',[
    'Show a line chart of UK inflation for the latest five years.',
    'Sales: Jan 100, Feb 120, something unknown. Show a line chart.',
    'Show a sankey chart: Revenue 100 → Salaries 90, Profit 20.',
    'Show a heatmap: North — Jan 1, Feb 2; South — Jan 3.',
])
def test_incomplete_or_external_data_does_not_use_supplied_path(query):
    assert build_supplied_chart(query) is None


def test_unrelated_turn_prevents_stale_chart_reuse():
    history = [SimpleNamespace(role='user',content='Sales: Jan 100, Feb 120. Show a line chart.'), SimpleNamespace(role='user',content='What is VAT?')]
    assert build_supplied_chart('Show it as a bar chart.',history) is None


def test_different_currencies_do_not_become_pie_slices():
    result = build_supplied_chart('Conversions: USD 1033.80, EUR 922.54, GBP 781.97. Show a pie chart.')
    assert result.chart is None
    assert 'different currencies' in result.text


@pytest.mark.parametrize('query',[
    'Sales: Jan 100, Feb 120. Do not show a line chart.',
    'Sales: Jan 100, Feb 120. Show a line chart only when sales increased.',
])
def test_conditional_or_negated_chart_requests_are_not_automatically_drawn(query):
    assert build_supplied_chart(query) is None


@pytest.mark.parametrize("query,expected", [
    ("Sales: Jan 200, Feb 250, Mar 300. Do not show a chart; only give the total.", "Total sales: 750."),
    ("Opening cash 50,000; sales +80,000; salaries −45,000; rent −12,000; tax −8,000. Show a waterfall chart and the closing balance.", "65,000"),
    ("Sales heatmap (₹ thousands): North — Jan 120, Feb 135, Mar 150; South — Jan 90, Feb 95, Mar 110; West — Jan 140, Feb 128, Mar 160", "heatmap"),
    ("Show a sankey chart of where revenue goes: Revenue 1,000,000 → Salaries 450,000, Suppliers 300,000, Tax 100,000, Profit 150,000.", "1,000,000"),
])
async def test_request_path_does_not_retrieve_or_call_a_model(monkeypatch, query, expected):
    from unittest.mock import AsyncMock
    from app.orchestration import service, review
    from app.orchestration.schemas import AskKritonRequest

    # Real planning, context resolution, safety, parsing and serialization.
    # Only persistence is replaced; external work must never be reached.
    for name in dir(service):
        if name.startswith('audit_'):
            monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, '_finalise_and_return', AsyncMock())
    monkeypatch.setattr(review, 'record_answer', AsyncMock())
    monkeypatch.setattr(service, 'list_authorized_engagements', AsyncMock(return_value=[]))
    forbidden = AsyncMock(side_effect=AssertionError('External retrieval must not run'))
    monkeypatch.setattr(service, 'fetch_live_data', forbidden)
    response = await service.ask_kriton(
        None, None, actor_id='user-test',tenant_id='tenant-test',role='ACCOUNTANT',
        request=AskKritonRequest(query=query),
    )
    assert response.outcome == 'answered'
    assert response.route == 'CALCULATION'
    assert response.answer.computed_from_question
    assert response.answer.citations == []
    assert response.safety.disclaimer_required is False
    assert expected in response.answer.text
    if "Do not show a chart" in query:
        assert response.answer.text == expected
        assert response.answer.response_kind == "calculation"
        assert '```chart' not in response.answer.text
    else:
        assert '```chart' in response.answer.text
    forbidden.assert_not_called()


def test_live_chart_followup_reuses_answer_table_without_refetching():
    history = [SimpleNamespace(role='assistant',content='| Month | USD per GBP |\n|---|---|\n| May | 1.3427 |\n| June | 1.3221 |\n| July | 1.3421 |\n| August | 1.3539 |\n| September | 1.3286 |\n| October | 1.3220 |\n')]
    result = build_supplied_chart('Now show it as a bar chart.',history)
    assert result.chart['categories'] == ['May','June','July','August','September','October']
    assert len(result.chart['series'][0]['data']) == 6


def test_valid_pie_followup_keeps_categories():
    history = [SimpleNamespace(role='user',content='Budget: Digital 40, Print 15, Events 25, PR 20. Show a bar chart.')]
    result = build_supplied_chart('Show it as a pie chart instead.',history)
    assert result.chart['type'] == 'pie'
    assert sum(slice['value'] for slice in result.chart['data']) == 100


@pytest.mark.parametrize("query,expected", [
    ("Sales: Jan 200, Feb 250, Mar 300. Do not show a chart; only give the total.", "Total sales: 750."),
    ("Sales: Jan 200, Feb 250, Mar 300. Only give the total.", "Total sales: 750."),
    ("Costs: Staff £100.25, Rent £50.50. Calculate the total.", "Total costs: £150.75."),
    ("Cash movements: Receipts +200, Payments −50. Show the total only.", "Total cash movements: 150."),
])
def test_total_only_is_deterministic_and_has_no_chart(query, expected):
    result = build_supplied_chart(query)
    assert result.markdown() == expected
    assert result.chart is None
    assert result.response_kind == "calculation"


@pytest.mark.parametrize("query", [
    "Sales: Jan 200, Feb 300. Give the total and explain VAT.",
    "Shares: First 50%, Second 50%. Give the total.",
])
def test_ambiguous_totals_do_not_silently_sum(query):
    assert build_supplied_chart(query) is None


def test_response_kinds_distinguish_charting_explanation_and_arithmetic():
    chart = build_supplied_chart("Orders: Jan 100, Feb 200. Show a bar chart.")
    assert chart.response_kind == "chart"
    explanation = build_supplied_chart("Currencies: USD 100, GBP 90. Show a pie chart.")
    assert explanation.response_kind == "chart_explanation"
    calculation = build_supplied_chart("Sales: Jan 100, Feb 200. Show a bar chart and the total.")
    assert calculation.response_kind == "calculation"


@pytest.mark.parametrize("token", ["unknown", "missing", "n/a", "?", "null", "not provided"])
def test_missing_values_produce_subtotal_and_clarification(token):
    result = build_supplied_chart(f"Sales: Apr 450, May {token}, Jun 625. Only give the total.")
    assert result.text == "Known-values subtotal: 1,075. The complete total cannot be calculated because May is missing."
    assert result.clarification == "Please provide the missing values for May."
    assert result.chart is None


@pytest.mark.parametrize("amounts", ["USD 200, GBP 300", "First $200, Second £300"])
def test_mixed_totals_require_conversion_inputs(amounts):
    result = build_supplied_chart(f"Amounts: {amounts}. Give the total.")
    assert result.clarification
    assert "conversion" in result.text


@pytest.mark.parametrize("amounts,expected", [
    ("Hosting £125.50, Software £240.25, Support £89.75", "£455.50"),
    ("First $1, Second $2", "$3.00"),
    ("First ₹1,00,000, Second ₹25,000", "₹125,000.00"),
])
def test_money_always_keeps_two_decimal_places(amounts,expected):
    result = build_supplied_chart(f"Costs: {amounts}. Calculate the total.")
    assert result is not None
    assert expected in result.text


def test_constant_scatter_explicitly_reports_undefined_correlation():
    result = build_supplied_chart("Spend versus sales: (100, 10), (100, 20), (100, 30). Show a scatter chart and calculate the correlation.")
    assert "undefined" in result.text
    assert "constant" in result.text


@pytest.mark.parametrize("start,end,missing", [("Feb", "Apr", "March"), ("June", "September", "July, August")])
def test_month_gap_disclosure_is_not_specific_to_january(start,end,missing):
    result = build_supplied_chart(f"Sales: {start} 100, {end} 200. Show a line chart.")
    assert missing in result.text


async def test_missing_total_is_a_clarification_without_external_work(monkeypatch):
    from unittest.mock import AsyncMock
    from app.orchestration import service, review
    from app.orchestration.schemas import AskKritonRequest
    for name in dir(service):
        if name.startswith("audit_"):
            monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, "_finalise_and_return", AsyncMock())
    monkeypatch.setattr(review, "record_answer", AsyncMock())
    monkeypatch.setattr(service, "list_authorized_engagements", AsyncMock(return_value=[]))
    forbidden = AsyncMock(side_effect=AssertionError("Must not retrieve incomplete totals"))
    monkeypatch.setattr(service, "fetch_live_data", forbidden)
    response = await service.ask_kriton(None, None, actor_id="u", tenant_id="t", role="ACCOUNTANT",
        request=AskKritonRequest(query="Sales: Apr 450, May unknown, Jun 625. Only give the total."))
    assert response.outcome == "clarification_required"
    assert "Known-values subtotal: 1,075" in response.answer.text
    assert "May" in response.next_action.message
    forbidden.assert_not_called()


def test_waterfall_with_signs_on_the_labels():
    from app.orchestration.supplied_charts import build_supplied_chart

    for query in ("Waterfall: opening cash 100, +sales 60, −costs 45, −tax 10",
                  "Waterfall: opening cash 100, +sales 60, -costs 45, -tax 10"):
        chart = build_supplied_chart(query)
        assert chart is not None and chart.chart["type"] == "waterfall"
        assert chart.chart["series"][0]["data"] == [100.0, 60.0, -45.0, -10.0, 105.0]
        assert chart.text == "Closing balance: 105."
