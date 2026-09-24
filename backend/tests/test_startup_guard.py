"""Regression guard for the env-config class of failure where the backend
started with no SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY: token verification
fails closed, so every authenticated endpoint 401s and default-user seeding is
silently skipped. The strict gate is opt-in (REQUIRE_SUPABASE_CONFIG=true) —
local/dev keeps the soft warning + skip-seeding behavior — so these tests pin
both sides of the flag.
"""
from __future__ import annotations

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