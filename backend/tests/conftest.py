"""Hermetic test defaults.

Unit tests must never inherit the developer's backend/.env database URL or
contact Supabase. PostgreSQL/RLS integration tests already skip themselves
when the configured dialect is SQLite.
"""
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ.pop("APP_DATABASE_URL", None)
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import pytest_asyncio

from app.core.database import async_engine
from app.db.base import Base


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_test_schema():
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await async_engine.dispose()
