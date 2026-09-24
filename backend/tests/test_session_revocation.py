"""ISSUE-3 regression — POST /auth/sign-out-all-sessions must not report
false success.

Previously the handler checked supabase_admin.is_configured() itself and
silently skipped revocation (still returning 204 AND still writing
auth.sessions_revoked) when the Admin API was unconfigured — a user believes
sessions were revoked and the audit log agrees, while nothing happened.

Fail-closed contract asserted here:
  * unconfigured        -> 503, revocation never attempted, no audit event
  * upstream non-confirm-> 502, no audit event
  * upstream failure    -> propagates (500), no audit event
  * confirmed revocation-> 204, exactly one auth.sessions_revoked event
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import supabase_admin
from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Tenant, User
from app.domains.identity.router import sign_out_all_sessions
from app.domains.identity.service import get_user_by_id

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def session_revocation_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        db.add_all([
            Tenant(id="tenant-1", name="Tenant One"),
            User(
                id="user-1", tenant_id="tenant-1", email="u1@example.com",
                first_name="Ada", last_name="Lovelace", full_name="Ada Lovelace",
                role="Admin", is_active=True,
            ),
        ])
        await db.commit()
        yield db
    await engine.dispose()


async def _count_revoked_events(db) -> int:
    result = await db.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.event_name == "auth.sessions_revoked")
    )
    return result.scalar_one()


def _raise_not_configured(_uid):
    return (_ for _ in ()).throw(supabase_admin.SupabaseNotConfiguredError("not configured"))


async def test_unconfigured_returns_503_not_204(session_revocation_db, monkeypatch) -> None:
    db = session_revocation_db
    monkeypatch.setattr("app.core.supabase_admin.revoke_all_sessions", _raise_not_configured)
    current = await get_user_by_id(db, "user-1")

    with pytest.raises(HTTPException) as exc:
        await sign_out_all_sessions(db, current)
    assert exc.value.status_code == 503
    assert await _count_revoked_events(db) == 0, "audit must not claim revocation that never happened"


async def test_upstream_non_confirmation_returns_502(session_revocation_db, monkeypatch) -> None:
    db = session_revocation_db
    monkeypatch.setattr("app.core.supabase_admin.revoke_all_sessions", lambda uid: False)
    current = await get_user_by_id(db, "user-1")

    with pytest.raises(HTTPException) as exc:
        await sign_out_all_sessions(db, current)
    assert exc.value.status_code == 502
    assert await _count_revoked_events(db) == 0


async def test_upstream_failure_propagates_and_is_not_audited(session_revocation_db, monkeypatch) -> None:
    db = session_revocation_db

    def explode(_uid):
        raise RuntimeError("network partition")

    monkeypatch.setattr("app.core.supabase_admin.revoke_all_sessions", explode)
    current = await get_user_by_id(db, "user-1")

    with pytest.raises(RuntimeError):
        await sign_out_all_sessions(db, current)
    assert await _count_revoked_events(db) == 0, "audit must never fire on a failed revocation attempt"


async def test_confirmed_revocation_returns_204_and_audits_once(session_revocation_db, monkeypatch) -> None:
    db = session_revocation_db
    revoked: list[str] = []
    monkeypatch.setattr(
        "app.core.supabase_admin.revoke_all_sessions",
        lambda uid: revoked.append(uid) or True,
    )
    current = await get_user_by_id(db, "user-1")

    resp = await sign_out_all_sessions(db, current)
    assert isinstance(resp, Response)
    assert resp.status_code == 204
    assert revoked == ["user-1"]
    assert await _count_revoked_events(db) == 1