"""A person whose Supabase identity was deleted and who registered again keeps
their profile (tenant, role, data) — but only when the old identity is really
gone and the new one has a confirmed email. Otherwise provisioning still 409s."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import supabase_admin
from app.db.base import Base
from app.domains.identity import relink
from app.domains.identity.models import PasswordResetChallenge, Tenant, User
from app.domains.identity.schemas import ProvisionRequest
from app.domains.identity.service import provision_profile

OLD, NEW, EMAIL = "old-auth-id", "new-auth-id", "ada@example.com"


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'relink.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    make = async_sessionmaker(engine, expire_on_commit=False)
    async with make() as db:
        db.add(Tenant(id="t-1", name="Ada Ltd"))
        db.add(User(id=OLD, tenant_id="t-1", email=EMAIL, full_name="Ada L", role="Admin", platform_role="super_admin"))
        await db.flush()
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        db.add(PasswordResetChallenge(user_id=OLD, code_hash="x", salt="y", created_at=now,
                                      expires_at=now + timedelta(minutes=5), attempts=0))
        await db.commit()
    monkeypatch.setattr(relink, "AsyncSessionLocal", make)
    monkeypatch.setattr(supabase_admin, "is_configured", lambda: True)
    monkeypatch.setattr(supabase_admin, "update_app_metadata", lambda *a: None)
    yield make
    await engine.dispose()


def _supabase(monkeypatch, users: dict) -> None:
    monkeypatch.setattr(supabase_admin, "get_user", lambda uid: users.get(uid))


async def _provision(make):
    async with make() as db:
        return await provision_profile(db, NEW, EMAIL, ProvisionRequest(company_name="Other", account_type="company"))


async def test_reregistered_confirmed_identity_keeps_its_profile(factory, monkeypatch) -> None:
    _supabase(monkeypatch, {NEW: {"id": NEW, "email": EMAIL, "email_confirmed_at": "2026-10-17T00:00:00Z"}})
    user = await _provision(factory)
    assert (user.id, user.tenant_id, user.role, user.platform_role) == (NEW, "t-1", "Admin", "super_admin")
    async with factory() as db:
        assert (await db.get(User, OLD)) is None
        assert len((await db.execute(select(Tenant))).scalars().all()) == 1, "no second tenant created"
        challenge = (await db.execute(select(PasswordResetChallenge))).scalar_one()
        assert challenge.user_id == NEW, "references follow the profile"


async def test_live_old_identity_is_never_taken_over(factory, monkeypatch) -> None:
    confirmed = {"email": EMAIL, "email_confirmed_at": "2026-10-17T00:00:00Z"}
    _supabase(monkeypatch, {OLD: {"id": OLD, **confirmed}, NEW: {"id": NEW, **confirmed}})
    with pytest.raises(HTTPException) as exc:
        await _provision(factory)
    assert exc.value.status_code == 409


async def test_unconfirmed_new_identity_is_refused(factory, monkeypatch) -> None:
    _supabase(monkeypatch, {NEW: {"id": NEW, "email": EMAIL, "email_confirmed_at": None}})
    with pytest.raises(HTTPException) as exc:
        await _provision(factory)
    assert exc.value.status_code == 409
    async with factory() as db:
        assert (await db.get(User, OLD)) is not None
