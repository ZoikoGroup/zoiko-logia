"""Super Admin directory: every company and account across tenants, people
only (no service accounts), with a status per account and per company."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.identity.models import ServiceAccount, Tenant, User
from app.domains.platform.directory import directory
from app.domains.platform.router import require_super_admin

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dir.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t-acme", name="Acme Ltd"),
            Tenant(id="t-ada", name="Ada Lovelace (personal)"),
            Tenant(id="t-blank", name=""),
            Tenant(id="t-empty", name="Ghost Co"),
        ])
        await session.flush()
        session.add_all([
            User(id="u-admin", tenant_id="t-acme", email="admin@acme.com", full_name="Ann Admin", role="Admin",
                 created_at=NOW - timedelta(days=9)),
            User(id="u-rev", tenant_id="t-acme", email="rev@acme.com", full_name="Rex Reviewer", role="SME Reviewer"),
            User(id="u-off", tenant_id="t-acme", email="off@acme.com", full_name="Olive Off", role="Learner", is_active=False),
            User(id="u-ada", tenant_id="t-ada", email="ada@example.com", full_name="Ada Lovelace", role="Learner"),
            User(id="u-blank", tenant_id="t-blank", email="owner@blank.com", full_name="Bo Blank", role="Admin"),
            User(id="svc-1", tenant_id="t-acme", email="svc@service-accounts.invalid", full_name="Bot", role="System Auditor"),
        ])
        await session.flush()
        session.add(ServiceAccount(id="svc-1", tenant_id="t-acme", name="Bot", owner_user_id="u-admin", created_by="u-admin"))
        await session.commit()
        yield session
    await engine.dispose()


async def test_lists_every_company_and_person_across_tenants(db) -> None:
    d = await directory(db, now=NOW)
    emails = {a["email"] for a in d["accounts"]}
    assert emails == {"admin@acme.com", "rev@acme.com", "off@acme.com", "ada@example.com", "owner@blank.com"}, \
        "every role in every tenant, never service accounts"
    acme = next(c for c in d["companies"] if c["id"] == "t-acme")
    assert (acme["type"], acme["members"], acme["activeMembers"]) == ("company", 3, 2)
    assert acme["roles"] == {"Admin": 1, "SME Reviewer": 1, "Learner": 1}
    assert acme["admins"] == [{"name": "Ann Admin", "email": "admin@acme.com"}]
    ada = next(c for c in d["companies"] if c["id"] == "t-ada")
    assert (ada["type"], ada["name"]) == ("personal", "Ada Lovelace")
    assert next(c for c in d["companies"] if c["id"] == "t-blank")["name"] == "Unnamed company (owner@blank.com)"
    assert next(c for c in d["companies"] if c["id"] == "t-empty")["state"] == "empty"
    assert (d["summary"]["companies"], d["summary"]["personalWorkspaces"], d["summary"]["accounts"]) == (3, 1, 5)


async def test_account_status_without_sign_in_data(db) -> None:
    d = await directory(db, now=NOW)
    assert d["signInDataAvailable"] is False, "SQLite has no Supabase auth schema: unknown, not guessed"
    status = {a["email"]: a["status"] for a in d["accounts"]}
    assert status["off@acme.com"] == "deactivated"
    assert status["admin@acme.com"] == "active"
    assert all(a["emailConfirmed"] is None and a["mfa"] is None for a in d["accounts"])


async def test_directory_needs_the_platform_role(db) -> None:
    tenant_admin = await db.get(User, "u-admin")
    with pytest.raises(HTTPException) as exc:
        await require_super_admin(tenant_admin, db)
    assert exc.value.status_code == 403
