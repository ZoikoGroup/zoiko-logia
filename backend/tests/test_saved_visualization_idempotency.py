"""Tests the user-namespaced idempotency-key scoping that
app.domains.kriton_workspace.router.post_saved_visualization applies before
calling the shared check_idempotency/store_idempotency helpers.

Deliberately does NOT use TestClient(app) against the real endpoint —
FastAPI TestClient(app) triggers app.main's real lifespan, whose request-time
DB dependency (app.core.database.request_engine) falls back to the live
Supabase APP_DATABASE_URL from backend/.env whenever conftest.py's
os.environ.pop("APP_DATABASE_URL", None) leaves it unset (pydantic-settings'
env_file mechanism re-reads the real .env value once the override is gone).
That's a pre-existing gap in this test suite's hermeticity — confirmed by
attempting it and watching the request actually reach Postgres — not
something to work around here. This test instead exercises the exact same
scoping logic directly against the sqlite-backed async_engine, which is what
every other test in this file already does safely.
"""
import uuid

import pytest_asyncio

from app.core.database import AsyncSessionLocal
from app.orchestration.identifiers import check_idempotency, store_idempotency

_TENANT = "tenant-idempotency-test"


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


def _scoped_key(user_id: str, raw_key: str) -> str:
    # Mirrors router.py's post_saved_visualization exactly.
    return f"{user_id}:{raw_key}"


async def test_same_owner_and_key_reuses_the_cached_response(db):
    # test.db is a persistent file, not recreated per test run — a fixed key
    # here would collide with leftover data from a prior run of this same
    # suite, so every key is unique per invocation.
    raw_key = f"repeat-click-key-{uuid.uuid4()}"
    scoped = _scoped_key("user-same", raw_key)
    assert await check_idempotency(db, scoped, _TENANT) is None

    await store_idempotency(db, scoped, _TENANT, {"id": "sv-1"})
    cached = await check_idempotency(db, scoped, _TENANT)
    assert cached == {"id": "sv-1"}


async def test_different_users_with_the_same_raw_key_do_not_collide(db):
    raw_key = f"shared-raw-key-{uuid.uuid4()}"
    alice_key = _scoped_key("user-alice", raw_key)
    bob_key = _scoped_key("user-bob", raw_key)

    await store_idempotency(db, alice_key, _TENANT, {"id": "sv-alice"})

    # Bob's namespaced key is a different string even though the raw
    # client-supplied key is identical — no cached response for him yet.
    assert await check_idempotency(db, bob_key, _TENANT) is None
    await store_idempotency(db, bob_key, _TENANT, {"id": "sv-bob"})

    assert (await check_idempotency(db, alice_key, _TENANT))["id"] == "sv-alice"
    assert (await check_idempotency(db, bob_key, _TENANT))["id"] == "sv-bob"
