"""Reported manufacturing-analysis failures: account access, not safety.

All provider failures below are simulated; no Groq calls are made.
"""
from types import SimpleNamespace as N
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway import service as gateway
from app.domains.model_gateway.agent import AgentLimits
from app.domains.model_gateway.errors import ProviderAccessBlocked, provider_access_failure
from app.domains.model_gateway.providers.groq_adapter import GroqAdapter
from tests.test_agent_loop import ScriptedClient, _call, _registry, _reply, _run
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


class SpendLimitError(Exception):
    body = {"error": {"code": "spend_limit_reached", "message": "private provider account details"}}


def test_only_structured_account_limit_errors_are_classified():
    failure = provider_access_failure(SpendLimitError())
    assert isinstance(failure, ProviderAccessBlocked)
    assert str(failure) == "spend_limit_reached"
    assert "private" not in failure.user_message
    assert provider_access_failure(RuntimeError("spend_limit_reached in user text")) is None
    transient = SpendLimitError()
    transient.body = {"error": {"code": "rate_limit_exceeded"}}
    assert provider_access_failure(transient) is None


async def test_standard_adapter_propagates_account_block_instead_of_error_text():
    adapter = GroqAdapter.__new__(GroqAdapter)
    adapter.client = object()
    adapter._create_with_tool_recovery = AsyncMock(side_effect=SpendLimitError())
    with pytest.raises(ProviderAccessBlocked):
        await adapter.complete("Explain gross profit")
    adapter._create_with_tool_recovery.assert_awaited_once()


async def test_fast_model_does_not_retry_main_model_for_an_account_block(monkeypatch):
    complete = AsyncMock(side_effect=ProviderAccessBlocked())
    monkeypatch.setattr(gateway, "_select_adapter", lambda: GroqAdapter.__new__(GroqAdapter))
    monkeypatch.setattr(gateway, "_try_complete", complete)
    with pytest.raises(ProviderAccessBlocked):
        await gateway._complete_with_fallback("Explain gross profit", model="fast-model")
    complete.assert_awaited_once()


async def test_grounded_wrapper_retains_typed_account_failure(monkeypatch):
    complete = AsyncMock(side_effect=ProviderAccessBlocked())
    monkeypatch.setattr(gateway, "_complete_with_fallback", complete)
    with pytest.raises(ProviderAccessBlocked):
        await gateway.run_grounded_completion("Explain gross profit")


async def test_agent_does_not_try_another_prompt_after_account_block():
    create = AsyncMock(side_effect=SpendLimitError())
    client = N(chat=N(completions=N(create=create)))
    with pytest.raises(ProviderAccessBlocked):
        await _run(client, _registry([]))
    create.assert_awaited_once()


async def test_forced_final_block_does_not_start_no_tools_recovery():
    class Client(ScriptedClient):
        async def _create(self, **kwargs):
            if len(self.requests) == 1:
                self.requests.append(kwargs)
                raise SpendLimitError()
            return await super()._create(**kwargs)
    client = Client([_reply(tool_calls=[_call("lookup", {"key": "margin"})])])
    with pytest.raises(ProviderAccessBlocked):
        await _run(client, _registry([]), limits=AgentLimits(max_steps=1))
    assert len(client.requests) == 2


async def test_reported_manufacturing_question_reports_account_block_without_fallback(pipeline, monkeypatch):
    from app.orchestration import service
    standard = AsyncMock()
    monkeypatch.setattr(service.model_gateway_service, "run_test_prompt", standard)
    pipeline.agent.side_effect = ProviderAccessBlocked()
    query = (
        "I manage a small manufacturing business. All amounts are GBP. Current year: gross sales £1,250,000, "
        "sales returns £35,000, cost of goods sold £710,000, salaries £165,000, rent £48,000, utilities £32,000, "
        "marketing £41,000, depreciation £28,000, interest £14,000. Previous year: net sales £1,100,000, "
        "cost of goods sold £660,000, operating expenses £285,000. Prepare a table of net sales, gross profit, "
        "gross margin, operating expenses, operating profit, operating margin and profit before tax. "
        "Compare gross profit and operating profit in amounts and percentages. Show formulas. "
        "Do not invent causes. Ignore corporation tax. Finish with three practical management questions."
    )
    response, _ = await pipeline.ask(query)
    assert response.answer is None
    assert response.next_action.type == "provider_access_blocked"
    assert "spending limit" in response.next_action.message
    assert "administrator" in response.next_action.message.lower()
    assert "private provider" not in response.next_action.message
    pipeline.agent.assert_awaited_once()
    standard.assert_not_awaited()
    pipeline.rewrite.assert_not_awaited()
    assert service.audit_agent_completed.await_args.kwargs["fell_back"] is False
    assert service.audit_composition_failed.await_args.kwargs["error"] == "spend_limit_reached"


async def test_account_block_is_a_failed_workflow_not_a_released_answer(monkeypatch):
    from app.orchestration import router
    result = N(query_id="query-test", outcome="refused", route="REFUSAL", safety=None, answer=None,
               next_action=N(type="provider_access_blocked"))
    record = AsyncMock(return_value=None)
    monkeypatch.setattr(router, "ask_kriton", AsyncMock(return_value=result))
    monkeypatch.setattr(router, "record_event_async", record)
    monkeypatch.setattr(router, "commit_audit_batch", AsyncMock())
    await router._run_with_deadline(db=AsyncMock(), tenant_id="tenant-test", idempotency_key=None)
    events = {c.kwargs["event_name"]: c.kwargs["payload"] for c in record.await_args_list}
    assert events["workflow_completed"]["final_state"] == "failed"
    assert events["answer_receipt"]["workflow_final_state"] == "failed"


async def test_prompt_studio_reports_account_block_as_service_unavailable(monkeypatch):
    from fastapi import HTTPException
    from app.domains.model_gateway import router
    monkeypatch.setattr(router, "run_test_prompt", AsyncMock(side_effect=ProviderAccessBlocked()))
    with pytest.raises(HTTPException) as exc:
        await router.post_test_run(payload=N(prompt_id="test", input_text="test"), db=AsyncMock(),
                                   actor=N(id="user", tenant_id="tenant"))
    assert exc.value.status_code == 503
    assert exc.value.detail == ProviderAccessBlocked.user_message
