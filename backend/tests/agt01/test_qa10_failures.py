"""QA 10 — tool timeout, provider outage, audit outage: safe state and durable event."""
import asyncio
import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from agt01_support import call, reply, run
from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec
from app.orchestration import router


class _Args(BaseModel):
    key: str


async def test_a_tool_timeout_is_retried_then_reported_not_guessed():
    attempts = []

    async def slow(args):
        attempts.append(1)
        await asyncio.sleep(1)
        return ToolResult(ok=True, content="late")

    registry = ToolRegistry()
    registry.register(ToolSpec(name="feed", version="1.0", description="d", args_model=_Args, handler=slow,
                               data_source="t", risk_level="low", timeout_seconds=0.05, max_retries=1))
    outcome, trace, _ = await run([reply(calls=[call("c1", "feed", {"key": "x"})]), reply("The data is unavailable.")],
                                  question="Get the feed.", registry=registry)
    assert len(attempts) == 2 and trace[0].error_code == "timeout"
    assert outcome.text == "The data is unavailable."


async def test_a_provider_outage_raises_rather_than_inventing_an_answer():
    class Down:
        chat = SimpleNamespace(completions=SimpleNamespace(create=None))

    async def fail(**_):
        raise ConnectionError("provider unreachable")
    Down.chat.completions.create = fail
    from app.domains.model_gateway.agent import run_agent
    from app.domains.model_gateway.tool_registry import build_default_registry
    with pytest.raises(ConnectionError):
        await run_agent(Down(), model="m", system_prompt="", user_prompt="q", registry=build_default_registry(),
                        granted_permissions=frozenset())


async def test_an_audit_outage_withholds_the_answer(monkeypatch, caplog):
    async def answered(**_):
        return SimpleNamespace(query_id="q-1", next_action=None, model_dump=lambda **__: {})

    async def ledger_down(db, token):
        raise ConnectionError("audit database unreachable")

    async def record(*_, **__):
        return None

    async def done():
        return None

    monkeypatch.setattr(router, "ask_kriton", answered)
    monkeypatch.setattr(router, "commit_audit_batch", ledger_down)
    monkeypatch.setattr(router, "record_event_async", record)
    with caplog.at_level(logging.CRITICAL), pytest.raises(HTTPException) as raised:
        await router._run_with_deadline(db=SimpleNamespace(rollback=done), actor_id="u", tenant_id="t", request=None)
    assert raised.value.status_code == 503 and "withheld" in raised.value.detail
    assert "AUDIT_COMMIT_FAILED" in caplog.text
