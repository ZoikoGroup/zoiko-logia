"""QA 2 — true multi-step task: ≥2 authorised calls, bounded, replayable order."""
from agt01_support import call, reply, run


async def test_two_authorised_steps_are_recorded_in_order():
    outcome, trace, _ = await run([
        reply(calls=[call("c1", "calculate", {"expression": "120000 / 1000000 * 100"})]),
        reply(calls=[call("c2", "calculate", {"expression": "150000 / 1200000 * 100"})]),
        reply("Margins were 12% and 12.5%."),
    ])
    assert [(r.step, r.tool, r.ok, r.policy_reason) for r in trace] == [
        (1, "calculate", True, "allowed"), (2, "calculate", True, "allowed")]
    assert all(r.policy_decision_id and r.idempotency_key.startswith("req-qa-s") for r in trace)
    assert outcome.steps == 3 and outcome.stop_reason == "final_answer"
