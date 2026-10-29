"""Conversation-level regressions from the user's second acceptance run."""
import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.conversation_resolver import asks_something, resolve_conversation
from app.orchestration.schemas import ConversationMessage as Message
from app.orchestration.supplied_context import missing_in_supplied_context
from app.orchestration.verification_service import verification_breakdown, operational_guidance_claims
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


CLAIMS = ('Check each claim separately and cite authoritative evidence: '
          'Persistent subsidiary losses can attract transfer-pricing scrutiny. '
          'Legal ownership alone always entitles an entity to all intellectual-property returns. '
          'Large royalty payments automatically prove tax avoidance.')
IFRS = ('Compare inventories, revenue recognition, leases, and provisions under IFRS. '
        'Use a table showing purpose, applicable standard, key accounting requirements, '
        'and optional supporting-document suggestions. Cite authoritative sources and identify evidence gaps.')
SCENARIO = ('Our group has recurring losses in one subsidiary, substantial intercompany royalties, '
            'and limited local staff. Explain which facts warrant transfer-pricing investigation '
            'and which conclusions cannot be drawn from those facts alone. Cite authoritative evidence.')
CALCULATION = ('Revenue is £800,000 and operating costs are £920,000. Calculate operating profit or loss '
               'and operating margin using only these figures. Then explain whether this result alone '
               'establishes a transfer-pricing problem. Cite evidence for the tax discussion and keep it '
               'separate from the calculations.')


def resolve(query, history):
    return resolve_conversation(query, history, legacy_follow_up=service._looks_like_contextual_follow_up,
                                standalone=service._standalone_with_figures)


@pytest.mark.parametrize('verb', ['Check', 'Verify', 'Review', 'Validate'])
def test_claim_review_is_a_request_not_an_unfinished_scenario(verb):
    assert asks_something(CLAIMS.replace('Check', verb, 1))
    assert not resolve(IFRS, [Message(role='user', content=CLAIMS.replace('Check', verb, 1))]).follows_up


def test_independent_research_sequence_does_not_accumulate_previous_tasks():
    history = []
    for query in (CLAIMS, IFRS, SCENARIO, CALCULATION):
        resolution = resolve(query, history)
        assert not resolution.follows_up, resolution.summary()
        assert resolution.history() == []
        history += [Message(role='user', content=query), Message(role='assistant', content='Previous task output.')]


def test_local_reference_does_not_match_an_earlier_modifier():
    assert not resolve(SCENARIO, [Message(role='user', content=CLAIMS)]).follows_up
    # A genuine reference to a previously supplied scenario still works.
    assert resolve('Explain the tax implications of this acquisition.', [Message(
        role='user', content='Apex Corp acquired SubCorp for $900,000; net assets were $750,000.')]).follows_up


def test_current_figures_satisfy_the_request_even_when_prior_answer_has_none():
    assert missing_in_supplied_context(CALCULATION, ['Transfer-Pricing Documentation Requirements']) is None


def test_source_count_without_binding_cannot_produce_a_verified_badge():
    status = verification_breakdown(completeness='complete', citations=4, limitations=[], source_binding=False)
    assert status.sources == 'unsupported' and status.overall == 'not_verified'
    supported = verification_breakdown(completeness='complete', citations=1, limitations=[], source_binding=True)
    assert supported.sources == 'verified'


@pytest.mark.parametrize('heading', [
    '### General Operational Guidance (practical steps – not source-verified)',
    '**General Operational Guidance (practical steps – not source-verified)**',
    '### Optional Process Suggestions (general operational guidance)',
    '### Optional supporting-document suggestions',
])
def test_optional_guidance_heading_variations_preserve_actions_but_not_rules(heading):
    answer = (heading + '\nCollect contracts and supporting schedules.\n'
              'Recognise a provision for every expected expense.\n'
              '### Accounting requirements\nMaintain records for seven years.\n')
    kept = operational_guidance_claims(answer, 'Suggest documentation and distinguish requirements.')
    assert kept == ['Collect contracts and supporting schedules.']


async def test_pipeline_keeps_an_independent_calculation_and_drops_prior_checklist(pipeline):
    pipeline.answers(AgentOutcome(text=(
        'Operating loss = £800,000 − £920,000 = −£120,000. '
        'Operating margin = −£120,000 ÷ £800,000 × 100 = −15%. '
        'The retrieved evidence does not establish the requested transfer-pricing conclusion.')))
    response, _ = await pipeline.ask(CALCULATION, history=[
        Message(role='user', content='Prepare a multinational tax-audit readiness checklist.'),
        Message(role='assistant', content='Transfer-Pricing Documentation Requirements: compile documents.')])
    assert response.outcome != 'clarification_required'
    assert response.answer is not None
    assert '120,000' in response.answer.text and '15%' in response.answer.text
    prompt = pipeline.agent.await_args.args[0]
    assert 'Transfer-Pricing Documentation Requirements' not in prompt


async def test_pipeline_does_not_send_the_previous_ifrs_answer_to_tax_research(pipeline):
    pipeline.answers(AgentOutcome(text='The retrieved evidence does not establish the requested transfer-pricing answer.'))
    await pipeline.ask(SCENARIO, history=[Message(role='user', content=IFRS), Message(
        role='assistant', content='PREVIOUS_IFRS_COMPARISON: inventories, revenue, leases and provisions.')])
    assert 'PREVIOUS_IFRS_COMPARISON' not in pipeline.agent.await_args.args[0]
