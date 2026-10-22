"""Whole-request execution controls, using scripted providers only."""
import asyncio
from types import SimpleNamespace as N
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway import auxiliary, service as gateway
from app.domains.model_gateway.agent_budget import GenerationBudget, GenerationBudgetExceeded
from app.domains.model_gateway.errors import ProviderAccessBlocked, ProviderRateLimited, RequestBudgetExhausted
from app.domains.model_gateway.errors import ProviderResponseIncomplete
from app.domains.model_gateway.execution import current_budget, request_execution_scope
from app.domains.model_gateway.providers.groq_adapter import GroqAdapter
from app.orchestration.service import parts_instruction
from tests.test_agent_loop import ScriptedClient, _registry, _reply, _run
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


@pytest.fixture
def limits(monkeypatch):
    from app.core import config
    settings = N(AGENT_MAX_TOKENS=64000, AGENT_MAX_COMPLETION_TOKENS=4096,
                 AGENT_MAX_REQUEST_TOKENS=8000, AGENT_MAX_COST_USD=0,
                 MODEL_PRICE_PER_MILLION_TOKENS=0, MODEL_REQUEST_MAX_CALLS=2,
                 ASK_KRITON_TIMEOUT_SECONDS=105)
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    return settings


async def test_standard_agent_and_auxiliary_share_one_attempt_allowance(limits, monkeypatch):
    client = ScriptedClient([_reply('Standard answer.'), _reply('Agent answer.')])
    adapter = GroqAdapter.__new__(GroqAdapter)
    adapter.client = client
    monkeypatch.setenv('GROQ_API_KEY', 'fake-offline-key')
    monkeypatch.setattr(auxiliary, 'AsyncGroq', lambda **kwargs: client)

    @request_execution_scope
    async def request():
        budget = current_budget()
        assert await adapter.complete('Explain gross profit.') == 'Standard answer.'
        outcome = await _run(client, _registry([]))
        assert outcome.text == 'Agent answer.'
        with pytest.raises(RequestBudgetExhausted):
            await auxiliary.complete_auxiliary(purpose='risk_classification', model='m', system='s', user='u')
        assert budget.calls == 2 and budget.tokens_used == 220
        return budget

    budget = await request()
    assert len(client.requests) == 2
    assert current_budget() is None and budget.closed


async def test_concurrent_requests_have_isolated_budgets_and_nested_calls_share(limits):
    @request_execution_scope
    async def nested():
        return current_budget()

    @request_execution_scope
    async def request():
        budget = current_budget()
        await asyncio.sleep(0)
        assert await nested() is budget
        return budget

    first, second = await asyncio.gather(request(), request())
    assert first is not second and first.closed and second.closed
    assert current_budget() is None


async def test_cancelled_request_cannot_leave_background_model_work_open(limits):
    started = asyncio.Event()
    budgets = []

    @request_execution_scope
    async def request():
        budgets.append(current_budget())
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(request())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client = ScriptedClient([])
    with pytest.raises(GenerationBudgetExceeded, match='request_closed'):
        await budgets[0].create(client, seconds=1, model='m', messages=[])
    assert not client.requests and current_budget() is None


async def test_expired_request_deadline_prevents_transport():
    budget = GenerationBudget(max_total_tokens=64000, deadline=0)
    client = ScriptedClient([])
    with pytest.raises(TimeoutError):
        await budget.create(client, seconds=10, model='m', messages=[])
    assert not client.requests


@pytest.mark.parametrize('failure', [ProviderRateLimited(), ProviderAccessBlocked()])
async def test_terminal_provider_failure_does_not_trigger_another_transport(failure):
    create = AsyncMock(side_effect=failure)
    client = N(chat=N(completions=N(create=create)))
    budget = GenerationBudget(max_total_tokens=64000)
    for _ in range(2):
        with pytest.raises(type(failure)):
            await budget.create(client, seconds=1, model='m', messages=[])
    create.assert_awaited_once()


async def test_rate_limit_on_one_model_does_not_block_a_separately_allowed_model():
    create = AsyncMock(side_effect=[ProviderRateLimited(), _reply('Other model answer.')])
    client = N(chat=N(completions=N(create=create)))
    budget = GenerationBudget(max_total_tokens=64000)
    with pytest.raises(ProviderRateLimited):
        await budget.create(client, seconds=1, model='first', messages=[])
    await budget.create(client, seconds=1, model='second', messages=[])
    assert create.await_count == 2


async def test_optional_correction_cannot_discard_an_answer_on_budget_exhaustion(limits, monkeypatch):
    adapter = GroqAdapter.__new__(GroqAdapter)
    adapter.client = ScriptedClient([])
    monkeypatch.setattr(gateway, '_select_adapter', lambda: adapter)

    @request_execution_scope
    async def request():
        current_budget().calls = limits.MODEL_REQUEST_MAX_CALLS
        assert await gateway.run_optional_completion('Repair this explanation.') == ''
        assert not adapter.client.requests

    await request()


async def test_provider_failure_is_not_a_policy_refusal(pipeline):
    pipeline.agent.side_effect = ProviderRateLimited()
    result, _ = await pipeline.ask('Compare IFRS 18 and IAS 1 and cite the official requirements.')
    assert result.outcome == 'unavailable' and result.route == 'LLM'
    assert result.next_action.type == 'provider_rate_limited'
    pipeline.rewrite.assert_not_awaited()


@pytest.mark.parametrize('scoped', [False, True])
async def test_truncated_standard_response_is_not_released_or_retried(scoped, limits):
    response = _reply('Gross profit is')
    response.choices[0].finish_reason = 'length'
    adapter = GroqAdapter.__new__(GroqAdapter)
    adapter.client = ScriptedClient([response])

    async def request():
        with pytest.raises(ProviderResponseIncomplete):
            await adapter.complete('Prepare the full statement.')

    await (request_execution_scope(request)() if scoped else request())
    assert len(adapter.client.requests) == 1


async def test_truncated_optional_rewrite_leaves_existing_answer(monkeypatch):
    response = _reply('An unfinished rewrite')
    response.choices[0].finish_reason = 'length'
    adapter = GroqAdapter.__new__(GroqAdapter)
    adapter.client = ScriptedClient([response])
    monkeypatch.setattr(gateway, '_select_adapter', lambda: adapter)
    assert await gateway.run_optional_completion('Improve the existing answer.') == ''
    assert len(adapter.client.requests) == 1


async def test_truncated_response_is_service_failure_not_refusal(pipeline):
    pipeline.agent.side_effect = ProviderResponseIncomplete()
    result, _ = await pipeline.ask('Compare IFRS 18 and IAS 1 and cite the official requirements.')
    assert result.outcome == 'unavailable'
    assert result.next_action.type == 'composition_failed'
    assert 'output limit' in result.next_action.message


def test_explanations_and_authoritative_claims_receive_different_evidence_instructions():
    prompt = parts_instruction([
        {'status': 'needs_evidence', 'needs_evidence': False, 'text': 'Explain the arithmetic.'},
        {'status': 'needs_evidence', 'needs_evidence': True, 'text': 'Find the current legal threshold.'},
    ])
    assert 'ordinary explanation does not require an external citation' in prompt
    assert 'current legal threshold. — answer only from the evidence' in prompt
