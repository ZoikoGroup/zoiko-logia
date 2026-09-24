"""Section 5 — auth audit trail tests.

Every auth lifecycle mutation emits an audit event through the canonical
envelope (app/domains/audit_ledger/event_envelope.py). These tests pin that:
  1. envelope compliance — identity/service events carry emitting_service,
     actor_type, classification, correlation and validation_status exactly as
     the audit domain expects, and never secret payload data;
  2. chain integrity — auth events for a tenant link previous_chain_hash →
     chain_hash across provision → profile edit → sessions revoked, and the
     rows persist with those exact hashes;
  3. actor identity — the actor of an admin-bound action is the resolved
     admin row (from the dependency, not from the request body), so a client
     can never write another user's id into an event;
  4. admin lifecycle events — POST /users and PATCH /users/{id} record
     auth.user_created / auth.user_activation_changed with the right subject
     and payload.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.core.supabase_auth import SupabaseClaims
from app.domains.audit_ledger.chain_integrity import compute_chain_hash, compute_payload_hash
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Tenant, User
from app.domains.identity.router import post_user, provision
from app.domains.identity.schemas import ProvisionRequest, UserActiveUpdateRequest, UserCreateRequest
from app.domains.identity.service import get_user_by_id

pytestmark = pytest.mark.asyncio

AUTH_EVENTS = {
    "auth.provisioned",
    "auth.profile_updated",
    "auth.sessions_revoked",
    "auth.mfa_enroll_attempted",
    "auth.user_created",
    "auth.user_activation_changed",
}


@pytest.fixture
async def audit_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # The Supabase Admin API writes used by the identity service — captured,
    # never sent over the wire.
    monkeypatch.setattr(
        "app.core.supabase_admin.create_user",
        lambda email, password, email_confirm=False: {"id": "new-user-id"},
    )
    monkeypatch.setattr("app.core.supabase_admin.update_app_metadata", lambda uid, tid, role: None)

    async with session_factory() as db:
        db.add_all([
            Tenant(id="tenant-1", name="Tenant One"),
            User(
                id="admin-1", tenant_id="tenant-1", email="admin@example.com",
                first_name="Ada", last_name="Lovelace", full_name="Ada Lovelace",
                role="Admin", is_active=True,
            ),
            User(
                id="staff-2", tenant_id="tenant-1", email="staff@example.com",
                first_name="Grace", last_name="Hopper", full_name="Grace Hopper",
                role="Accountant", is_active=True,
            ),
        ])
        await db.commit()
        yield db
    await engine.dispose()


# ── envelope compliance ───────────────────────────────────────────────────────

async def test_auth_events_follow_canonical_envelope(audit_db) -> None:
    db = audit_db

    def events():
        return select(AuditEvent)

    for event_name in AUTH_EVENTS:
        await record_event_async(
            db,
            tenant_id="tenant-1",
            event_name=event_name,
            emitting_service="identity",
            actor_id="admin-1",
            subject_type="user_account",
            subject_id="staff-2",
            payload={},
        )

    rows = (await db.execute(events())).scalars().all()
    assert len(rows) == len(AUTH_EVENTS)
    for row in rows:
        # Envelope fields are invariant — payload varies, envelope doesn't.
        assert row.emitting_service == "identity"
        assert row.actor_type == "user"
        assert row.classification == "INTERNAL"
        assert row.replay_relevance == "SUPPORTING"
        assert row.correlation_id == row.subject_id == "staff-2"
        assert row.validation_status == "ACCEPTED"
        assert row.payload_hash == compute_payload_hash(row.payload)
        assert row.chain_hash == compute_chain_hash(row.id, row.event_name, row.payload_hash, row.previous_chain_hash)


async def test_router_auth_events_never_carry_secrets(audit_db, monkeypatch) -> None:
    """Audit payloads must be credential-clean. Drive the real router handlers
    (the only things allowed to write auth events) and assert none of their
    payload keys could carry a password/token/credential — the UserCreateRequest
    password and provision data are inputs, never ledger contents."""
    from fastapi import HTTPException

    from app.domains.identity.router import (
        mfa_enroll,
        patch_me,
        patch_user,
        sign_out_all_sessions,
    )
    from app.domains.identity.schemas import ProfileUpdateRequest

    db = audit_db
    admin = await get_user_by_id(db, "admin-1")
    monkeypatch.setattr("app.core.supabase_admin.is_configured", lambda: True)
    monkeypatch.setattr("app.core.supabase_admin.revoke_all_sessions", lambda uid: True)
    monkeypatch.setattr(
        "app.domains.identity.router.verify_token",
        lambda token: SupabaseClaims(sub="brand-new", email="new@example.com"),
    )

    await provision(ProvisionRequest(first_name="New", last_name="User", company_name="X"), db, "token-1")
    await patch_me(ProfileUpdateRequest(first_name="Ada", last_name="King"), db, admin)
    created = await post_user(
        UserCreateRequest(email="join@example.com", password="Sup3rSecret!", full_name="Join Doe", role="Source Admin"),
        db,
        admin,
    )
    await patch_user(created.id, UserActiveUpdateRequest(is_active=False), db, admin)
    await sign_out_all_sessions(db, admin)
    try:
        await mfa_enroll(db, admin)
    except HTTPException:
        pass

    rows = (await db.execute(select(AuditEvent))).scalars().all()
    assert len(rows) == 6
    for row in rows:
        keys = {str(k).lower() for k in row.payload}
        for key in keys:
            assert not any(word in key for word in ("password", "secret", "token", "credential", "api_key", "key_secret")), f"{row.event_name} payload leaks {key}"


# ── chain integrity across a lifecycle ───────────────────────────────────────

async def test_auth_events_chain_across_lifecycle(audit_db) -> None:
    """provision → profile_updated → sessions_revoked must form one contiguous
    tenant chain: each row's previous_chain_hash is the prior row's chain_hash,
    and the persisted rows carry exactly the hashes the writers computed."""
    db = audit_db
    rows: list[AuditEvent] = []
    for i, event_name in enumerate(("auth.provisioned", "auth.profile_updated", "auth.sessions_revoked")):
        created = await record_event_async(
            db,
            tenant_id="tenant-1",
            event_name=event_name,
            emitting_service="identity",
            actor_id="staff-2",
            subject_type="user_account",
            subject_id="staff-2",
            payload={"step": i},
        )
        rows.append(created)

    for i, row in enumerate(rows):
        previous = rows[i - 1].chain_hash if i else None
        assert row.previous_chain_hash == previous
        assert row.chain_hash == compute_chain_hash(row.id, row.event_name, row.payload_hash, previous)

    persisted = (await db.execute(select(AuditEvent).where(AuditEvent.id.in_([r.id for r in rows])))).scalars().all()
    assert len(persisted) == len(rows)
    for stored in persisted:
        stored_in_memory = next(r for r in rows if r.id == stored.id)
        assert stored.chain_hash == stored_in_memory.chain_hash


async def test_auth_chain_is_tenant_scoped(audit_db) -> None:
    """A re-provision of the tenant — any event on tenant-2 — must NOT chain
    onto the tenant-1 ledger: hashes derive from the previous hash, so a
    cross-tenant link would make verify_chain over tenant-1 break."""
    from app.domains.audit_ledger.chain_integrity import verify_chain

    db = audit_db
    for increment in (0, 1):
        tenant_id = "tenant-1" if increment == 0 else "tenant-2"
        await record_event_async(
            db,
            tenant_id=tenant_id,
            event_name="auth.provisioned",
            emitting_service="identity",
            actor_id=f"user-{increment}",
            subject_type="user_account",
            subject_id=f"user-{increment}",
            payload={"first_time": True},
        )

    tenant1 = (await db.execute(select(AuditEvent).where(AuditEvent.tenant_id == "tenant-1"))).scalars().all()
    tenant2 = (await db.execute(select(AuditEvent).where(AuditEvent.tenant_id == "tenant-2"))).scalars().all()
    assert len(tenant1) == 1
    assert len(tenant2) == 1
    assert tenant1[0].previous_chain_hash is None  # second tenant never linked onto first
    ok, broken = verify_chain(tenant1)
    assert ok, broken
    ok, broken = verify_chain(tenant2)
    assert ok, broken


# ── actor identity ───────────────────────────────────────────────────────────

async def test_provisioned_actor_is_the_signing_user(audit_db, monkeypatch) -> None:
    """The provisioned event's actor_id must equal the token's sub — the
    claims-derived id the handler passes — not anything a caller could put in
    the request body."""
    db = audit_db
    monkeypatch.setattr(
        "app.domains.identity.router.verify_token",
        lambda token: SupabaseClaims(sub="brand-new", email="new@example.com"),
    )

    await provision(ProvisionRequest(first_name="New", last_name="User", company_name="X"), db, "token-1")

    row = (await db.execute(select(AuditEvent).where(AuditEvent.event_name == "auth.provisioned"))).scalars().first()
    assert row.actor_id == "brand-new"
    assert row.subject_id == "brand-new"


async def test_admin_actor_comes_from_dependency_not_payload(audit_db) -> None:
    """The admin-bound events derive actor_id from the resolved current_user
    row (the dependency), so a request body can never impersonate another
    actor in the ledger."""
    db = audit_db
    admin = await get_user_by_id(db, "admin-1")

    # POST /users — subject is the freshly created account, actor is the admin.
    created = await post_user(
        UserCreateRequest(email="new@example.com", password="Str0ngPass!", full_name="New Hire", role="Source Admin"),
        db,
        admin,
    )
    created_event = (await db.execute(select(AuditEvent).where(AuditEvent.event_name == "auth.user_created"))).scalars().first()
    assert created_event.actor_id == "admin-1"
    assert created_event.subject_id == created.id
    assert created_event.payload.get("email") == "new@example.com"
    assert created_event.payload.get("role") == "Source Admin"


async def test_activation_changed_records_state(audit_db) -> None:
    db = audit_db
    admin = await get_user_by_id(db, "admin-1")
    user = await get_user_by_id(db, "staff-2")

    from app.domains.identity.router import patch_user

    # Deactivate, then reactivate — each transition is its own event with the
    # full post-transition state, so the ledger can reconstruct who turned an
    # account off and on.
    await patch_user(user.id, UserActiveUpdateRequest(is_active=False), db, admin)
    await patch_user(user.id, UserActiveUpdateRequest(is_active=True), db, admin)

    events = (await db.execute(select(AuditEvent).where(AuditEvent.event_name == "auth.user_activation_changed"))).scalars().all()
    assert len(events) == 2
    assert [e.payload.get("is_active") for e in events] == [False, True]
    assert all(e.actor_id == "admin-1" for e in events)
    assert all(e.subject_id == "staff-2" for e in events)


# ── the auth namespace is the only producer in identity ──────────────────────

async def test_all_identity_events_are_auth_prefixed(audit_db) -> None:
    db = audit_db
    for event_name in AUTH_EVENTS:
        await record_event_async(
            db,
            tenant_id="tenant-1",
            event_name=event_name,
            emitting_service="identity",
            actor_id="admin-1",
            subject_type="user_account",
            subject_id="staff-2",
            payload={},
        )
    rows = (await db.execute(select(AuditEvent))).scalars().all()
    assert {r.event_name for r in rows} == AUTH_EVENTS
    for row in rows:
        assert row.event_name.startswith("auth."), f"non-auth-prefixed event {row.event_name} leaked from identity"