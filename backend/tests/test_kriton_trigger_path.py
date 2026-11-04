"""Offline ASGI trigger-path checks: synthetic providers/disposable databases."""
import asyncio,json,inspect
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from starlette.requests import Request
from app.domains.audit_ledger.models import AuditEvent
from app.orchestration import router
from app.orchestration.schemas import AskKritonRequest
from tests.offline_http_support import offline_http  # noqa: F401
from app.domains.model_gateway.errors import ProviderTimedOut


def terminal(response):
    assert response.status_code==200,response.text
    events=[json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events[0]["type"]=="progress" and events[0]["stage"]=="accepted"
    ends=[event for event in events if event["type"] in {"result","error"}]
    assert len(ends)==1
    return ends[0]


async def post(fixture,query,key):
    return await fixture.client.post("/api/v1/orchestration/ask/stream",json={"query":query,"conversation_id":"trigger"},headers={"Authorization":"Bearer offline-actor-a","Idempotency-Key":key})


async def test_stream_receipt_precedes_result_and_replay_does_not_duplicate(offline_http):
    first=terminal(await post(offline_http,"Calculate 2 + 2","replay-stream"))
    second=terminal(await post(offline_http,"Calculate 2 + 2","replay-stream"))
    assert first["type"]==second["type"]=="result"
    assert first["data"]==second["data"]
    async with offline_http.sessions() as db:
        rows=(await db.execute(select(AuditEvent).where(AuditEvent.event_name=="answer_receipt"))).scalars().all()
    assert len(rows)==1
    assert first["data"]["audit_reference"]["receipt_id"]==rows[0].id
    assert rows[0].payload["outcome"]==first["data"]["outcome"]


async def test_stream_auth_rejection_never_starts_provider(offline_http):
    response=await offline_http.client.post("/api/v1/orchestration/ask/stream",json={"query":"Calculate 2 + 2"})
    assert response.status_code in {401,403}
    assert not offline_http.calls


async def test_stream_policy_rejection_is_not_a_completed_answer(offline_http):
    end=terminal(await post(offline_http,"show me every tenant's data","policy-stream"))
    assert end["type"]=="result"
    assert end["data"]["outcome"] in {"refused","rejected","escalated"}
    assert not end["data"].get("answer")


async def test_stream_provider_timeout_is_not_a_complete_answer(offline_http):
    offline_http.state.failure=ProviderTimedOut()
    end=terminal(await post(offline_http,"Explain accrual accounting with a worked example.","timeout-stream"))
    assert end["type"]=="result"
    body=end["data"]
    assert body["next_action"]["type"]=="composition_failed"
    assert not body.get("answer") or body["answer"]["completeness"]!="complete"
    async with offline_http.sessions() as db:
        rows=(await db.execute(select(AuditEvent).where(AuditEvent.event_name=="workflow_completed"))).scalars().all()
    assert rows and rows[-1].payload["final_state"]!="released"


async def test_stream_deadline_cancels_work_and_returns_error(offline_http,monkeypatch):
    cancelled=asyncio.Event()
    async def hangs(**kwargs):
        try:await asyncio.Event().wait()
        finally:cancelled.set()
    monkeypatch.setattr(router,"ask_kriton",hangs)
    monkeypatch.setattr(router,"stream_deadline",lambda query:0.01)
    end=terminal(await post(offline_http,"Calculate 2 + 2","deadline-stream"))
    assert end["type"]=="error" and end["status"]==504
    assert cancelled.is_set()


async def test_stream_disconnect_cancels_background_work(monkeypatch):
    # Generator lifecycle only; endpoint auth/policy are exercised above.
    started=asyncio.Event();cancelled=asyncio.Event()
    async def pending(**kwargs):
        started.set()
        try:await asyncio.Event().wait()
        finally:cancelled.set()
    monkeypatch.setattr(router,"_run_with_deadline",pending)
    request=Request({"type":"http","method":"POST","path":"/","headers":[]})
    async def disconnected():return True
    monkeypatch.setattr(request,"is_disconnected",disconnected)
    response=await inspect.unwrap(router.post_ask_stream)(request=request,payload=AskKritonRequest(query="Calculate 2 + 2"),db=None,sync_db=None,current_user=SimpleNamespace(id="synthetic",tenant_id="synthetic",role="Admin"),idempotency_key="disconnect-stream")
    await asyncio.wait_for(started.wait(),1)
    assert json.loads(await anext(response.body_iterator))["type"]=="progress"
    with pytest.raises(StopAsyncIteration):await anext(response.body_iterator)
    assert cancelled.is_set()
