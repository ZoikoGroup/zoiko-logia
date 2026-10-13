"""Authentication hardening tests.

Pins the controls added on top of the base sign-in flow:
  1. access_denied — every refused permission/role check writes the canonical
     event, and the 403 still stands;
  2. step-up MFA — with MFA_REQUIRED_FOR_PRIVILEGED on, privileged actions need
     an aal2 session, read permissions do not, and the level comes from the
     verified token (get_current_user), never the request;
  3. role governance — only registry roles are assignable, role changes are
     audited, an Admin cannot change their own role or demote the last Admin,
     and another tenant's user is invisible;
  4. invite-only sign-up — ALLOW_PUBLIC_SIGNUP=false refuses a new tenant to an
     unknown sign-up while invited (pre-created) users still provision;
  5. audit-ledger tenant isolation — list, single-event, replay, correction
     list and correction issue never cross a tenant boundary, including the
     merged safety_events rows.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.supabase_auth import SupabaseClaims
from app.db.base import Base
from app.domains.audit_ledger import service as audit_service
from app.domains.audit_ledger.compensating_events import CompensatingEventError
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.audit_ledger.models import AuditEvent, CompensatingEvent
from app.domains.audit_ledger.schemas import CompensatingEventCreate
from app.domains.identity.models import Tenant, User
from app.domains.identity.permissions import ASSIGNABLE_ROLES, SOURCE_MANAGE, SOURCE_READ
from app.domains.identity.rbac import MFA_REQUIRED_DETAIL, get_current_user, require_admin, require_permission
from app.domains.identity.router import patch_user, patch_user_role, provision
from app.domains.identity.schemas import (
    ProvisionRequest,
    UserActiveUpdateRequest,
    UserCreateRequest,
    UserRoleUpdateRequest,
)
from app.domains.identity.service import AccountChangeError, get_user_by_id, set_user_role
from app.domains.risk_safety.models import SafetyEvent

class _Settings:
    def __init__(self, *, mfa: bool = False, public_signup: bool = True) -> None:
        self.MFA_REQUIRED_FOR_PRIVILEGED = mfa
        self.ALLOW_PUBLIC_SIGNUP = public_signup


def _user(user_id: str, tenant_id: str, role: str, *, active: bool = True) -> User:
    return User(
        id=user_id, tenant_id=tenant_id, email=f"{user_id}@example.com",
        first_name=user_id, last_name="", full_name=user_id, role=role, is_active=active,
    )


@pytest.fixture
async def dbs(tmp_path, monkeypatch):
    """One SQLite file reached through both an async session (ledger, identity)
    and a sync session (safety_events), like the app's get_db/get_sync_db."""
    path = tmp_path / "auth.db"
    sync_engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync_engine)
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    sync_factory = sessionmaker(sync_engine)

    monkeypatch.setattr("app.core.supabase_admin.update_app_metadata", lambda uid, tid, role: None)

    async with async_factory() as db:
        db.add_all([
            Tenant(id="tenant-a", name="A"),
            Tenant(id="tenant-b", name="B"),
            _user("admin-a", "tenant-a", "Admin"),
            _user("admin-a2", "tenant-a", "Admin"),
            _user("auditor-a", "tenant-a", "System Auditor"),
            _user("admin-b", "tenant-b", "Admin"),
        ])
        await db.commit()
        with sync_factory() as sync_db:
            yield db, sync_db
    await async_engine.dispose()
    sync_engine.dispose()


async def _events(db, name: str) -> list[AuditEvent]:
    return list((await db.execute(select(AuditEvent).where(AuditEvent.event_name == name))).scalars())


# ── 1 + 2. access_denied and step-up MFA ─────────────────────────────────────

async def test_missing_permission_is_denied_and_audited(dbs) -> None:
    db, _ = dbs
    auditor = await get_user_by_id(db, "auditor-a")
    with pytest.raises(HTTPException) as exc:
        await require_permission(SOURCE_MANAGE)(current_user=auditor, db=db)
    assert exc.value.status_code == 403
    [event] = await _events(db, "access_denied")
    assert event.tenant_id == "tenant-a"
    assert event.actor_id == "auditor-a"
    assert event.payload == {"required": SOURCE_MANAGE, "role": "System Auditor", "reason": "missing_permission"}


async def test_non_admin_denied_admin_route_is_audited(dbs) -> None:
    db, _ = dbs
    auditor = await get_user_by_id(db, "auditor-a")
    with pytest.raises(HTTPException) as exc:
        await require_admin(current_user=auditor, db=db)
    assert exc.value.status_code == 403
    [event] = await _events(db, "access_denied")
    assert event.payload["reason"] == "missing_role"


async def test_step_up_not_enforced_when_policy_off(dbs, monkeypatch) -> None:
    db, _ = dbs
    monkeypatch.setattr("app.domains.identity.rbac.get_settings", lambda: _Settings(mfa=False))
    admin = await get_user_by_id(db, "admin-a")
    admin.auth_aal = "aal1"
    assert await require_permission(SOURCE_MANAGE)(current_user=admin, db=db) is admin
    assert await require_admin(current_user=admin, db=db) is admin


async def test_step_up_blocks_privileged_actions_without_mfa(dbs, monkeypatch) -> None:
    db, _ = dbs
    monkeypatch.setattr("app.domains.identity.rbac.get_settings", lambda: _Settings(mfa=True))
    admin = await get_user_by_id(db, "admin-a")
    admin.auth_aal = "aal1"
    for check in (require_permission(SOURCE_MANAGE), require_admin):
        with pytest.raises(HTTPException) as exc:
            await check(current_user=admin, db=db)
        assert exc.value.status_code == 403
        assert exc.value.detail == MFA_REQUIRED_DETAIL
    events = await _events(db, "access_denied")
    assert {e.payload["reason"] for e in events} == {"mfa_required"}


async def test_step_up_allows_aal2_and_never_gates_reads(dbs, monkeypatch) -> None:
    db, _ = dbs
    monkeypatch.setattr("app.domains.identity.rbac.get_settings", lambda: _Settings(mfa=True))
    admin = await get_user_by_id(db, "admin-a")
    admin.auth_aal = "aal1"
    # Reads are never step-up gated.
    assert await require_permission(SOURCE_READ)(current_user=admin, db=db) is admin
    admin.auth_aal = "aal2"
    assert await require_permission(SOURCE_MANAGE)(current_user=admin, db=db) is admin
    assert await require_admin(current_user=admin, db=db) is admin
    assert await _events(db, "access_denied") == []


async def test_assurance_level_comes_from_the_verified_token(dbs, monkeypatch) -> None:
    db, _ = dbs
    claims = SupabaseClaims(sub="admin-a", email="admin-a@example.com", tenant_id="tenant-a", role="Admin", aal="aal2")
    monkeypatch.setattr("app.domains.identity.rbac.verify_token", lambda token: claims)
    user = await get_current_user("token", db)
    assert user.auth_aal == "aal2"


async def test_claims_default_to_aal1() -> None:
    assert SupabaseClaims(sub="x").aal == "aal1"


# ── 3. role governance ───────────────────────────────────────────────────────

def test_only_registry_roles_are_assignable() -> None:
    with pytest.raises(ValidationError):
        UserCreateRequest(email="cfo@example.com", password="Passw0rd!", full_name="C F O", role="CFO")
    with pytest.raises(ValidationError):
        UserRoleUpdateRequest(role="Controller")
    for role in ASSIGNABLE_ROLES:
        assert UserRoleUpdateRequest(role=role).role == role
    assert "SME Reviewer" in ASSIGNABLE_ROLES


async def test_role_change_is_applied_and_audited(dbs) -> None:
    db, _ = dbs
    admin = await get_user_by_id(db, "admin-a")
    result = await patch_user_role("auditor-a", UserRoleUpdateRequest(role="SME Reviewer"), db, admin)
    assert result.role == "SME Reviewer"
    assert (await get_user_by_id(db, "auditor-a")).role == "SME Reviewer"
    [event] = await _events(db, "admin_permission_changed")
    assert event.actor_id == "admin-a"
    assert event.subject_id == "auditor-a"
    assert event.payload == {"previous_role": "System Auditor", "new_role": "SME Reviewer"}


async def test_admin_cannot_change_own_role(dbs) -> None:
    db, _ = dbs
    admin = await get_user_by_id(db, "admin-a")
    with pytest.raises(HTTPException) as exc:
        await patch_user_role("admin-a", UserRoleUpdateRequest(role="System Auditor"), db, admin)
    assert exc.value.status_code == 409
    assert (await get_user_by_id(db, "admin-a")).role == "Admin"


async def test_last_active_admin_cannot_be_demoted(dbs) -> None:
    db, _ = dbs
    # Through the API another active Admin always exists (self-change is
    # refused), so the guard is defence in depth for any other caller of the
    # service — e.g. a future bulk or scripted role change.
    second = await get_user_by_id(db, "admin-a2")
    second.is_active = False
    await db.commit()
    with pytest.raises(AccountChangeError, match="last active administrator"):
        await set_user_role(db, "admin-a", "tenant-a", "Risk Admin", actor_id="script")
    assert (await get_user_by_id(db, "admin-a")).role == "Admin"


async def test_admin_cannot_deactivate_themselves(dbs) -> None:
    db, _ = dbs
    admin = await get_user_by_id(db, "admin-a")
    with pytest.raises(HTTPException) as exc:
        await patch_user("admin-a", UserActiveUpdateRequest(is_active=False), db, admin)
    assert exc.value.status_code == 409
    assert (await get_user_by_id(db, "admin-a")).is_active is True


async def test_role_change_cannot_reach_another_tenant(dbs) -> None:
    db, _ = dbs
    admin = await get_user_by_id(db, "admin-a")
    with pytest.raises(HTTPException) as exc:
        await patch_user_role("admin-b", UserRoleUpdateRequest(role="System Auditor"), db, admin)
    assert exc.value.status_code == 404
    assert (await get_user_by_id(db, "admin-b")).role == "Admin"


# ── 4. invite-only sign-up ───────────────────────────────────────────────────

async def test_invite_only_refuses_unknown_signup(dbs, monkeypatch) -> None:
    db, _ = dbs
    monkeypatch.setattr("app.domains.identity.service.get_settings", lambda: _Settings(public_signup=False))
    claims = SupabaseClaims(sub="stranger", email="stranger@example.com")
    monkeypatch.setattr("app.domains.identity.router.verify_token", lambda token: claims)
    with pytest.raises(HTTPException) as exc:
        await provision(ProvisionRequest(company_name="Stranger Co"), db, "token")
    assert exc.value.status_code == 403
    assert await get_user_by_id(db, "stranger") is None
    tenants = (await db.execute(select(Tenant).where(Tenant.name == "Stranger Co"))).scalars().all()
    assert tenants == []


async def test_invite_only_still_provisions_invited_users(dbs, monkeypatch) -> None:
    db, _ = dbs
    monkeypatch.setattr("app.domains.identity.service.get_settings", lambda: _Settings(public_signup=False))
    claims = SupabaseClaims(sub="auditor-a", email="auditor-a@example.com", tenant_id="tenant-a", role="System Auditor")
    monkeypatch.setattr("app.domains.identity.router.verify_token", lambda token: claims)
    user = await provision(ProvisionRequest(), db, "token")
    assert user.id == "auditor-a"
    assert user.tenant_id == "tenant-a"


# ── 5. audit-ledger tenant isolation ─────────────────────────────────────────

async def _seed_ledger(db, sync_db) -> tuple[str, str]:
    a = await record_event_async(
        db, tenant_id="tenant-a", event_name="query_received", emitting_service="orchestration",
        actor_id="admin-a", subject_type="query", subject_id="q-shared", payload={},
    )
    b = await record_event_async(
        db, tenant_id="tenant-b", event_name="query_received", emitting_service="orchestration",
        actor_id="admin-b", subject_type="query", subject_id="q-shared", payload={"secret": "tenant-b"},
    )
    sync_db.add_all([
        SafetyEvent(tenant_id="tenant-a", event_type="risk_classified", query_id="q-shared", payload={}),
        SafetyEvent(tenant_id="tenant-b", event_type="risk_classified", query_id="q-shared", payload={"secret": "tenant-b"}),
    ])
    sync_db.commit()
    return a.id, b.id


async def test_event_list_never_includes_another_tenants_rows(dbs) -> None:
    db, sync_db = dbs
    await _seed_ledger(db, sync_db)
    events = await audit_service.list_events(db, sync_db, tenant_id="tenant-a")
    assert events, "tenant-a must still see its own events"
    assert {e["tenant_id"] for e in events} == {"tenant-a"}
    assert {e["source"] for e in events} == {"audit_ledger", "risk_safety_ledger"}


async def test_single_event_lookup_is_tenant_scoped(dbs) -> None:
    db, sync_db = dbs
    a_id, b_id = await _seed_ledger(db, sync_db)
    assert (await audit_service.get_event(db, a_id, "tenant-a")) is not None
    assert (await audit_service.get_event(db, b_id, "tenant-a")) is None


async def test_replay_manifest_is_tenant_scoped(dbs) -> None:
    db, sync_db = dbs
    await _seed_ledger(db, sync_db)
    manifest = await audit_service.get_replay_manifest(db, sync_db, "q-shared", "tenant-a")
    assert "tenant-b" not in repr(manifest)
    assert len(manifest["events"]) == 2, "tenant-a's own ledger + safety events must still replay"


async def test_corrections_cannot_cross_tenants(dbs) -> None:
    db, sync_db = dbs
    a_id, b_id = await _seed_ledger(db, sync_db)
    payload = CompensatingEventCreate(
        correction_type="metadata", correction_reason="typo", approver_id="admin-a2",
    )
    with pytest.raises(CompensatingEventError):
        await audit_service.issue_compensating_event(db, b_id, "admin-a", "tenant-a", payload)

    own = await audit_service.issue_compensating_event(db, a_id, "admin-a", "tenant-a", payload)
    db.add(CompensatingEvent(
        corrects_event_id=b_id, correction_type="metadata", correction_reason="b",
        issued_by="admin-b", approver_id="admin-b2",
    ))
    await db.commit()
    listed = await audit_service.list_compensating_events(db, "tenant-a")
    assert [row.id for row in listed] == [own.id]
