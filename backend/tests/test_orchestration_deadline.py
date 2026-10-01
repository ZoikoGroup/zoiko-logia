import asyncio

import pytest
from fastapi import HTTPException

from app.orchestration import router


@pytest.mark.asyncio
async def test_request_deadline_cancels_orchestration(monkeypatch):
    cancelled = asyncio.Event()

    async def slow_ask(**_kwargs):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    monkeypatch.setattr(router, "ask_kriton", slow_ask)
    monkeypatch.setattr(router.settings, "ASK_KRITON_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(HTTPException) as error:
        await router._run_with_deadline(db=None, sync_db=None)

    assert error.value.status_code == 504
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_duplicate_request_does_not_release_other_workers_claim(monkeypatch):
    async def duplicate(**_kwargs):
        raise HTTPException(status_code=409, detail="already running")

    released = False

    async def abandon(*_args):
        nonlocal released
        released = True

    monkeypatch.setattr(router, "ask_kriton", duplicate)
    monkeypatch.setattr(router, "abandon_idempotency", abandon)

    with pytest.raises(HTTPException) as error:
        await router._run_with_deadline(
            db=None, sync_db=None, idempotency_key="same-key", tenant_id="tenant-a"
        )

    assert error.value.status_code == 409
    assert released is False
