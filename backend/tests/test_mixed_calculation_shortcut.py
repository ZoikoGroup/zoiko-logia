import pytest

from app.domains.model_gateway.errors import ProviderRateLimited
from app.orchestration.calculations.engine import calculate_from_query, calculation_markdown
from app.orchestration.service import uncalculated_part
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

CONTEXT = ('This request has three independent parts. First, calculate gross profit and gross margin '
           'from revenue of £800,000 and cost of goods sold of £520,000. Second, retrieve the latest '
           'available USD/GBP reference exchange rate and state its source and observation date. '
           'Third, retrieve the latest available share price for the fictional company '
           'Kriton Example Manufacturing with ticker ZZZFICTIONAL123. Complete every possible part.')


@pytest.mark.parametrize('query', [CONTEXT, 'Highlight the most important differences. Context: ' + CONTEXT,
    'Calculate gross profit from revenue £800,000 and COGS £520,000. Retrieve the share price for ticker ABC123.',
    'Calculate gross profit from revenue £800,000 and COGS £520,000. Find the USD/GBP exchange rate for 2026-10-01.',
])
def test_live_lookup_or_comparison_cannot_be_completed_by_calculator(query):
    assert uncalculated_part(query)


def test_supplied_rate_scenario_is_still_calculation_only():
    assert not uncalculated_part('Convert USD 100 at the supplied exchange rate USD/GBP 0.8. Calculate the GBP amount.')


async def test_highlight_request_never_releases_calculation_only_as_complete(pipeline):
    pipeline.agent.side_effect = ProviderRateLimited()
    response, audited = await pipeline.ask('Highlight the most important differences. Context: ' + CONTEXT)
    pipeline.agent.assert_awaited_once()
    assert response.answer.completeness == 'partial'
    assert audited.completeness == 'partial'
    assert 'Most important differences' in response.answer.text
    assert '35.00%' in response.answer.text
    assert 'currency pair' in response.answer.text
    assert 'fictional' in response.answer.text
    assert any('usage allowance' in note for note in response.answer.limitations)


def test_percentage_unit_is_in_calculation_payload_and_markdown():
    result = calculate_from_query(CONTEXT)
    margin = next(item for item in result.outputs if item.name == 'gross_margin')
    assert margin.kind == 'percentage' and margin.display_value == '35.00%'
    assert '| Gross Margin | 35.00% |' in calculation_markdown(result)
