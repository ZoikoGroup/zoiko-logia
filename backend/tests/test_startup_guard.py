"""Regression guard for the env-config class of failure where the backend
started with no SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY: token verification
fails closed, so every authenticated endpoint 401s and default-user seeding is
silently skipped. The strict gate is opt-in (REQUIRE_SUPABASE_CONFIG=true) —
local/dev keeps the soft warning + skip-seeding behavior — so these tests pin
both sides of the flag.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings
from app.main import _require_supabase_config

settings = get_settings()


@pytest.fixture(autouse=True)
def _reset_flag():
    original = settings.REQUIRE_SUPABASE_CONFIG
    yield
    settings.REQUIRE_SUPABASE_CONFIG = original


def test_local_mode_allows_startup_when_unconfigured(monkeypatch) -> None:
    """Default (flag unset) is the current soft behavior: no hard failure
    when Supabase isn't configured — this is intentional for plain-SQLite
    dev and frontend-only contributors."""
    settings.REQUIRE_SUPABASE_CONFIG = False
    monkeypatch.setattr("app.core.supabase_admin.is_configured", lambda: False)
    _require_supabase_config()  # must not raise


def test_local_mode_ok_when_configured(monkeypatch) -> None:
    settings.REQUIRE_SUPABASE_CONFIG = False
    monkeypatch.setattr("app.core.supabase_admin.is_configured", lambda: True)
    _require_supabase_config()  # must not raise


def test_strict_mode_aborts_startup_when_unconfigured(monkeypatch) -> None:
    """Staging/prod with the flag on gets a loud, at-the-gateway failure."""
    settings.REQUIRE_SUPABASE_CONFIG = True
    monkeypatch.setattr("app.core.supabase_admin.is_configured", lambda: False)
    with pytest.raises(RuntimeError) as exc:
        _require_supabase_config()
    assert "SUPABASE_SERVICE_ROLE_KEY" in str(exc.value)
    assert "SUPABASE_URL" in str(exc.value)


def test_strict_mode_passes_when_configured(monkeypatch) -> None:
    settings.REQUIRE_SUPABASE_CONFIG = True
    monkeypatch.setattr("app.core.supabase_admin.is_configured", lambda: True)
    _require_supabase_config()  # must not raise


@pytest.mark.parametrize("failed_step", ["_setup_source_rls", "_setup_user_rls", None])
async def test_startup_requires_security_policies_and_never_creates_accounts(monkeypatch, failed_step):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, Mock
    from app import main

    @asynccontextmanager
    async def connection():
        yield Mock(run_sync=AsyncMock())

    monkeypatch.setattr(main, "async_engine", Mock(begin=connection, dispose=AsyncMock()))
    monkeypatch.setattr(main, "_require_supabase_config", Mock())
    for name in (
        "_migrate_tenant_columns", "_migrate_source_licence_columns",
        "_migrate_user_profile_columns", "_migrate_orphan_tenant_id_not_null",
        "_migrate_document_search_vector", "_setup_source_rls", "_setup_user_rls",
        "_warm_up_ml_models",
    ):
        monkeypatch.setattr(main, name, AsyncMock(side_effect=RuntimeError("policy failed") if name == failed_step else None))
    for name in ("_seed_defaults", "_seed_evaluation", "_seed_escalation_rules", "_seed_incidents"):
        monkeypatch.setattr(main, name, Mock())
    create_user = Mock(side_effect=AssertionError("Startup must not create auth accounts"))
    monkeypatch.setattr("app.core.supabase_admin.create_user", create_user)
    if failed_step:
        with pytest.raises(RuntimeError, match="policy failed"):
            async with main.lifespan(main.app):
                pytest.fail("Application served with missing security policies")
    else:
        async with main.lifespan(main.app):
            pass
    create_user.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_ddl_on_startup_is_retried_not_fatal(monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app import main

    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock())
    calls = []

    async def security_step():
        calls.append(1)
        if len(calls) < 3:
            raise OperationalError("ALTER TABLE sources", {}, Exception("canceling statement due to lock timeout"))
        return "applied"

    assert await main._with_ddl_retry(security_step) == "applied"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_other_database_errors_still_stop_startup(monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app import main

    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock())

    async def broken_policy():
        raise OperationalError("CREATE POLICY", {}, Exception("permission denied for table sources"))

    with pytest.raises(OperationalError):
        await main._with_ddl_retry(broken_policy)
