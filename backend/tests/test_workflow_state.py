"""Explicit request workflow states (ZL-ENG-AGT-01 §05.2, App. B4)."""
import asyncio
from types import SimpleNamespace

import pytest

from app.orchestration import router, workflow_state
from app.orchestration.workflow_state import WorkflowRun, WorkflowState


def test_states_follow_the_audit_trail_in_order():
    run = WorkflowRun()
    for event in ("query_received", "prescreen_completed", "risk_classified", "bundle_built",
                  "agent_tool_called", "bundle_built", "agent_tool_called", "release_check_completed"):
        run.observe(event)
    assert run.finish(released=True) == WorkflowState.RELEASED
    assert run.path == ["received", "checked", "evidence_ready", "tool_running", "evidence_ready",
                        "tool_running", "verifying", "released"]
    assert run.invalid == []


def test_a_clarification_may_skip_straight_to_release():
    run = WorkflowRun()
    run.observe("prescreen_completed")
    assert run.finish(released=True) == WorkflowState.RELEASED and run.path == ["received", "checked", "released"]


def test_a_response_sent_to_review_is_not_released():
    run = WorkflowRun()
    for event in ("prescreen_completed", "release_check_completed", "human_review_created"):
        run.observe(event)
    assert run.finish(released=True) == WorkflowState.AWAITING_REVIEW


def test_moving_backwards_or_after_the_end_is_recorded_not_applied():
    run = WorkflowRun()
    run.observe("release_check_completed")
    run.observe("prescreen_completed")
    assert run.state == WorkflowState.VERIFYING and run.invalid == ["verifying->checked"]
    run.finish(released=True)
    run.observe("agent_tool_called")
    assert run.state == WorkflowState.RELEASED and "released->tool_running" in run.invalid


async def test_every_answered_request_records_its_workflow_before_release(monkeypatch):
    events = []

    async def answered(**_):
        workflow_state.observe("prescreen_completed")
        workflow_state.observe("release_check_completed")
        return SimpleNamespace(query_id="q-1", next_action=None, model_dump=lambda **__: {})

    async def record(db, **event):
        events.append(event)

    async def commit(db, token):
        events.append({"event_name": "committed"})

    monkeypatch.setattr(router, "ask_kriton", answered)
    monkeypatch.setattr(router, "record_event_async", record)
    monkeypatch.setattr(router, "commit_audit_batch", commit)
    await router._run_with_deadline(db=object(), actor_id="u1", tenant_id="t1", request=None)
    assert [e["event_name"] for e in events] == ["workflow_completed", "answer_receipt", "committed"]
    assert events[0]["payload"]["final_state"] == "released"
    assert events[0]["payload"]["path"] == ["received", "checked", "verifying", "released"]
    receipt = events[1]["payload"]
    assert receipt["request_id"] == "q-1" and receipt["workflow_final_state"] == "released"
    assert receipt["calculation_ids"] == [] and receipt["policy_version"]


async def test_a_cancelled_request_leaves_a_durable_record(monkeypatch):
    recorded = []

    async def slow(**_):
        workflow_state.observe("prescreen_completed")
        await asyncio.sleep(10)

    async def record_cancellation(kwargs, run):
        recorded.append(run.summary())

    monkeypatch.setattr(router, "ask_kriton", slow)
    monkeypatch.setattr(router, "_record_cancellation", record_cancellation)
    task = asyncio.create_task(router._run_with_deadline(db=object(), actor_id="u1", tenant_id="t1", request=None))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert recorded and recorded[0]["final_state"] == "cancelled"
    assert recorded[0]["path"] == ["received", "checked", "cancelled"]
