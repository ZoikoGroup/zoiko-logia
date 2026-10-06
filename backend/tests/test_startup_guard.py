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


@pytest.mark.parametrize("policies_valid", [True, False])
async def test_startup_requires_security_policies_without_writing_schema(monkeypatch, policies_valid):
    from unittest.mock import Mock
    from app import main
    monkeypatch.setattr(main, "_require_supabase_config", Mock())
    monkeypatch.setattr(main, "_stored_fingerprint", AsyncMock(return_value="current"))
    monkeypatch.setattr(main, "_startup_fingerprint", Mock(return_value="current"))
    monkeypatch.setattr(main, "_verify_security_policies", AsyncMock(
        side_effect=None if policies_valid else RuntimeError("policy missing")))
    monkeypatch.setattr(main, "_warm_up_ml_models", AsyncMock())
    monkeypatch.setattr(main, "async_engine", Mock(dispose=AsyncMock()))
    writes = AsyncMock(side_effect=AssertionError("startup must not run DDL"))
    monkeypatch.setattr(main, "_apply_schema_and_seeds", writes)
    if policies_valid:
        async with main.lifespan(main.app):
            pass
    else:
        with pytest.raises(RuntimeError, match="policy missing"):
            async with main.lifespan(main.app):
                pytest.fail("Application served without policies")
    writes.assert_not_called()


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


@pytest.mark.parametrize("stored_matches", [True, False])
async def test_startup_checks_setup_state_and_never_runs_migrations(monkeypatch, stored_matches):
    from unittest.mock import Mock
    from app import main
    monkeypatch.setattr(main, "async_engine", Mock(dispose=AsyncMock()))
    monkeypatch.setattr(main, "_require_supabase_config", Mock())
    monkeypatch.setattr(main, "_startup_fingerprint", Mock(return_value="current"))
    monkeypatch.setattr(main, "_stored_fingerprint", AsyncMock(return_value="current" if stored_matches else "old"))
    monkeypatch.setattr(main, "_verify_security_policies", AsyncMock())
    monkeypatch.setattr(main, "_warm_up_ml_models", AsyncMock())
    writes = AsyncMock()
    monkeypatch.setattr(main, "_apply_schema_and_seeds", writes)
    if stored_matches:
        async with main.lifespan(main.app):
            pass
    else:
        with pytest.raises(RuntimeError, match="setup_database"):
            async with main.lifespan(main.app):
                pytest.fail("Unprepared database was served")
    writes.assert_not_called()


def test_startup_fingerprint_is_stable_and_tracks_the_schema():
    from app import main

    assert main._startup_fingerprint() == main._startup_fingerprint()
    assert len(main._startup_fingerprint()) == 64
