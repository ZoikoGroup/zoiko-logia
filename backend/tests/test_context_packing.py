"""Complete composition sizing with scripted transport only."""
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.agent_budget import request_prompt_estimate
from app.domains.model_gateway.errors import ProviderRequestTooLarge
from app.domains.model_gateway.providers.groq_adapter import KRITON_COMPOSITION_SYSTEM_PROMPT, CHART_TOOL_SCHEMA
from app.orchestration.context_packing import ContextSection, governed_context, pack_context
from app.orchestration.conversation import conversation_prompt
from app.orchestration.schemas import ConversationMessage
from app.orchestration.websearch import WebSource, build_web_grounded_prompt
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

QUESTION = ('What is the current UK VAT registration threshold? Give the effective date and an official source. '
            'If you cannot verify the current rule, say so clearly and explain what I should check.')


def estimate(prompt):
    return request_prompt_estimate([
        {'role': 'system', 'content': KRITON_COMPOSITION_SYSTEM_PROMPT},
        {'role': 'user', 'content': prompt},
    ], [CHART_TOOL_SCHEMA])


def test_complete_web_registered_history_and_instructions_fit_together():
    sources = [WebSource(title=f'Official {i}', url=f'https://www.gov.uk/example-{i}',
                         snippet='Registration guidance and relevant dates. ' * 100) for i in range(3)]
    passages = [(f'passage-{i}', f'Section {i}', 'Registered VAT threshold and effective date guidance. ' * 40)
                for i in range(8)]
    refs = {pid: f'REF-{i+4}' for i, (pid, _, _) in enumerate(passages)}
    history = [ConversationMessage(role='user', content='Explain revenue and profit.')]
    history += [ConversationMessage(role='assistant', content=f'Answer {i}. ' + 'Educational explanation. ' * 40)
                for i in range(6)]
    prompt, sections = '', []
    renderers = [
        lambda factor: build_web_grounded_prompt(QUESTION, sources, compact=True,
                                                 context_char_budget=int(6000 * factor)),
        lambda factor: governed_context(QUESTION, passages, refs, int(16000 * factor)),
        lambda factor: conversation_prompt(history, max_chars=int(6000 * factor)),
    ]
    fixed = '\nAll requested parts must be addressed with verified sources. ' * 20
    for render in renderers:
        start = len(prompt)
        prompt += render(1.0)
        sections.append(ContextSection(start, len(prompt), render))
        prompt += fixed
    packed, before, after = pack_context(prompt, sections, estimate, 8000 - 1280)
    assert before > 8000 and after <= 6720
    assert packed.count(QUESTION) == 1
    assert packed.count(fixed) == 3
    assert all(f'[REF-{i}]' in packed for i in range(1, 12))
    assert 'shortened' in packed
    assert all(content in text for content, text in [('passage-7', packed), ('official information to check', packed)])


def test_fixed_user_input_is_never_cut_even_when_impossible_to_fit():
    prompt = 'User financial inputs must remain exact. ' * 2000
    packed, before, after = pack_context(prompt, [], estimate, 200)
    assert packed == prompt and before == after and after > 200


def test_packing_leaves_small_prompt_unchanged_and_rejects_overlapping_sections():
    prompt = 'A small prompt.'
    assert pack_context(prompt, [], len, 100) == (prompt, len(prompt), len(prompt))
    with pytest.raises(ValueError, match='boundaries'):
        pack_context(prompt, [ContextSection(0, 10, lambda _: ''), ContextSection(5, 12, lambda _: '')], len, 1)


async def test_production_standard_path_fits_complete_assembled_context(pipeline, monkeypatch):
    from app.orchestration import service
    gateway = service.model_gateway_service
    monkeypatch.setattr(gateway, 'agent_mode_active', lambda: False)
    sources = [WebSource(title=f'Official {i}', url=f'https://www.gov.uk/example-{i}',
                         snippet='Registration guidance and dates. ' * 100) for i in range(3)]
    monkeypatch.setattr(service, 'web_search_each', AsyncMock(return_value=sources))
    # Fixed context simulates additional instructions and verified facts added
    # after sources/history. The whole assembled prompt must be measured.
    fixed = '\nVerified extra context. ' * 350
    monkeypatch.setattr(service, '_verified_document_figures_context', AsyncMock(return_value=fixed))
    captured = []

    async def complete(db, prompt_id, prompt, *args, **kwargs):
        captured.append(prompt)
        raise ProviderRequestTooLarge()  # stop before release; never call a provider

    monkeypatch.setattr(gateway, 'run_test_prompt', complete)
    history = [ConversationMessage(role='user', content='Explain cash flow.')]
    history += [ConversationMessage(role='assistant', content=f'Answer {i}. ' + 'Earlier explanation. ' * 45)
                for i in range(6)]
    await pipeline.ask(QUESTION, history=history)
    assert len(captured) == 1
    assert QUESTION in captured[0] and fixed in captured[0]
    assert estimate(captured[0]) <= 6720
