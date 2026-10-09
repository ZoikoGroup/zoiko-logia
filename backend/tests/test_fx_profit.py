from datetime import date
from types import SimpleNamespace
from app.domains.calculations.schemas import LiveObservation
from app.orchestration.websearch import WebSource
from app.orchestration.fx_profit import fresh_fx_sources, grounded_fx_profit, latest_fx_requested
from app.orchestration.calculation_service import validate_answer_calculations
QUESTION = ('Using the latest available USD/INR reference rate, convert US$4,000 into rupees. '
            'Revenue is ₹500,000. Calculate profit and profit margin.')
TODAY = date(2026, 10, 8)

def source(period='2026-10-07', value='90', pair='USD/INR'):
    return WebSource(title='Dated FX rate', url='https://api.example/latest', snippet='Latest rate',
                     provider='Test provider', freshness='daily', observation=LiveObservation(
                         observation_id='obs', indicator=f'{pair} exchange rate', value=value,
                         unit='INR per USD', period=period, provider='Test provider',
                         source_url='https://api.example/latest', freshness='daily'))

def test_latest_requires_dated_recent_matching_observation():
    assert latest_fx_requested(QUESTION)
    assert not latest_fx_requested('Use the USD/INR rate on 31 December 2024.')
    assert fresh_fx_sources(QUESTION, [source()], TODAY)
    for bad in [source('2024-12-31'), source('2026-10-09'), source(value='NaN'), source(value='0'),
                source(pair='EUR/INR'), WebSource(title='Filing', url='https://example.com', snippet='85.55 on 2024-12-31')]:
        assert not fresh_fx_sources(QUESTION, [bad], TODAY)
        assert grounded_fx_profit(QUESTION, [bad], [], TODAY) is None

def test_source_bound_profit_preserves_calculation_and_explains_date_gap():
    evidence = source()
    result = grounded_fx_profit(QUESTION, [evidence], [SimpleNamespace(url=evidence.url, ref_id='REF-6')], TODAY)
    assert '2026-10-07' in result and '[REF-6]' in result
    assert '₹360,000.00' in result and '₹140,000.00' in result and '28.00%' in result
    assert 'earlier than the request date' in result and 'did not return a reason' in result
    assert not validate_answer_calculations(result)

def test_uncited_observation_cannot_build_answer():
    assert grounded_fx_profit(QUESTION, [source()], [], TODAY) is None
