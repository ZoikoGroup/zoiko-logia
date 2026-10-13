"""Elevated-access governance: impersonation, break-glass, service accounts,
admin MFA reset and email invitations.

Pins the rules identity/governance.py exists to enforce:
  * impersonation is Admin-only, reasoned, time-boxed, same-tenant, never of an
    Admin, read-only (middleware), and fails closed once ended or expired;
  * break-glass needs a different Admin to activate and to review, expires on
    its own, grants only what was asked, and flags repeated use;
  * service accounts authenticate only by API key, never hold Admin, store
    only key hashes, and stop working once the key is revoked or expired;
  * admin MFA reset and invitations are audited and never self-applied.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.supabase_auth import SupabaseClaims
from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity import governance
from app.domains.identity.models import (
    BreakGlassGrant,
    ImpersonationSession,
    ServiceAccountKey,
    Tenant,
    User,
)
from app.domains.identity.permissions import AUDIT_CORRECT, SOURCE_MANAGE, user_has_permission
from app.domains.identity.rbac import enforce_step_up, get_current_user
from app.domains.identity.router import post_user, post_user_mfa_reset
from app.domains.identity.schemas import UserCreateRequest
from app.domains.identity.service import get_user_by_id, list_users


class _Settings:
    def __init__(self, **overrides) -> None:
        self.IMPERSONATION_MAX_MINUTES = 60
        self.BREAK_GLASS_MAX_MINUTES = 240
        self.BREAK_GLASS_REPEAT_THRESHOLD = 3
        self.SERVICE_KEY_MAX_DAYS = 365
        self.MFA_REQUIRED_FOR_PRIVILEGED = True
        self.FRONTEND_URL = "https://app.example.com"
        self.__dict__.update(overrides)


def _user(user_id: str, tenant_id: str, role: str) -> User:
    return User(
        id=user_id, tenant_id=tenant_id, email=f"{user_id}@example.com",
        first_name=user_id, last_name="", full_name=user_id, role=role, is_active=True,
    )


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'gov.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr("app.domains.identity.governance.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.core.supabase_admin.update_app_metadata", lambda uid, tid, role: None)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="One"), Tenant(id="t2", name="Two"),
            _user("admin", "t1", "Admin"), _user("admin2", "t1", "Admin"),
            _user("staff", "t1", "Source Admin"), _user("auditor", "t1", "System Auditor"),
            _user("other", "t2", "Source Admin"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


async def _events(db, name: str) -> list[AuditEvent]:
    return list((await db.execute(select(AuditEvent).where(AuditEvent.event_name == name))).scalars())


async def _signed_in(db, monkeypatch, user_id: str, *, header: str | None = None) -> User:
    user = await get_user_by_id(db, user_id)
    claims = SupabaseClaims(sub=user_id, email=user.email, tenant_id=user.tenant_id, role=user.role, aal="aal2")
    monkeypatch.setattr("app.domains.identity.rbac.verify_token", lambda token: claims)
    return await get_current_user("jwt", db, header)


# ── Impersonation ────────────────────────────────────────────────────────────

async def test_admin_can_view_as_a_tenant_user(db, monkeypatch) -> None:
    admin = await get_user_by_id(db, "admin")
    session = await governance.start_impersonation(db, admin, "staff", "ticket #42", 30)
    [event] = await _events(db, "admin_impersonation_started")
    assert event.subject_id == "staff" and event.payload["read_only"] is True

    viewed = await _signed_in(db, monkeypatch, "admin", header=session.id)
    assert viewed.id == "staff"
    assert viewed.impersonated_by == "admin"
    assert viewed.role == "Source Admin"


@pytest.mark.parametrize(
    ("target", "minutes", "reason", "status_code"),
    [
        ("admin2", 30, "x", 403),   # never another Admin
        ("other", 30, "x", 404),    # never another tenant
        ("admin", 30, "x", 409),    # never yourself
        ("staff", 61, "x", 422),    # capped duration
        ("staff", 30, "  ", 422),   # reason required
    ],
)
async def test_impersonation_guardrails(db, target, minutes, reason, status_code) -> None:
    admin = await get_user_by_id(db, "admin")
    with pytest.raises(governance.GovernanceError) as exc:
        await governance.start_impersonation(db, admin, target, reason, minutes)
    assert exc.value.status_code == status_code


async def test_ended_expired_or_foreign_sessions_fail_closed(db, monkeypatch) -> None:
    admin = await get_user_by_id(db, "admin")
    session = await governance.start_impersonation(db, admin, "staff", "check", 30)

    # Another Admin cannot ride on this session.
    with pytest.raises(HTTPException) as exc:
        await _signed_in(db, monkeypatch, "admin2", header=session.id)
    assert exc.value.status_code == 403

    await governance.end_impersonation(db, admin, session.id)
    assert len(await _events(db, "admin_impersonation_ended")) == 1
    with pytest.raises(HTTPException):
        await _signed_in(db, monkeypatch, "admin", header=session.id)

    expired = ImpersonationSession(
        tenant_id="t1", actor_id="admin", target_user_id="staff", reason="old",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.add(expired)
    await db.commit()
    with pytest.raises(HTTPException):
        await _signed_in(db, monkeypatch, "admin", header=expired.id)


async def test_starting_a_new_session_ends_the_previous_one(db) -> None:
    admin = await get_user_by_id(db, "admin")
    first = await governance.start_impersonation(db, admin, "staff", "a", 30)
    second = await governance.start_impersonation(db, admin, "auditor", "b", 30)
    assert (await governance.active_impersonation(db, admin)).id == second.id
    await db.refresh(first)
    assert first.ended_at is not None


def test_impersonated_requests_are_read_only() -> None:
    from app.main import create_app

    client = TestClient(create_app())  # no lifespan: the middleware answers first
    for method in ("post", "patch", "put", "delete"):
        response = getattr(client, method)("/api/v1/users", headers={"X-Impersonation-Session": "any"})
        assert response.status_code == 403, method
        assert "read-only" in response.json()["detail"]


# ── Break-glass ──────────────────────────────────────────────────────────────

async def test_break_glass_lifecycle(db, monkeypatch) -> None:
    requester = await get_user_by_id(db, "auditor")
    assert not user_has_permission(requester, AUDIT_CORRECT)
    grant = await governance.request_break_glass(db, requester, [AUDIT_CORRECT], "fix ledger typo", 60)
    assert grant.status == "requested"

    # Not active until a different Admin approves it.
    me = await _signed_in(db, monkeypatch, "auditor")
    assert not user_has_permission(me, AUDIT_CORRECT)

    approver = await get_user_by_id(db, "admin")
    grant = await governance.approve_break_glass(db, approver, grant.id)
    assert grant.status == "active" and grant.approved_by == "admin"

    me = await _signed_in(db, monkeypatch, "auditor")
    assert user_has_permission(me, AUDIT_CORRECT)
    assert not user_has_permission(me, SOURCE_MANAGE), "only the requested permission is granted"

    await governance.revoke_break_glass(db, me, grant.id)
    me = await _signed_in(db, monkeypatch, "auditor")
    assert not user_has_permission(me, AUDIT_CORRECT)

    with pytest.raises(governance.GovernanceError):
        await governance.review_break_glass(db, me, grant.id, "self review")
    reviewed = await governance.review_break_glass(db, approver, grant.id, "Used for EV-17 correction only.")
    assert reviewed.reviewed_by == "admin"
    names = {e.event_name for e in (await db.execute(select(AuditEvent))).scalars()}
    assert {
        "break_glass_access_requested", "break_glass_access_granted",
        "break_glass_access_revoked", "break_glass_access_reviewed", "self_approval_attempt_blocked",
    } <= names


async def test_requester_cannot_approve_own_break_glass(db) -> None:
    admin = await get_user_by_id(db, "admin")
    grant = await governance.request_break_glass(db, admin, [AUDIT_CORRECT], "urgent", 30)
    with pytest.raises(governance.GovernanceError) as exc:
        await governance.approve_break_glass(db, admin, grant.id)
    assert exc.value.status_code == 403
    assert len(await _events(db, "self_approval_attempt_blocked")) == 1


async def test_break_glass_expires_on_its_own(db, monkeypatch) -> None:
    requester = await get_user_by_id(db, "auditor")
    grant = await governance.request_break_glass(db, requester, [AUDIT_CORRECT], "x", 30)
    await governance.approve_break_glass(db, await get_user_by_id(db, "admin"), grant.id)
    grant.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()

    me = await _signed_in(db, monkeypatch, "auditor")
    assert not user_has_permission(me, AUDIT_CORRECT)
    [listed] = await governance.list_break_glass(db, await get_user_by_id(db, "admin"))
    assert listed.status == "expired"


@pytest.mark.parametrize(("permissions", "minutes"), [(["root.everything"], 30), ([AUDIT_CORRECT], 241), ([], 30)])
async def test_break_glass_request_validation(db, permissions, minutes) -> None:
    with pytest.raises(governance.GovernanceError) as exc:
        await governance.request_break_glass(db, await get_user_by_id(db, "auditor"), permissions, "x", minutes)
    assert exc.value.status_code == 422


async def test_repeated_break_glass_use_is_flagged(db) -> None:
    requester = await get_user_by_id(db, "auditor")
    approver = await get_user_by_id(db, "admin")
    for _ in range(3):
        grant = await governance.request_break_glass(db, requester, [AUDIT_CORRECT], "again", 10)
        await governance.approve_break_glass(db, approver, grant.id)
        await governance.revoke_break_glass(db, approver, grant.id)
    [flag] = await _events(db, "break_glass_repeated_use_detected")
    assert flag.subject_id == "auditor" and flag.payload["grants_in_30_days"] == 3


async def test_non_admins_only_see_their_own_grants(db) -> None:
    await governance.request_break_glass(db, await get_user_by_id(db, "auditor"), [AUDIT_CORRECT], "a", 10)
    await governance.request_break_glass(db, await get_user_by_id(db, "staff"), [AUDIT_CORRECT], "b", 10)
    assert {g.user_id for g in await governance.list_break_glass(db, await get_user_by_id(db, "staff"))} == {"staff"}
    assert len(await governance.list_break_glass(db, await get_user_by_id(db, "admin"))) == 2


# ── Service accounts ─────────────────────────────────────────────────────────

async def _service_account_with_key(db, role: str = "Source Admin"):
    admin = await get_user_by_id(db, "admin")
    account = await governance.create_service_account(
        db, admin, name="ERP sync", description="nightly", role=role, owner_user_id="staff",
    )
    key, raw = await governance.issue_service_account_key(db, admin, account.id, 30)
    return admin, account, key, raw


async def test_service_account_authenticates_with_its_key_only(db) -> None:
    _, account, key, raw = await _service_account_with_key(db)
    assert raw.startswith("zlk_")
    stored = await db.get(ServiceAccountKey, key.id)
    assert stored.key_hash == governance.hash_api_key(raw) and raw not in stored.key_hash
    assert stored.key_prefix == raw[:12]

    user = await get_current_user(raw, db)
    assert user.id == account.id and user.auth_method == "api_key"
    assert user_has_permission(user, SOURCE_MANAGE)
    # Non-interactive credential: step-up MFA does not apply.
    await enforce_step_up(db, user, SOURCE_MANAGE)
    assert (await db.get(ServiceAccountKey, key.id)).last_used_at is not None


async def test_revoked_or_expired_keys_are_rejected(db) -> None:
    admin, account, key, raw = await _service_account_with_key(db)
    await governance.revoke_service_account_key(db, admin, account.id, key.id)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(raw, db)
    assert exc.value.status_code == 401

    key2, raw2 = await governance.issue_service_account_key(db, admin, account.id, 30)
    key2.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    with pytest.raises(HTTPException):
        await get_current_user(raw2, db)
    with pytest.raises(HTTPException):
        await get_current_user("zlk_not-a-real-key", db)


async def test_service_accounts_cannot_be_admin_or_impersonate(db) -> None:
    admin = await get_user_by_id(db, "admin")
    with pytest.raises(governance.GovernanceError):
        await governance.create_service_account(db, admin, name="x", description="", role="Admin", owner_user_id="staff")
    with pytest.raises(governance.GovernanceError):
        await governance.create_service_account(db, admin, name="x", description="", role="System Auditor", owner_user_id="other")

    _, account, _, raw = await _service_account_with_key(db)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(raw, db, "some-session")
    assert exc.value.status_code == 403
    svc = await get_current_user(raw, db)
    with pytest.raises(governance.GovernanceError):
        await governance.request_break_glass(db, svc, [AUDIT_CORRECT], "x", 10)
    with pytest.raises(governance.GovernanceError):
        await governance.start_impersonation(db, admin, account.id, "x", 10)


async def test_service_accounts_are_not_listed_as_people(db) -> None:
    _, account, _, _ = await _service_account_with_key(db)
    assert account.id not in {u.id for u in await list_users(db, "t1")}
    assert len(await _events(db, "service_account_created")) == 1
    assert len(await _events(db, "service_account_key_issued")) == 1


async def test_key_expiry_is_capped(db) -> None:
    admin = await get_user_by_id(db, "admin")
    account = await governance.create_service_account(db, admin, name="x", description="", role="System Auditor", owner_user_id="staff")
    with pytest.raises(governance.GovernanceError):
        await governance.issue_service_account_key(db, admin, account.id, 366)


# ── Admin MFA reset and invitations ─────────────────────────────────────────

async def test_admin_mfa_reset_removes_factors_and_sessions(db, monkeypatch) -> None:
    removed, revoked = [], []
    monkeypatch.setattr("app.core.supabase_admin.list_mfa_factors", lambda uid: [{"id": "f1"}, {"id": "f2"}])
    monkeypatch.setattr("app.core.supabase_admin.delete_mfa_factor", lambda uid, fid: removed.append((uid, fid)))
    monkeypatch.setattr("app.core.supabase_admin.revoke_all_sessions", lambda uid: revoked.append(uid) or True)
    admin = await get_user_by_id(db, "admin")

    response = await post_user_mfa_reset("staff", db, admin)
    assert response.status_code == 204
    assert removed == [("staff", "f1"), ("staff", "f2")] and revoked == ["staff"]
    [event] = await _events(db, "admin_mfa_reset")
    assert event.payload == {"factors_removed": 2}

    with pytest.raises(HTTPException) as exc:
        await post_user_mfa_reset("admin", db, admin)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await post_user_mfa_reset("other", db, admin)
    assert exc.value.status_code == 404


async def test_user_without_password_is_invited_by_email(db, monkeypatch) -> None:
    invites = []
    monkeypatch.setattr("app.domains.identity.service.get_settings", lambda: _Settings())
    monkeypatch.setattr(
        "app.core.supabase_admin.invite_user",
        lambda email, redirect_to: invites.append((email, redirect_to)) or {"id": "invited-1"},
    )
    admin = await get_user_by_id(db, "admin")
    created = await post_user(
        UserCreateRequest(email="new@example.com", full_name="New Person", role="SME Reviewer"), db, admin,
    )
    assert created.invited is True and created.id == "invited-1"
    assert invites == [("new@example.com", "https://app.example.com/auth/accept-invite")]
    assert len(await _events(db, "auth.user_invited")) == 1


def test_temporary_passwords_must_be_strong() -> None:
    with pytest.raises(ValidationError):
        UserCreateRequest(email="a@example.com", password="weak", full_name="A", role="SME Reviewer")
    assert UserCreateRequest(email="a@example.com", password="", full_name="A", role="SME Reviewer").password is None


async def test_break_glass_rows_are_tenant_scoped(db) -> None:
    grant = await governance.request_break_glass(db, await get_user_by_id(db, "auditor"), [AUDIT_CORRECT], "x", 10)
    with pytest.raises(governance.GovernanceError) as exc:
        await governance.approve_break_glass(db, await get_user_by_id(db, "other"), grant.id)
    assert exc.value.status_code == 404
    assert (await db.get(BreakGlassGrant, grant.id)).status == "requested"
