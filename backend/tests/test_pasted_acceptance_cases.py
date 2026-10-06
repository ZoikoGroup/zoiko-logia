from decimal import Decimal
import pytest
from app.orchestration.input_requirements import expense_followup_query, missing_tax_inputs, needs_invoice_attachment
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.schemas import ConversationMessage
from app.orchestration.websearch import evidence_search_queries
from app.orchestration.verification_service import verify_for_release


def test_profit_and_expense_followup_are_deterministic():
    original = 'Revenue is ₹250,000 and expenses are ₹160,000. Calculate profit and profit margin.'
    first = calculate_from_query(original)
    assert first.status == 'success'
    assert [value.value for value in first.outputs] == [Decimal('90000'), Decimal('36')]
    followup = expense_followup_query('Increase those expenses by 10%, keep revenue unchanged, and recalculate.',
        [ConversationMessage(role='user', content=original)])
    second = calculate_from_query(followup)
    assert [value.value for value in second.outputs] == [Decimal('74000'), Decimal('29.6')]
    assert all(value.currency == 'INR' for value in second.inputs)


def test_followup_cannot_use_assistant_invented_inputs_or_mixed_currencies():
    query = 'Increase those expenses by 10%, keep revenue unchanged, and recalculate.'
    assert expense_followup_query(query, [ConversationMessage(role='assistant', content='Revenue is 250000 and expenses are 160000.')]) == query
    assert expense_followup_query(query, [ConversationMessage(role='user', content='Revenue is £250000 and expenses are $160000.')]) == query


def test_missing_invoice_and_tax_inputs_are_identified():
    assert needs_invoice_attachment('Extract the subtotal, tax and total. Check whether the arithmetic agrees.')
    assert needs_invoice_attachment('Upload a sample invoice, then ask: Extract the subtotal, tax and total.')
    assert not needs_invoice_attachment('Explain what a tax invoice is.')
    assert missing_tax_inputs('Calculate my company’s tax liability.')
    assert not missing_tax_inputs('Explain how corporate tax liability is calculated.')
    assert not missing_tax_inputs('Calculate tax liability at 20% on taxable profit of 50000.')


def test_registration_and_itc_searches_cover_substantive_rules():
    queries = evidence_search_queries('What are India’s GST registration requirements? Explain exceptions and cite official sources.')
    assert len(queries) == 3
    assert 'thresholds goods services' in queries[1]
    assert 'section 23' in queries[2] and 'section 24' in queries[2]
    queries = evidence_search_queries('Explain input tax credit in simple English, using India GST as the example.')
    assert 'blocked credits' in queries[1]
    assert evidence_search_queries('What is the UK VAT threshold?') == ['What is the UK VAT threshold?']


async def test_honest_evidence_gap_needs_neither_sources_nor_model_verifier(monkeypatch):
    monkeypatch.setenv('CLAIM_VERIFICATION', 'off')
    result = await verify_for_release('The sources provided do not state this.', question='Testland VAT rate?', evidence=[], requires_authority=True)
    assert result.passed
    result = await verify_for_release('The sources provided do not state this. The VAT rate is 25%.', question='Testland VAT rate?', evidence=[], requires_authority=True)
    assert not result.passed


@pytest.mark.parametrize('query, expected_word', [
    ('Calculate my company’s tax liability.', 'jurisdiction'),
    ('Extract the subtotal, tax and total. Check whether the arithmetic agrees.', 'upload'),
])
async def test_missing_input_pipeline_stops_before_web_and_composition(monkeypatch, query, expected_word):
    from unittest.mock import AsyncMock
    from app.orchestration import service
    from app.orchestration.schemas import AskKritonRequest
    for name in dir(service):
        if name.startswith('audit_'):
            monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, '_finalise_and_return', AsyncMock())
    monkeypatch.setattr(service, 'list_authorized_engagements', AsyncMock(return_value=[]))
    search = AsyncMock(side_effect=AssertionError('Missing-input requests must not search'))
    composition = AsyncMock(side_effect=AssertionError('Missing-input requests must not generate an answer'))
    monkeypatch.setattr(service, 'web_search_each', search)
    monkeypatch.setattr(service.model_gateway_service, 'run_grounded_completion', composition)
    response = await service.ask_kriton(db=object(), sync_db=object(), actor_id='u', tenant_id='t',
        role='Accountant', request=AskKritonRequest(query=query))
    assert response.outcome == 'clarification_required'
    assert expected_word in response.next_action.message.lower()
    assert response.answer is None
    search.assert_not_awaited()
    composition.assert_not_awaited()


def test_unchanged_threshold_sentence_is_detected_as_incomplete():
    from app.orchestration.input_requirements import gst_answer_gaps
    query = 'What are India’s GST registration requirements?'
    assert gst_answer_gaps(query, 'There has been no change in the turnover threshold.')
    assert not gst_answer_gaps(query, 'The sources provided do not establish the applicable goods/services turnover thresholds.')
    assert not gst_answer_gaps(query, 'The threshold is ₹40,00,000 for the specified eligible suppliers. [REF-1]')
