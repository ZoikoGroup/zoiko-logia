import pytest

from app.orchestration import audit_events


@pytest.mark.asyncio
async def test_response_returned_does_not_reopen_a_database_transaction(monkeypatch):
    captured = {}

    async def fake_emit(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(audit_events, "_emit", fake_emit)

    await audit_events.audit_response_returned(
        object(),
        query_id="query-1",
        correlation_id="correlation-1",
        tenant_id="tenant-1",
        audit_chain_id="chain-1",
        actor_id="actor-1",
        latency_ms=123.4,
    )

    assert captured["restore_tenant_context"] is False
