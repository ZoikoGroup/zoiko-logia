"""Per-step tool policy (ZL-ENG-AGT-01 §05, §10, App. B2; QA demonstration 6).

The model only proposes a tool call; tool_registry.decide() authorises it
from server-side state before every execution, and the decision is recorded
on the call. Write actions are always refused, and a role revoked during a
run is refused at the next call.
"""
from tests.test_agent_loop import ScriptedClient, _call, _registry, _reply, _run

from app.domains.model_gateway.tool_registry import PolicyDecision, ToolSpec, decide

ALLOWED = dict(role="Admin", active=True, same_tenant=True, role_unchanged=True, permissions=frozenset())


def _spec(**changes) -> ToolSpec:
    registry = _registry([])
    spec = registry.get("lookup")
    return ToolSpec(**{**spec.__dict__, **changes})


def test_decide_fails_closed_on_every_condition():
    spec = _spec()
    assert decide(spec, "lookup", **ALLOWED).allowed
    assert decide(None, "lookup", **ALLOWED).reason_code == "unknown_tool"
    assert decide(spec, "lookup", **{**ALLOWED, "active": False}).reason_code == "user_not_authorised"
    assert decide(spec, "lookup", **{**ALLOWED, "same_tenant": False}).reason_code == "user_not_authorised"
    assert decide(spec, "lookup", **{**ALLOWED, "role_unchanged": False}).reason_code == "role_changed"
    assert decide(_spec(is_write_action=True), "lookup", **ALLOWED).reason_code == "write_action_blocked"
    assert decide(_spec(allowed_roles=frozenset({"SME Reviewer"})), "lookup", **ALLOWED).reason_code == "role_not_allowed"
    assert decide(_spec(required_permission="source.manage"), "lookup", **ALLOWED).reason_code == "permission_denied"
    first, second = decide(spec, "lookup", **ALLOWED), decide(spec, "lookup", **ALLOWED)
    assert first.decision_id != second.decision_id and first.policy_version


async def test_a_write_tool_is_never_executed_even_with_permission():
    registry = _registry(executed := [])
    registry._tools["file_payroll"] = _spec(name="file_payroll", is_write_action=True)
    result = await registry.execute("file_payroll", '{"key": "x"}', granted_permissions=frozenset({"*"}))
    assert result.error_code == "write_action_blocked" and executed == []


async def test_execute_rejects_a_decision_for_another_tool_or_a_refusal():
    registry = _registry(executed := [])
    other = PolicyDecision(decision_id="pd-1", tool="other", allowed=True, reason_code="allowed", role="Admin")
    refused = PolicyDecision(decision_id="pd-2", tool="lookup", allowed=False, reason_code="role_changed", role="Admin")
    for decision in (other, refused):
        result = await registry.execute("lookup", '{"key": "x"}', granted_permissions=frozenset(), decision=decision)
        assert result.error_code == "permission_denied"
    assert executed == []


async def test_a_role_revoked_mid_run_is_refused_at_the_next_call():
    """QA: role revoked mid-session → the next tool call is denied."""
    executed: list[str] = []
    registry = _registry(executed)
    state = {"role_unchanged": True}

    async def authorize(tool):
        decision = decide(registry.get(tool), tool, **{**ALLOWED, **state})
        state["role_unchanged"] = False  # an administrator changes the role after the first call
        return decision

    client = ScriptedClient([
        _reply(tool_calls=[_call("lookup", {"key": "a"}, "c1")]),
        _reply(tool_calls=[_call("lookup", {"key": "b"}, "c2")]),
        _reply("done"),
    ])
    done = []

    async def on_done(record):
        done.append(record)

    outcome = await _run(client, registry, authorize=authorize, on_tool_done=on_done)
    assert executed == ["a"]
    assert [r.error_code for r in outcome.tool_calls] == [None, "permission_denied"]
    assert [r.policy_reason for r in done] == ["allowed", "role_changed"]
    assert all(r.policy_decision_id and r.policy_decision_id.startswith("pd-") for r in done)
    assert "Policy refused 'lookup' (role_changed)" in client.requests[2]["messages"][-1]["content"]


async def test_an_unknown_tool_proposed_by_the_model_is_refused_by_policy():
    registry = _registry(executed := [])

    async def authorize(tool):
        return decide(registry.get(tool), tool, **ALLOWED)

    client = ScriptedClient([_reply(tool_calls=[_call("send_email", {"to": "x@example.com"})]), _reply("ok")])
    outcome = await _run(client, registry, authorize=authorize)
    assert executed == [] and outcome.tool_calls[0].policy_reason == "unknown_tool"


def test_every_production_tool_is_read_only():
    from app.domains.model_gateway.tool_registry import build_default_registry
    registry = build_default_registry()
    assert registry.names() and all(not registry.get(name).is_write_action for name in registry.names())


async def test_a_run_over_its_token_budget_stops_calling_tools_and_answers():
    """§05.4: token budget enforced; the stop reason is recorded."""
    from types import SimpleNamespace
    from app.domains.model_gateway.agent import AgentLimits

    def with_usage(reply, tokens):
        reply.usage = SimpleNamespace(total_tokens=tokens)
        return reply

    executed: list[str] = []
    client = ScriptedClient([
        with_usage(_reply(tool_calls=[_call("lookup", {"key": "a"})]), 900),
        with_usage(_reply("Answer from what was gathered."), 50),
    ])
    outcome = await _run(client, _registry(executed), limits=AgentLimits(max_total_tokens=500))
    assert executed == [] and outcome.stop_reason == "token_budget"
    assert outcome.tokens_used == 950 and outcome.text == "Answer from what was gathered."
    assert client.requests[-1]["tool_choice"] == "none"


def test_every_production_tool_has_an_explicit_role_list_and_refuses_unknown_roles():
    from app.domains.model_gateway.tool_registry import build_default_registry
    registry = build_default_registry()
    for name in registry.names():
        spec = registry.get(name)
        assert spec.allowed_roles and "Admin" in spec.allowed_roles and "SME Reviewer" in spec.allowed_roles
        assert decide(spec, name, **{**ALLOWED, "role": "Unknown Role"}).reason_code == "role_not_allowed"


async def test_a_run_whose_every_tool_failed_stops_with_no_result():
    from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec
    from tests.test_agent_loop import _LookupArgs

    async def empty(args):
        return ToolResult.failure("no_data", "nothing found")
    registry = ToolRegistry()
    registry.register(ToolSpec(name="lookup", version="1", description="d", args_model=_LookupArgs, handler=empty,
                               data_source="t", risk_level="low", timeout_seconds=1.0))
    client = ScriptedClient([_reply(tool_calls=[_call("lookup", {"key": "a"})]), _reply("Nothing could be found.")])
    outcome = await _run(client, registry)
    assert outcome.stop_reason == "no_result"


async def test_a_run_over_its_spend_budget_stops_calling_tools():
    from types import SimpleNamespace
    from app.domains.model_gateway.agent import AgentLimits

    def with_usage(reply, tokens):
        reply.usage = SimpleNamespace(total_tokens=tokens)
        return reply

    executed: list[str] = []
    client = ScriptedClient([with_usage(_reply(tool_calls=[_call("lookup", {"key": "a"})]), 2_000_000),
                             with_usage(_reply("Answer."), 10)])
    outcome = await _run(client, _registry(executed),
                         limits=AgentLimits(max_total_tokens=10_000_000, max_cost_usd=0.5, price_per_million_tokens=0.6))
    assert executed == [] and outcome.stop_reason == "cost_budget" and outcome.cost_usd > 0.5


async def test_a_retried_request_resumes_completed_tool_calls():
    """§05.4 safe resume: same idempotency key → successful calls are reused,
    still re-authorised, and marked as resumed."""
    from app.domains.model_gateway.agent import run_agent
    executed: list[str] = []
    registry = _registry(executed)
    authorizations = []

    async def authorize(tool):
        authorizations.append(tool)
        return decide(registry.get(tool), tool, **ALLOWED)

    for attempt in range(2):
        done = []

        async def on_done(record):
            done.append(record)
        client = ScriptedClient([_reply(tool_calls=[_call("lookup", {"key": "gdp"})]), _reply("GDP is up.")])
        await run_agent(client, model="m", system_prompt="", user_prompt="q", registry=registry,
                        granted_permissions=frozenset(), authorize=authorize, on_tool_done=on_done,
                        resume_key="idem-resume-test")
        assert done[0].resumed is (attempt == 1)
    assert executed == ["gdp"] and authorizations == ["lookup", "lookup"]
