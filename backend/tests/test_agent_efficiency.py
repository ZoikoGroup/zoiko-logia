"""Offline token-efficiency checks: scripted replies, no model or network."""
from types import SimpleNamespace as N

import pytest

from app.domains.model_gateway.agent import AgentLimits
from app.domains.model_gateway.agent_budget import GenerationBudget, GenerationBudgetExceeded, prompt_allowance
from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec
from tests.test_agent_loop import ScriptedClient, _LookupArgs, _call, _registry, _reply, _run


async def test_oversized_prompt_is_rejected_before_any_request():
    client = ScriptedClient([])
    budget = GenerationBudget(max_total_tokens=10)
    with pytest.raises(GenerationBudgetExceeded, match="token_budget"):
        await budget.create(client, seconds=1, model="m", messages=[{"role": "user", "content": "Explain accruals"}])
    assert not client.requests and budget.tokens_used == budget.calls == 0


async def test_output_limit_is_clamped_to_the_remaining_run_budget():
    messages = [{"role": "user", "content": "Explain accruals"}]
    budget = GenerationBudget(max_total_tokens=prompt_allowance(messages) + 73, max_completion_tokens=4096)
    client = ScriptedClient([_reply("Income is recorded when earned.")])
    await budget.create(client, seconds=1, model="m", messages=messages)
    assert client.requests[0]["max_completion_tokens"] == 73
    assert budget.tokens_used == 110 and budget.estimated_tokens == 0


@pytest.mark.parametrize("usage", [None, N(total_tokens=0)])
async def test_missing_usage_cannot_allow_free_repeated_generations(usage):
    reply = _reply("Income is recorded when earned.")
    reply.usage = usage
    messages = [{"role": "user", "content": "Explain accruals"}]
    limit = prompt_allowance(messages) + 100
    budget = GenerationBudget(max_total_tokens=limit)
    client = ScriptedClient([reply])
    await budget.create(client, seconds=1, model="m", messages=messages)
    with pytest.raises(GenerationBudgetExceeded):
        await budget.create(client, seconds=1, model="m", messages=messages)
    assert len(client.requests) == 1
    assert budget.tokens_used == budget.estimated_tokens == limit


async def test_failed_generation_keeps_its_reservation_before_retry():
    async def fail(**kwargs):
        raise TimeoutError("model timed out")
    client = N(chat=N(completions=N(create=fail)))
    messages = [{"role": "user", "content": "Explain accruals"}]
    budget = GenerationBudget(max_total_tokens=prompt_allowance(messages) + 100)
    with pytest.raises(TimeoutError):
        await budget.create(client, seconds=1, model="m", messages=messages)
    with pytest.raises(GenerationBudgetExceeded):
        await budget.create(client, seconds=1, model="m", messages=messages)
    assert budget.calls == 1 and budget.tokens_used == budget.max_total_tokens


async def test_cost_allowance_is_checked_before_sending_the_prompt():
    budget = GenerationBudget(max_total_tokens=100_000, max_cost_usd=0.00001, price_per_million_tokens=1)
    client = ScriptedClient([])
    with pytest.raises(GenerationBudgetExceeded, match="cost_budget"):
        await budget.create(client, seconds=1, model="m", messages=[{"role": "user", "content": "Explain accruals"}])
    assert not client.requests


async def test_forced_final_and_recovery_share_usage_and_output_limits():
    def response(text="", calls=None, tokens=110):
        reply = _reply(text, tool_calls=calls)
        reply.usage = N(total_tokens=tokens)
        return reply
    client = ScriptedClient([
        response(calls=[_call("lookup", {"key": "accruals"})], tokens=120),
        response(tokens=80),  # Empty forced-final reply triggers recovery.
        response("Income is recorded when earned.", tokens=50),
    ])
    outcome = await _run(client, _registry([]), limits=AgentLimits(max_steps=1, max_completion_tokens=256))
    assert outcome.text == "Income is recorded when earned."
    assert outcome.tokens_used == 250 and outcome.model_calls == 3 and outcome.estimated_tokens == 0
    assert all(0 < request["max_completion_tokens"] <= 256 for request in client.requests)
    assert "tools" not in client.requests[-1]


async def test_budget_exhaustion_returns_verified_work_without_another_model_call():
    async def calculate(args):
        return ToolResult(ok=True, content="100 + 10 = 110", receipt={
            "calculation_id": "calc-1", "expression": "100+10", "result": "110",
        })
    registry = ToolRegistry()
    registry.register(ToolSpec(name="calculate", version="1", description="Calculate", args_model=_LookupArgs,
                               handler=calculate, data_source="test", risk_level="low", timeout_seconds=1))
    reply = _reply(tool_calls=[_call("calculate", {"key": "sum"})])
    reply.usage = N(total_tokens=19_900)
    client = ScriptedClient([reply])
    outcome = await _run(client, registry, question="Add 100 and 10.", limits=AgentLimits(max_total_tokens=20_000))
    assert len(client.requests) == 1 and outcome.model_calls == 1
    assert outcome.stop_reason == "token_budget" and outcome.incomplete_reason
    assert "100+10 = 110" in outcome.text and outcome.tokens_used == 19_900


async def test_duplicate_result_is_not_copied_back_into_context():
    client = ScriptedClient([
        _reply(tool_calls=[_call("lookup", {"key": "accruals"}, "a")]),
        _reply(tool_calls=[_call("lookup", {"key": "accruals"}, "b")]),
        _reply("Income is recorded when earned."),
    ])
    executions = []
    await _run(client, _registry(executions))
    tool_messages = [m["content"] for m in client.requests[-1]["messages"] if m["role"] == "tool"]
    assert executions == ["accruals"]
    assert sum("value for accruals" in text for text in tool_messages) == 1
    assert "earlier tool result" in tool_messages[-1]


async def test_gateway_disables_hidden_sdk_retries_and_passes_the_output_limit(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from app.domains.model_gateway import service
    from app.domains.model_gateway.agent import AgentOutcome

    bounded_client = object()
    client = N(with_options=Mock(return_value=bounded_client))
    run = AsyncMock(return_value=AgentOutcome(text="Income is recorded when earned."))
    monkeypatch.setattr(service, "GroqAdapter", lambda: N(client=client))
    monkeypatch.setattr(service, "approved_providers", lambda: {"groq"})
    monkeypatch.setattr(service, "run_agent", run)
    await service.run_agentic_completion("Explain accruals", granted_permissions=frozenset())
    client.with_options.assert_called_once_with(max_retries=0)
    assert run.await_args.args[0] is bounded_client
    assert run.await_args.kwargs["limits"].max_completion_tokens == service.get_settings().AGENT_MAX_COMPLETION_TOKENS


async def test_offline_tests_block_groq_before_network_transport():
    import groq

    client = groq.AsyncGroq(api_key="offline-test-placeholder")
    try:
        with pytest.raises(pytest.fail.Exception, match="Live model transport is disabled"):
            await client.chat.completions.create(model="offline-model", messages=[{"role": "user", "content": "test"}])
    finally:
        await client.close()


async def test_output_limited_answer_is_reported_as_incomplete():
    reply = _reply("Accrual accounting records income when earned.")
    reply.choices[0].finish_reason = "length"
    outcome = await _run(ScriptedClient([reply]), _registry([]))
    assert outcome.incomplete_reason == "the model reached its output token limit"
