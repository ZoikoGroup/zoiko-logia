"""Section 1 — authorization-layer tests on top of the existing suite.

Covers the pieces the backend already ships, so later sections (permission
registry, account lifecycle, audit trail) have a regression net:
  1. token verification (verify_token): fail-closed on every PyJWT failure,
     real RS256/ES256 signature check against a stubbed JWKS fetch;
  2. get_current_user / require_admin dependencies — every 401 path and the
     403 for non-Admin roles, plus the happy path;
  3. /auth/provision — first call creates the Tenant + Admin profile row,
     repeats are idempotent (no second row), and the Admin-API write that
     stamps tenant_id/role into app_metadata is called with the right args;
  4. the users-table RLS guarantee (self-row or tenant-admin, FORCED) both
     structurally (runs everywhere) and, against a live Postgres with the
     app's RLS setup applied, functionally (mirrors test_tenant_isolation's
     standalone skip-under-SQLite pattern).
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives import serialization
import jwt
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main as main_module
from app.db.base import Base
from app.core.database import AsyncSessionLocal, RequestSessionLocal
from app.core import supabase_auth
from app.core.config import get_settings
from app.domains.identity.models import Tenant, User
from app.domains.identity.rbac import get_current_user, require_admin
from app.domains.identity.router import provision
from app.domains.identity.schemas import ProvisionRequest

settings = get_settings()


# ── helpers: real keys, stubbed JWKS fetch ───────────────────────────────────

def _private_pem(key) -> str:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _public_pem(key) -> str:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _make_token(
    *,
    signing_key,
    algorithm: str = "RS256",
    sub: str = "user-abc123",
    email: str | None = "ada@example.com",
    app_metadata: dict | None = {"tenant_id": "tenant-1", "role": "Admin"},
    audience: str = "authenticated",
    exp_delta: timedelta = timedelta(hours=1),
    extra: dict | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict = {
        "iss": "https://example.supabase.co/auth/v1",
        "sub": sub,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + exp_delta).timestamp()),
    }
    if email is not None:
        payload["email"] = email
    if app_metadata is not None:
        payload["app_metadata"] = app_metadata
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _private_pem(signing_key), algorithm=algorithm)


class _FakeSigningKey:
    def __init__(self, pem: str) -> None:
        self.key = pem


class _FakeJwksClient:
    """Stands in for PyJWKClient's network-fetched key without touching the
    network — signature verification below is still real PyJWT against the
    actual public key."""

    def __init__(self, public_pem: str) -> None:
        self._pem = public_pem

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(self._pem)


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def ec_key():
    return ec.generate_private_key(curve=ec.SECP256R1())


@pytest.fixture
def jwks_hooked(rsa_key, monkeypatch) -> None:
    monkeypatch.setattr(supabase_auth, "_get_jwks_client", lambda: _FakeJwksClient(_public_pem(rsa_key)))


# ── verify_token ─────────────────────────────────────────────────────────────

async def test_verify_token_accepts_valid_rs256_token(rsa_key, jwks_hooked) -> None:
    token = _make_token(signing_key=rsa_key)
    claims = supabase_auth.verify_token(token)
    assert claims is not None
    assert claims.sub == "user-abc123"
    assert claims.email == "ada@example.com"
    assert claims.tenant_id == "tenant-1"
    assert claims.role == "Admin"


async def test_verify_token_accepts_valid_es256_token(ec_key, rsa_key, monkeypatch) -> None:
    monkeypatch.setattr(supabase_auth, "_get_jwks_client", lambda: _FakeJwksClient(_public_pem(ec_key)))
    token = _make_token(signing_key=ec_key, algorithm="ES256")
    claims = supabase_auth.verify_token(token)
    assert claims is not None
    assert claims.sub == "user-abc123"


async def test_verify_token_rejects_expired_token(rsa_key, jwks_hooked) -> None:
    token = _make_token(signing_key=rsa_key, exp_delta=timedelta(hours=-1))
    assert supabase_auth.verify_token(token) is None


async def test_verify_token_rejects_wrong_audience(rsa_key, jwks_hooked) -> None:
    token = _make_token(signing_key=rsa_key, audience="service_role")
    assert supabase_auth.verify_token(token) is None


async def test_verify_token_rejects_signature_from_different_key(rsa_key, jwks_hooked) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_token(signing_key=other_key)
    assert supabase_auth.verify_token(token) is None


async def test_verify_token_rejects_none_algorithm(rsa_key, jwks_hooked) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "https://example.supabase.co/auth/v1",
        "sub": "user-abc123",
        "aud": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, key=None, algorithm="none")
    assert supabase_auth.verify_token(token) is None


async def test_verify_token_rejects_malformed_token(rsa_key, jwks_hooked) -> None:
    assert supabase_auth.verify_token("not.a.jwt") is None


async def test_verify_token_returns_none_when_supabase_unconfigured(rsa_key, monkeypatch) -> None:
    monkeypatch.setattr(supabase_auth, "_get_jwks_client", lambda: None)
    token = _make_token(signing_key=rsa_key)
    assert supabase_auth.verify_token(token) is None


async def test_verify_token_tolerates_missing_app_metadata(rsa_key, jwks_hooked) -> None:
    token = _make_token(signing_key=rsa_key, app_metadata=None)
    claims = supabase_auth.verify_token(token)
    assert claims is not None
    assert claims.email == "ada@example.com"
    assert claims.tenant_id == ""
    assert claims.role == ""


async def test_verify_token_tolerates_missing_email(rsa_key, jwks_hooked) -> None:
    token = _make_token(signing_key=rsa_key, email=None)
    claims = supabase_auth.verify_token(token)
    assert claims is not None
    assert claims.email is None


# ── get_current_user / require_admin dependencies ────────────────────────────

@pytest.fixture
async def user_db():
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
                role="Accountant", is_active=False,
            ),
            User(
                id="user-3", tenant_id="tenant-1", email="u3@example.com",
                first_name="Katherine", last_name="Johnson", full_name="Katherine Johnson",
                role="Accountant", is_active=True,
            ),
        ])
        await db.commit()
        yield db
    await engine.dispose()


async def test_get_current_user_missing_token_returns_401(user_db) -> None:
    with pytest.raises(HTTPException) as exc:
        await get_current_user(None, user_db)
    assert exc.value.status_code == 401


async def test_get_current_user_invalid_token_returns_401(user_db, monkeypatch) -> None:
    monkeypatch.setattr("app.domains.identity.rbac.verify_token", lambda token: None)
    with pytest.raises(HTTPException) as exc:
        await get_current_user("garbage", user_db)
    assert exc.value.status_code == 401


async def test_get_current_user_unprovisioned_account_returns_401(user_db, monkeypatch) -> None:
    claims = supabase_auth.SupabaseClaims(sub="never-provisioned", email="new@example.com")
    monkeypatch.setattr("app.domains.identity.rbac.verify_token", lambda token: claims)
    with pytest.raises(HTTPException) as exc:
        await get_current_user("anything", user_db)
    assert exc.value.status_code == 401
    assert "provisioned" in exc.value.detail


async def test_get_current_user_inactive_user_returns_401(user_db, monkeypatch) -> None:
    claims = supabase_auth.SupabaseClaims(sub="user-2", email="u2@example.com")
    monkeypatch.setattr("app.domains.identity.rbac.verify_token", lambda token: claims)
    with pytest.raises(HTTPException) as exc:
        await get_current_user("anything", user_db)
    assert exc.value.status_code == 401


async def test_get_current_user_returns_loaded_user(user_db, monkeypatch) -> None:
    claims = supabase_auth.SupabaseClaims(sub="user-1", email="u1@example.com")
    monkeypatch.setattr("app.domains.identity.rbac.verify_token", lambda token: claims)
    user = await get_current_user("anything", user_db)
    assert user.id == "user-1"
    assert user.email == "u1@example.com"
    assert user.role == "Admin"


async def test_require_admin_grants_admin_role(user_db, monkeypatch) -> None:
    claims = supabase_auth.SupabaseClaims(sub="user-1", email="u1@example.com")
    monkeypatch.setattr("app.domains.identity.rbac.verify_token", lambda token: claims)
    user = await require_admin(await get_current_user("anything", user_db))
    assert user.role == "Admin"


async def test_require_admin_forbids_non_admin_role(user_db, monkeypatch) -> None:
    claims = supabase_auth.SupabaseClaims(sub="user-3", email="u3@example.com")
    monkeypatch.setattr("app.domains.identity.rbac.verify_token", lambda token: claims)
    current = await get_current_user("anything", user_db)
    with pytest.raises(HTTPException) as exc:
        await require_admin(current)
    assert exc.value.status_code == 403
    assert exc.value.detail == "Admin role required"


# ── /auth/provision: first call creates, repeats are no-ops ──────────────────

@pytest.fixture
async def provision_db(monkeypatch):
    """In-memory DB + stubbed Auth writes for the provision handler. The
    Supabase Admin API write (app_metadata) is captured, never sent over the
    wire."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    captured: list[tuple[str, str, str]] = []
    monkeypatch.setattr("app.core.supabase_admin.update_app_metadata", lambda uid, tid, role: captured.append((uid, tid, role)))
    async with session_factory() as db:
        yield db, captured
    await engine.dispose()


def _stub_claims(monkeypatch, *, sub="user-abc123", email="ada@example.com"):
    claims = supabase_auth.SupabaseClaims(sub=sub, email=email)
    monkeypatch.setattr("app.domains.identity.router.verify_token", lambda token: claims)


async def test_provision_creates_tenant_and_admin_profile(provision_db, monkeypatch) -> None:
    db, captured = provision_db
    _stub_claims(monkeypatch)
    payload = ProvisionRequest(first_name="Ada", last_name="Lovelace", company_name="ACME Ltd")
    result = await provision(payload, db, "token-xyz")

    assert result.email == "ada@example.com"
    assert result.full_name == "Ada Lovelace"
    assert result.role == "Admin"
    assert result.tenant_id != ""
    assert len(captured) == 1
    uid, tid, role = captured[0]
    assert uid == result.id
    assert tid == result.tenant_id
    assert role == "Admin"


async def test_provision_is_idempotent(provision_db, monkeypatch) -> None:
    db, captured = provision_db
    _stub_claims(monkeypatch)
    payload = ProvisionRequest(first_name="Ada", last_name="Lovelace", company_name="ACME Ltd")
    first = await provision(payload, db, "token-xyz")
    second = await provision(payload, db, "token-xyz")

    assert second.id == first.id
    assert second.tenant_id == first.tenant_id
    tenant_count = (await db.execute(select(func.count()).select_from(Tenant))).scalar_one()
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    assert tenant_count == 1
    assert user_count == 1
    # Only the first call reaches the Supabase Admin API.
    assert len(captured) == 1


async def test_provision_rejects_missing_token(provision_db) -> None:
    db, _ = provision_db
    with pytest.raises(HTTPException) as exc:
        await provision(ProvisionRequest(), db, None)
    assert exc.value.status_code == 401


async def test_provision_rejects_invalid_claims(provision_db, monkeypatch) -> None:
    db, _ = provision_db
    claims = supabase_auth.SupabaseClaims(sub="user-abc123", email=None)
    monkeypatch.setattr("app.domains.identity.router.verify_token", lambda token: claims)
    with pytest.raises(HTTPException) as exc:
        await provision(ProvisionRequest(), db, "token-xyz")
    assert exc.value.status_code == 401


# ── users-table RLS: self-row or tenant-admin, never cross-tenant ────────────

def test_user_rls_policy_is_self_or_tenant_admin() -> None:
    """Structural guarantee, runnable everywhere: the policy set at startup
    must scope reads to the caller's own row (or, for a tenant Admin, their
    own tenant) and must be FORCEd so RLS cannot be bypassed by table
    ownership — the same self-row isolation the earlier F1 fixtures assume."""
    source = inspect.getsource(main_module._setup_user_rls)
    assert "current_setting('app.user_id', true)" in source
    assert "_is_requester_tenant_admin(tenant_id)" in source
    assert "FORCE ROW LEVEL SECURITY" in source


async def _count_visible_users(user_id: str, tenant_id: str) -> list[str]:
    async with RequestSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": user_id})
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
        result = await db.execute(text("SELECT id FROM users"))
        return [row[0] for row in result.all()]


async def test_non_admin_cannot_read_another_users_row() -> None:
    """Functional check against live Postgres with the app's RLS setup applied
    (docker compose exec backend python -m pytest tests/test_auth.py)."""
    if settings.is_sqlite:
        print("test_non_admin_cannot_read_another_users_row: SKIPPED (SQLite has no RLS)")
        return

    async with AsyncSessionLocal() as db:
        caller_tenant = Tenant(name="RLS Caller Tenant")
        other_tenant = Tenant(name="RLS Other Tenant")
        db.add_all([caller_tenant, other_tenant])
        await db.flush()

        caller = User(tenant_id=caller_tenant.id, email="caller@rls.local", full_name="RLS Caller", role="Staff")
        other = User(tenant_id=other_tenant.id, email="other@rls.local", full_name="RLS Other", role="Staff")
        db.add_all([caller, other])
        await db.commit()
        caller_id, other_id, caller_tid, other_tid = caller.id, other.id, caller_tenant.id, other_tenant.id

    try:
        visible = await _count_visible_users(caller_id, caller_tid)
        assert caller_id in visible
        assert other_tid not in visible
        other_visible = await _count_visible_users(other_id, other_tid)
        assert caller_id not in other_visible, "cross-tenant users row read through RLS"
        assert other_id in other_visible
        print("test_non_admin_cannot_read_another_users_row: PASSED")
    finally:
        async with AsyncSessionLocal() as db:
            for tid in (caller_tid, other_tid):
                await db.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": tid})
                await db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
            await db.commit()