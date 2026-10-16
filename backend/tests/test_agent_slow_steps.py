"""A slow model step or an unresponsive tool ends the agent with an answer
from the evidence already gathered, inside its budget — not an exception
that discards that evidence (504 after 120.5 s, idem-1792040729549-q19ym9)."""
import asyncio
import time

from pydantic import BaseModel

from app.domains.model_gateway import agent as agent_module
from app.domains.model_gateway.agent import AgentLimits, run_agent
from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec
from app.orchestration.websearch import WebSource
from tests.test_agent_loop import ScriptedClient, _call, _registry, _reply


class _HangsOnCall(ScriptedClient):
    """Replies in order, but the call numbered `hang_on` never answers."""

    def __init__(self, replies, hang_on: int):
        super().__init__(replies)
        self.hang_on, self.calls = hang_on, 0

    async def _create(self, **kwargs):
        self.calls += 1
        if self.calls == self.hang_on:
            self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
            await asyncio.sleep(30)
        return await super()._create(**kwargs)


async def test_a_slow_model_step_answers_from_gathered_evidence(monkeypatch):
    monkeypatch.setattr(agent_module, "_FINAL_ANSWER_RESERVE_SECONDS", 1.0)
    client = _HangsOnCall([_reply(tool_calls=[_call("lookup", {"key": "vat"})]),
                           _reply("Answer from the gathered evidence [REF-1].")], hang_on=2)
    started = time.monotonic()
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt="q", registry=_registry([]),
                              granted_permissions=frozenset(), limits=AgentLimits(max_seconds=2.5))
    assert time.monotonic() - started < 4.0                       # bounded by the budget
    assert outcome.stop_reason == "time_budget"
    assert outcome.text == "Answer from the gathered evidence [REF-1]."
    assert [r.tool for r in outcome.tool_calls] == ["lookup"] and outcome.sources   # evidence kept
    assert client.requests[-1]["tool_choice"] == "none"           # the final turn calls no tools


async def test_an_unresponsive_tool_is_cut_off_and_the_run_continues():
    class _Args(BaseModel):
        key: str

    async def never_returns(args):
        await asyncio.sleep(30)

    async def quick(args):
        return ToolResult(ok=True, content="ok", sources=(WebSource(title="s", url="https://e.com", snippet="ok"),))

    registry = ToolRegistry()
    registry.register(ToolSpec(name="slow", version="1.0", description="Slow.", args_model=_Args, handler=never_returns,
                               data_source="test", risk_level="low", timeout_seconds=0.3))
    registry.register(ToolSpec(name="fast", version="1.0", description="Fast.", args_model=_Args, handler=quick,
                               data_source="test", risk_level="low", timeout_seconds=1.0))
    client = ScriptedClient([_reply(tool_calls=[_call("slow", {"key": "a"})]),
                             _reply(tool_calls=[_call("fast", {"key": "b"}, "c2")]),
                             _reply("Done [REF-1].")])
    started = time.monotonic()
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt="q", registry=registry,
                              granted_permissions=frozenset())
    assert time.monotonic() - started < 3.0
    assert [(r.tool, r.ok) for r in outcome.tool_calls] == [("slow", False), ("fast", True)]
    assert outcome.text == "Done [REF-1]."


async def test_clean_up_after_a_failure_cannot_hold_the_response(monkeypatch):
    from app.orchestration import router

    class _StuckSession:
        async def rollback(self):
            await asyncio.sleep(30)          # a broken connection reconnecting

    monkeypatch.setattr(router, "CLEANUP_SECONDS", 0.2)
    started = time.monotonic()
    await router._abandon_after_failure(_StuckSession(), "idem-x", "tenant")
    assert time.monotonic() - started < 1.0
