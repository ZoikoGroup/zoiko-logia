"""Section 4 — account lifecycle tests.

Covers the self-service and admin account operations the authorization layer
needs beyond sign-in:
  1. PATCH /auth/me — self-service profile edit, scoped to the caller's own
     row (no tenant_id parameter anywhere), with a matching audit event;
  2. POST /auth/sign-out-all-sessions — server-side revocation of every
     session via the Supabase Admin API (skipped when not configured), 204,
     audit event either way;
  3. POST /auth/mfa/enroll — deliberately a 501 stub (MFA pending a product
     decision); the attempt is still audited;
  4. /auth/provision binding — first creation earns exactly one audit event
     (idempotent re-provisions on every login stay quiet), and provisioning
     can never claim an existing tenant on someone else's behalf.
"""
from __future__ import annotations

import ast
import inspect

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.core.supabase_auth import SupabaseClaims
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Tenant, User
from app.domains.identity.router import mfa_enroll, patch_me, provision, sign_out_all_sessions
from app.domains.identity.schemas import ProfileUpdateRequest, ProvisionRequest
from app.domains.identity.service import get_user_by_id, update_own_profile

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def lifecycle_db():
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
            User(
                id="user-2", tenant_id="tenant-1", email="u2@example.com",
                first_name="Grace", last_name="Hopper", full_name="Grace Hopper",
                role="Accountant", is_active=True,
            ),
        ])
        await db.commit()
        yield db
    await engine.dispose()


async def _count_events(db, event_name: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.event_name == event_name)
    )
    return result.scalar_one()


async def _first_event(db, event_name: str) -> AuditEvent:
    result = await db.execute(
        select(AuditEvent).where(AuditEvent.event_name == event_name).order_by(AuditEvent.ingested_at.desc())
    )
    return result.scalars().first()


# ── PATCH /auth/me ────────────────────────────────────────────────────────────

async def test_patch_me_updates_only_own_profile(lifecycle_db) -> None:
    db = lifecycle_db
    current = await get_user_by_id(db, "user-1")
    result = await patch_me(ProfileUpdateRequest(first_name="Ada", last_name="King"), db, current)
    assert result.full_name == "Ada King"

    updated = await get_user_by_id(db, "user-1")
    assert updated.first_name == "Ada"
    assert updated.last_name == "King"
    assert updated.full_name == "Ada King"
    # Neighbouring row untouched.
    neighbour = await get_user_by_id(db, "user-2")
    assert neighbour.full_name == "Grace Hopper"


async def test_patch_me_rejects_all_blank_payload() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(first_name="", last_name="")


async def test_patch_me_has_no_tenant_scope_parameter() -> None:
    """The update is keyed purely by the caller's user id — there is no
    tenant_id argument anywhere in the handler, structurally ruling out
    editing someone else's (or another tenant's) row."""
    signature = inspect.signature(patch_me)
    assert {p.name for p in signature.parameters.values()} == {"payload", "db", "current_user"}
    assert "tenant_id" not in signature.parameters

    # Walk the actual code (not the docstring, which is a Constant, not a
    # Name node) for the service: the handler passes only the current user's
    # id, so the service needs no tenant scope.
    module_ast = ast.parse(inspect.getsource(update_own_profile))
    fn = module_ast.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    assert "tenant_id" not in [a.arg for a in fn.args.args]
    for node in ast.walk(fn):
        if isinstance(node, ast.Name):
            assert node.id != "tenant_id", f"service body reads tenant_id at {node.lineno}"


async def test_patch_me_unknown_user_returns_404_path(lifecycle_db) -> None:
    db = lifecycle_db
    assert await update_own_profile(db, "nobody", "A", "B") is None


async def test_patch_me_emits_profile_updated_event(lifecycle_db) -> None:
    db = lifecycle_db
    current = await get_user_by_id(db, "user-2")
    await patch_me(ProfileUpdateRequest(first_name="Grace", last_name="Murray Hopper"), db, current)

    event = await _first_event(db, "auth.profile_updated")
    assert event is not None
    assert event.actor_id == "user-2"
    assert event.subject_id == "user-2"
    assert event.tenant_id == "tenant-1"
    assert "last_name" in event.payload["fields_changed"]


# ── POST /auth/sign-out-all-sessions ─────────────────────────────────────────

async def test_sign_out_all_calls_admin_revocation(lifecycle_db, monkeypatch) -> None:
    db = lifecycle_db
    revoked: list[str] = []

    monkeypatch.setattr("app.core.supabase_admin.is_configured", lambda: True)
    monkeypatch.setattr("app.core.supabase_admin.revoke_all_sessions", lambda uid: revoked.append(uid) or True)
    current = await get_user_by_id(db, "user-1")

    resp = await sign_out_all_sessions(db, current)
    assert isinstance(resp, Response)
    assert resp.status_code == 204
    assert revoked == ["user-1"]


async def test_sign_out_all_still_204_when_not_configured(lifecycle_db, monkeypatch) -> None:
    db = lifecycle_db

    def fail_if_called(uid):
        raise AssertionError("revoke_all_sessions must not be called when Supabase is unconfigured")

    monkeypatch.setattr("app.core.supabase_admin.is_configured", lambda: False)
    monkeypatch.setattr("app.core.supabase_admin.revoke_all_sessions", fail_if_called)
    current = await get_user_by_id(db, "user-1")

    resp = await sign_out_all_sessions(db, current)
    assert resp.status_code == 204


async def test_sign_out_all_emits_sessions_revoked_event(lifecycle_db, monkeypatch) -> None:
    db = lifecycle_db
    monkeypatch.setattr("app.core.supabase_admin.is_configured", lambda: True)
    monkeypatch.setattr("app.core.supabase_admin.revoke_all_sessions", lambda uid: True)
    current = await get_user_by_id(db, "user-1")

    await sign_out_all_sessions(db, current)
    event = await _first_event(db, "auth.sessions_revoked")
    assert event is not None
    assert event.actor_id == "user-1"
    assert event.subject_id == "user-1"
    assert event.tenant_id == "tenant-1"


# ── POST /auth/mfa/enroll (stub) ─────────────────────────────────────────────

async def test_mfa_enroll_is_not_implemented(lifecycle_db) -> None:
    db = lifecycle_db
    current = await get_user_by_id(db, "user-1")
    with pytest.raises(HTTPException) as exc:
        await mfa_enroll(db, current)
    assert exc.value.status_code == 501


async def test_mfa_enroll_attempt_is_audited(lifecycle_db) -> None:
    db = lifecycle_db
    current = await get_user_by_id(db, "user-1")
    try:
        await mfa_enroll(db, current)
    except HTTPException:
        pass
    event = await _first_event(db, "auth.mfa_enroll_attempted")
    assert event is not None
    assert event.payload.get("rejected_reason") == "not_implemented"


# ── /auth/provision binding ──────────────────────────────────────────────────

async def test_provision_emits_exactly_one_event_across_re_provisions(lifecycle_db, monkeypatch) -> None:
    db = lifecycle_db
    monkeypatch.setattr("app.core.supabase_admin.update_app_metadata", lambda uid, tid, role: None)
    claims = SupabaseClaims(sub="fresh-user", email="fresh@example.com")
    monkeypatch.setattr("app.domains.identity.router.verify_token", lambda token: claims)

    await provision(ProvisionRequest(first_name="New", last_name="Hire", company_name="ACME"), db, "token-a")
    await provision(ProvisionRequest(), db, "token-a")

    assert await _count_events(db, "auth.provisioned") == 1
    event = await _first_event(db, "auth.provisioned")
    assert event.actor_id == "fresh-user"
    assert event.payload.get("first_time") is True


async def test_provision_cannot_claim_existing_tenant(lifecycle_db, monkeypatch) -> None:
    """Provisioning is bound to the token's own subject — a second user's
    token creates a brand-new tenant and can never join/claim the first
    user's tenant. There is no tenant reference in the request to target."""
    db = lifecycle_db
    monkeypatch.setattr("app.core.supabase_admin.update_app_metadata", lambda uid, tid, role: None)

    for sub, email in (("sub-a", "a@example.com"), ("sub-b", "b@example.com")):
        claims = SupabaseClaims(sub=sub, email=email)
        monkeypatch.setattr("app.domains.identity.router.verify_token", lambda token, claims=claims: claims)
        await provision(ProvisionRequest(company_name="ACME Ltd"), db, "token-x")

    user_a = await get_user_by_id(db, "sub-a")
    user_b = await get_user_by_id(db, "sub-b")
    assert user_a.tenant_id != user_b.tenant_id
    # The fixture already has tenant-1; each provisioned user owns exactly
    # its own new tenant with exactly one member — nothing claimed or shared.
    members_a = (await db.execute(select(func.count()).select_from(User).where(User.tenant_id == user_a.tenant_id))).scalar_one()
    assert members_a == 1
    assertions = {"sub-a": user_a, "sub-b": user_b}
    for sub, user in assertions.items():
        assert user.id == sub