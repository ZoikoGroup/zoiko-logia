"""The dev seed script refuses a non-isolated database (30 Oct 2026): it wrote
"Local tax bulletin" to the shared production database."""
import runpy
import sys

import pytest


def test_the_seed_script_refuses_a_shared_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@db.example.supabase.co:5432/postgres")
    called = []
    monkeypatch.setattr("asyncio.run", lambda *a, **k: called.append(True))
    monkeypatch.setattr(sys, "argv", ["seed_dev_user.py"])
    with pytest.raises(SystemExit, match="Refusing to write test fixtures"):
        runpy.run_path("scripts/seed_dev_user.py", run_name="__main__")
    assert not called


def test_the_seed_script_runs_against_a_local_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/kriton")
    called = []
    monkeypatch.setattr("asyncio.run", lambda coro, *a, **k: (called.append(True), coro.close()))
    monkeypatch.setattr(sys, "argv", ["seed_dev_user.py"])
    runpy.run_path("scripts/seed_dev_user.py", run_name="__main__")
    assert called
