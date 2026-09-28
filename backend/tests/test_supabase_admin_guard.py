"""Fail-closed regression guard for the Supabase Admin API.

Root cause this pins: with SUPABASE_SERVICE_ROLE_KEY empty, _headers() built
"Bearer " (trailing space, no token) and httpx rejected it at the transport
layer with httpx.LocalProtocolError, surfacing as an unhandled 500 from
/auth/provision with no actionable signal. Every admin-API function must now
raise SupabaseNotConfiguredError BEFORE assembling a request. Provisioning is
the one exception by design: the local profile row commits first and the
app_metadata stamp is best-effort, so a missing service-role key must not
brick first login.
"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import supabase_admin
from app.core.config import get_settings
from app.core.supabase_auth import SupabaseClaims
from app.db.base import Base
from app.domains.identity.router import provision
from app.domains.identity.schemas import ProvisionRequest
from app.domains.identity.service import provision_profile

settings = get_settings()

ADMIN_FUNCTIONS = {
    "create_user": ("a@example.com", "pw"),
    "get_user_by_email": ("a@example.com",),
    "revoke_all_sessions": ("user-1",),
    "update_app_metadata": ("user-1", "tenant-1", "Admin"),
}


def _unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")


def _configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "dummy-service-jwt")


def _no_transport(monkeypatch) -> None:
    """Any real httpx call means a guard leaked past the boundary."""

    def _explode(*args, **kwargs):
        raise AssertionError("admin-API guard leaked into a real httpx request")

    for name in ("post", "get", "put", "delete"):
        monkeypatch.setattr(httpx, name, _explode)


# ── is_configured() definition + the typed exception it gates ────────────────

def test_is_configured_definition_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")
    assert supabase_admin.is_configured() is False

    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "dummy-service-jwt")
    assert supabase_admin.is_configured() is True

    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    assert supabase_admin.is_configured() is False

    with pytest.raises(supabase_admin.SupabaseNotConfiguredError):
        supabase_admin.update_app_metadata("user-1", "tenant-1", "Admin")


# ── every admin function fails closed, no transport attempt ──────────────────

@pytest.mark.parametrize("func_name", list(ADMIN_FUNCTIONS))
def test_every_admin_function_raises_typed_error_when_unconfigured(
    monkeypatch, func_name: str
) -> None:
    _unconfigured(monkeypatch)
    _no_transport(monkeypatch)
    func = getattr(supabase_admin, func_name)
    with pytest.raises(supabase_admin.SupabaseNotConfiguredError):
        func(*ADMIN_FUNCTIONS[func_name])


def test_update_app_metadata_performs_request_when_configured(monkeypatch) -> None:
    _configured(monkeypatch)
    sent: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"ok": True}

    def fake_put(url, *, headers, json, timeout):
        sent.update(url=url, headers=headers, json=json, timeout=timeout)
        return _Resp()

    monkeypatch.setattr(httpx, "put", fake_put)
    result = supabase_admin.update_app_metadata("user-1", "tenant-1", "Accountant")

    assert result == {"ok": True}
    assert sent["url"] == "https://example.supabase.co/auth/v1/admin/users/user-1"
    assert sent["headers"]["apikey"] == "dummy-service-jwt"
    assert sent["headers"]["Authorization"] == "Bearer dummy-service-jwt"
    assert sent["json"] == {"app_metadata": {"tenant_id": "tenant-1", "role": "Accountant"}}


# ── /auth/provision: succeeds without the service-role key ───────────────────
# The app_metadata stamp is best-effort by design (the local profile row is the
# source of truth). Provisioning must NOT 503 when SUPABASE_SERVICE_ROLE_KEY is
# absent — that exact failure is what previously made every login error out on
# the FIRST sign-in even though the token verified cleanly.

@pytest.fixture
async def fresh_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        yield db
    await engine.dispose()


async def test_provision_succeeds_when_admin_not_configured(fresh_db, monkeypatch) -> None:
    _unconfigured(monkeypatch)
    _no_transport(monkeypatch)
    claims = SupabaseClaims(sub="user-abc123", email="ada@example.com")
    monkeypatch.setattr("app.domains.identity.router.verify_token", lambda token: claims)

    user = await provision(
        ProvisionRequest(first_name="Ada", last_name="Lovelace", company_name="ACME"),
        fresh_db,
        "token-xyz",
    )
    assert user.id == "user-abc123"
    assert user.email == "ada@example.com"
    assert user.role == "Admin"


async def test_provision_profile_commits_row_when_admin_not_configured(fresh_db, monkeypatch) -> None:
    _unconfigured(monkeypatch)
    _no_transport(monkeypatch)
    user = await provision_profile(
        fresh_db,
        "user-abc123",
        "ada@example.com",
        ProvisionRequest(first_name="Ada", last_name="Lovelace", company_name="ACME"),
    )
    assert user.id == "user-abc123"

    from app.domains.identity.service import get_user_by_id
    persisted = await get_user_by_id(fresh_db, "user-abc123")
    assert persisted is not None
    assert persisted.role == "Admin"