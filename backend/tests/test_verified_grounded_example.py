from copy import deepcopy

from app.domains.model_gateway.errors import ProviderRateLimited
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.calculations.illustrations import verified_example
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

QUESTION = ('Explain this comparison with a grounded example. Context: This request has three independent parts. '
            'First, calculate gross profit and gross margin from revenue of £800,000 and cost of goods sold of £520,000. '
            'Second, retrieve the latest available USD/GBP reference exchange rate and state its source and observation date. '
            'Third, retrieve the latest available share price for the fictional company Kriton Example Manufacturing '
            'with ticker ZZZFICTIONAL123. Complete every part that is possible.')


def test_example_uses_verified_figures_and_does_not_invent_market_data():
    result = calculate_from_query(QUESTION)
    text = verified_example(QUESTION, result)
    assert '£800,000' in text and '£520,000' in text and '£280,000' in text and '35.00%' in text
    assert 'before other expenses' in text
    assert 'cannot be inferred' in text
    assert 'observation date:' not in text.lower()


def test_unverified_or_unrequested_example_is_not_generated():
    result = calculate_from_query(QUESTION)
    assert not verified_example('Calculate gross profit.', result)
    unverified = deepcopy(result)
    unverified.verification_status = 'not_run'
    assert not verified_example(QUESTION, unverified)


async def test_rate_limit_preserves_a_grounded_explanation_and_partial_status(pipeline):
    pipeline.agent.side_effect = ProviderRateLimited()
    response, _ = await pipeline.ask(QUESTION)
    assert response.answer.completeness == 'partial'
    assert 'Grounded example using your figures' in response.answer.text
    assert '£280,000' in response.answer.text and '35.00%' in response.answer.text
    assert any('usage allowance' in note for note in response.answer.limitations)
