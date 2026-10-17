"""Individual ("Myself") vs company sign-up.

The first /auth/provision call decides the new workspace:
  * company (default, unchanged): tenant named after the company, user is Admin;
  * individual: private one-person tenant, user is a Learner with no
    governance permissions, adults only until the minors controls exist.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.supabase_auth import SupabaseClaims
from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Tenant
from app.domains.identity.permissions import ALL_PERMISSIONS, ASSIGNABLE_ROLES, user_has_permission
from app.domains.identity.router import provision
from app.domains.identity.schemas import ProvisionRequest
from app.domains.identity.service import get_user_by_id


@pytest.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr("app.core.supabase_admin.update_app_metadata", lambda uid, tid, role: None)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def _as(monkeypatch, sub: str, email: str, provider: str = "email") -> None:
    claims = SupabaseClaims(sub=sub, email=email, provider=provider)
    monkeypatch.setattr("app.domains.identity.router.verify_token", lambda token: claims)


async def test_individual_signup_gets_a_private_learner_workspace(db, monkeypatch) -> None:
    _as(monkeypatch, "u-ind", "asha@example.com")
    user = await provision(
        ProvisionRequest(first_name="Asha", last_name="Rao", account_type="individual", adult_confirmed=True),
        db, "token",
    )
    assert user.role == "Learner"
    tenant = await db.get(Tenant, user.tenant_id)
    assert tenant.name == "Asha Rao (personal)"
    row = await get_user_by_id(db, "u-ind")
    assert not any(user_has_permission(row, p) for p in ALL_PERMISSIONS)
    [event] = (await db.execute(select(AuditEvent).where(AuditEvent.event_name == "auth.provisioned"))).scalars()
    assert event.payload["account_type"] == "individual"


async def test_individual_workspace_is_named_from_email_without_a_name(db, monkeypatch) -> None:
    _as(monkeypatch, "u-anon", "student42@example.com")
    user = await provision(ProvisionRequest(account_type="individual", adult_confirmed=True), db, "token")
    assert (await db.get(Tenant, user.tenant_id)).name == "student42 (personal)"


async def test_individual_signup_requires_adult_confirmation(db, monkeypatch) -> None:
    _as(monkeypatch, "u-minor", "teen@example.com")
    with pytest.raises(HTTPException) as exc:
        await provision(ProvisionRequest(first_name="T", account_type="individual"), db, "token")
    assert exc.value.status_code == 422
    assert "18" in exc.value.detail
    assert await get_user_by_id(db, "u-minor") is None
    assert (await db.execute(select(Tenant))).scalars().all() == []


async def test_company_signup_is_unchanged(db, monkeypatch) -> None:
    _as(monkeypatch, "u-co", "owner@acme.example")
    user = await provision(ProvisionRequest(first_name="Olu", company_name="Acme Ltd"), db, "token")
    assert user.role == "Admin"
    assert (await db.get(Tenant, user.tenant_id)).name == "Acme Ltd"


@pytest.mark.parametrize("provider", ["google", "azure"])
async def test_oauth_sign_up_is_always_a_learner_never_a_company_admin(db, monkeypatch, provider) -> None:
    # "Continue with Google" must never create a company workspace, even when
    # the browser asks for one (a stale "My company" choice, a crafted call).
    _as(monkeypatch, f"u-{provider}", f"new-{provider}@gmail.com", provider=provider)
    user = await provision(
        ProvisionRequest(first_name="Gia", company_name="Acme Ltd", account_type="company", adult_confirmed=True),
        db, "token",
    )
    assert user.role == "Learner"
    assert (await db.get(Tenant, user.tenant_id)).name == "Gia (personal)"
    [event] = (await db.execute(select(AuditEvent).where(AuditEvent.event_name == "auth.provisioned"))).scalars()
    assert (event.payload["account_type"], event.payload["provider"]) == ("individual", provider)


async def test_oauth_sign_up_still_needs_adult_confirmation(db, monkeypatch) -> None:
    _as(monkeypatch, "u-g", "kid@gmail.com", provider="google")
    with pytest.raises(HTTPException) as exc:
        await provision(ProvisionRequest(account_type="company", company_name="Acme"), db, "token")
    assert exc.value.status_code == 422


async def test_choice_only_applies_on_first_provision(db, monkeypatch) -> None:
    """A later call claiming "company" can never upgrade an existing Learner."""
    _as(monkeypatch, "u-ind", "asha@example.com")
    first = await provision(ProvisionRequest(account_type="individual", adult_confirmed=True), db, "t")
    again = await provision(ProvisionRequest(account_type="company", company_name="Sneaky Inc"), db, "t")
    assert again.role == "Learner" and again.tenant_id == first.tenant_id


async def test_invite_only_mode_also_blocks_individual_signup(db, monkeypatch) -> None:
    class _Settings:
        ALLOW_PUBLIC_SIGNUP = False

    monkeypatch.setattr("app.domains.identity.service.get_settings", lambda: _Settings())
    _as(monkeypatch, "u-x", "x@example.com")
    with pytest.raises(HTTPException) as exc:
        await provision(ProvisionRequest(account_type="individual", adult_confirmed=True), db, "token")
    assert exc.value.status_code == 403


def test_unknown_account_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProvisionRequest(account_type="admin")


def test_learner_is_assignable_by_company_admins() -> None:
    assert "Learner" in ASSIGNABLE_ROLES
