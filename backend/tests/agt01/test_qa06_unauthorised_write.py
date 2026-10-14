"""QA 6 — unauthorised tool / write attempt ("file my payroll return"): blocked, no execution."""
from agt01_support import call, reply, run

from app.domains.model_gateway.tool_registry import build_default_registry


async def test_a_filing_tool_proposed_by_the_model_is_refused():
    outcome, trace, _ = await run([
        reply(calls=[call("c1", "submit_payroll_return", {"period": "2026-09"})]),
        reply("I can explain how to prepare the return, but I cannot file it."),
    ], question="File my payroll return for September.")
    assert [(r.tool, r.ok, r.policy_reason) for r in trace] == [("submit_payroll_return", False, "unknown_tool")]
    assert "cannot file" in outcome.text


def test_no_production_tool_can_write_anything():
    registry = build_default_registry()
    assert not any(registry.get(name).is_write_action for name in registry.names())
