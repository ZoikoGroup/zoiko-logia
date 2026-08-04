"""Hermetic test defaults.

Unit tests must never inherit the developer's backend/.env database URL or
contact Supabase. PostgreSQL/RLS integration tests already skip themselves
when the configured dialect is SQLite.
"""
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


if os.environ.get("RUN_POSTGRES_TESTS") != "1":
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
    os.environ.pop("APP_DATABASE_URL", None)
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import pytest_asyncio

from app.core.config import get_settings
from app.core.database import async_engine
from app.db.base import Base
from app.domains.live_sources.schema_sync import ensure_provider_columns


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_test_schema():
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    # create_all never alters an existing table, so a test.db carried over
    # from before a column was added keeps the stale schema and fails at the
    # first INSERT. The runtime reconciles this at startup (app/main.py's
    # _migrate_live_source_provider_columns); the suite has to reconcile it
    # the same way or it tests a schema the runtime never actually runs on.
    await ensure_provider_columns(async_engine, is_sqlite=get_settings().is_sqlite)
    yield
    await async_engine.dispose()
