from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.domains.audit_ledger import event_envelope


@pytest.mark.asyncio
async def test_audit_commit_restores_tenant_and_user_rls_context(monkeypatch):
    db = SimpleNamespace(add=Mock(), commit=AsyncMock(), rollback=AsyncMock())
    execute = AsyncMock()
    monkeypatch.setattr(event_envelope, "_execute_reconnect", execute)
    monkeypatch.setattr(event_envelope.settings, "DATABASE_URL", "postgresql://test")
    token = event_envelope._cached_previous_chain_hash.set("previous-hash")
    try:
        await event_envelope.record_event_async(
            db,
            tenant_id="tenant-1",
            actor_id="user-1",
            event_name="test_event",
            emitting_service="tests",
            subject_type="test",
            subject_id="subject-1",
            payload={},
        )
    finally:
        event_envelope._cached_previous_chain_hash.reset(token)

    assert execute.await_count == 2
    assert execute.await_args_list[0].args[2] == {"tenant_id": "tenant-1"}
    assert execute.await_args_list[1].args[2] == {"user_id": "user-1"}

