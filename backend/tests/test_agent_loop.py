"""The governed agent loop (model_gateway/agent.py) against a scripted client."""
import json
from types import SimpleNamespace

from pydantic import BaseModel

from app.domains.model_gateway.agent import AgentLimits, run_agent
from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec, build_default_registry
from app.orchestration.websearch import WebSource


def _call(name: str, args: dict, call_id: str = "c1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _reply(content: str = "", tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


class ScriptedClient:
    """chat.completions.create returns the scripted replies in order and
    records every request (a copy of the messages and the tool_choice)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.replies.pop(0)


class _LookupArgs(BaseModel):
    key: str


def _registry(counter: list[str]) -> ToolRegistry:
    async def lookup(args: _LookupArgs) -> ToolResult:
        counter.append(args.key)
        source = WebSource(title=f"Source {args.key}", url=f"https://example.com/{args.key}", snippet=args.key)
        return ToolResult(ok=True, content=f"value for {args.key}", sources=(source,))

    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="lookup", version="1.0", description="Look up.", args_model=_LookupArgs, handler=lookup,
        data_source="test", risk_level="low", timeout_seconds=1.0,
    ))
    return registry


async def _run(client, registry, limits=AgentLimits(), **hooks):
    return await run_agent(
        client, model="m", system_prompt="sys", user_prompt="question",
        registry=registry, granted_permissions=frozenset(), limits=limits, **hooks,
    )


async def test_answer_without_tools_is_one_step() -> None:
    client = ScriptedClient([_reply("Direct answer.")])
    outcome = await _run(client, _registry([]))
    assert outcome.text == "Direct answer." and outcome.steps == 1
    assert outcome.stop_reason == "final_answer" and outcome.tool_calls == []
    assert client.requests[0]["tool_choice"] == "auto"
    assert {t["function"]["name"] for t in client.requests[0]["tools"]} == {"lookup"}


async def test_tool_result_is_fed_back_and_evidence_collected() -> None:
    executed: list[str] = []
    started: list[str] = []
    done = []

    async def on_start(name):
        started.append(name)

    async def on_done(record):
        done.append(record)

    client = ScriptedClient([_reply(tool_calls=[_call("lookup", {"key": "gdp"})]), _reply("GDP is up.")])
    outcome = await _run(client, _registry(executed), on_tool_start=on_start, on_tool_done=on_done)

    assert outcome.text == "GDP is up." and outcome.steps == 2
    assert executed == ["gdp"] and started == ["lookup"]
    assert [s.url for s in outcome.sources] == ["https://example.com/gdp"]
    assert len(done) == 1 and done[0].ok and done[0].source_count == 1 and len(done[0].arguments_hash) == 32
    tool_message = client.requests[1]["messages"][-1]
    assert tool_message == {"role": "tool", "tool_call_id": "c1", "content": "value for gdp"}


async def test_identical_call_is_never_executed_twice() -> None:
    executed: list[str] = []
    client = ScriptedClient([
        _reply(tool_calls=[_call("lookup", {"key": "a"}, "c1")]),
        # Same arguments with different key order/spacing is still the same call.
        _reply(tool_calls=[SimpleNamespace(id="c2", function=SimpleNamespace(name="lookup", arguments='{ "key" : "a" }'))]),
        _reply("done"),
    ])
    outcome = await _run(client, _registry(executed))
    assert executed == ["a"]
    assert [r.error_code for r in outcome.tool_calls] == [None, "duplicate_call"]
    assert "Already called" in client.requests[2]["messages"][-1]["content"]
    assert len(outcome.sources) == 1


async def test_parallel_calls_in_one_step_run_and_duplicates_within_step_collapse() -> None:
    executed: list[str] = []
    client = ScriptedClient([
        _reply(tool_calls=[
            _call("lookup", {"key": "uk"}, "c1"), _call("lookup", {"key": "us"}, "c2"),
            _call("lookup", {"key": "uk"}, "c3"),
        ]),
        _reply("compared"),
    ])
    outcome = await _run(client, _registry(executed))
    assert sorted(executed) == ["uk", "us"]
    assert [r.error_code for r in outcome.tool_calls] == [None, None, "duplicate_call"]
    # Every proposed call gets its own tool message, in order.
    assert [m["tool_call_id"] for m in client.requests[1]["messages"][-3:]] == ["c1", "c2", "c3"]


async def test_tool_call_budget_is_enforced() -> None:
    executed: list[str] = []
    client = ScriptedClient([
        _reply(tool_calls=[_call("lookup", {"key": "a"}, "c1"), _call("lookup", {"key": "b"}, "c2")]),
        _reply("partial answer"),
    ])
    outcome = await _run(client, _registry(executed), limits=AgentLimits(max_tool_calls=1))
    assert executed == ["a"]
    assert [r.error_code for r in outcome.tool_calls] == [None, "budget_exhausted"]


async def test_step_limit_forces_a_final_answer_with_tools_forbidden() -> None:
    client = ScriptedClient([
        _reply(tool_calls=[_call("lookup", {"key": "a"}, "c1")]),
        _reply(tool_calls=[_call("lookup", {"key": "b"}, "c2")]),
        _reply("best effort answer"),
    ])
    outcome = await _run(client, _registry([]), limits=AgentLimits(max_steps=2))
    assert outcome.stop_reason == "max_steps" and outcome.text == "best effort answer"
    assert client.requests[-1]["tool_choice"] == "none"
    assert "Stop calling tools" in client.requests[-1]["messages"][-1]["content"]


async def test_exhausted_time_budget_skips_straight_to_final_answer() -> None:
    client = ScriptedClient([_reply("answer from what was given")])
    outcome = await _run(client, _registry([]), limits=AgentLimits(max_seconds=1.0))
    assert outcome.stop_reason == "time_budget"
    assert client.requests[0]["tool_choice"] == "none"


async def test_unknown_tool_is_reported_back_not_raised() -> None:
    client = ScriptedClient([_reply(tool_calls=[_call("delete_ledger", {})]), _reply("cannot do that")])
    outcome = await _run(client, _registry([]))
    assert outcome.tool_calls[0].error_code == "unknown_tool"
    assert "Unknown tool" in client.requests[1]["messages"][-1]["content"]


async def test_chart_and_calculation_through_the_real_registry() -> None:
    chart = {"type": "bar", "title": "Revenue", "categories": ["Q1", "Q2"], "series": [{"name": "Rev", "data": [100, 150]}]}
    client = ScriptedClient([
        _reply(tool_calls=[_call("calculate", {"expression": "(150 - 100) / 100 * 100", "label": "Growth %"}, "c1"),
                           _call("render_chart", chart, "c2")]),
        _reply("Revenue grew 50%."),
    ])
    outcome = await _run(client, build_default_registry())
    assert "= 50 " in client.requests[1]["messages"][-2]["content"]
    assert len(outcome.artifacts) == 1 and outcome.artifacts[0].startswith("```chart\n")
    assert json.loads(outcome.artifacts[0].split("\n")[1])["series"][0]["data"] == [100, 150]


async def test_invalid_chart_is_rejected_without_an_artifact() -> None:
    client = ScriptedClient([
        _reply(tool_calls=[_call("render_chart", {"type": "gauge", "title": "x"})]),
        _reply("Could not chart it."),
    ])
    outcome = await _run(client, build_default_registry())
    assert outcome.artifacts == [] and outcome.tool_calls[0].error_code == "invalid_arguments"


class _ToolUseFailed(Exception):
    """Shape of Groq's 400 when it rejects a proposed call against the schema."""

    def __init__(self):
        super().__init__("tool_use_failed")
        self.body = {"error": {
            "code": "tool_use_failed",
            "message": "parameters for tool lookup did not match schema: /key: expected string",
            "failed_generation": '{"name": "lookup", "arguments": {"key": [1, 2]}}',
        }}


async def test_provider_rejected_tool_call_is_corrected_not_fatal() -> None:
    executed: list[str] = []
    replies = [_ToolUseFailed(), _reply(tool_calls=[_call("lookup", {"key": "fixed"})]), _reply("ok")]

    class RejectingClient(ScriptedClient):
        async def _create(self, **kwargs):
            self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    client = RejectingClient(replies)
    outcome = await _run(client, _registry(executed))
    assert outcome.text == "ok" and executed == ["fixed"]
    assert outcome.tool_calls[0].tool == "lookup" and outcome.tool_calls[0].error_code == "invalid_arguments"
    assert "rejected as invalid" in client.requests[1]["messages"][-1]["content"]


async def test_other_provider_errors_still_raise_for_fallback() -> None:
    class Boom(ScriptedClient):
        async def _create(self, **kwargs):
            raise RuntimeError("503 from provider")

    try:
        await _run(Boom([]), _registry([]))
    except RuntimeError as exc:
        assert "503" in str(exc)
    else:
        raise AssertionError("provider outage must propagate so orchestration falls back")
