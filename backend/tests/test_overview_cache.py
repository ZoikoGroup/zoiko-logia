"""Overview cache: an expired result is served at once while it rebuilds in
the background, and concurrent requests share one build."""
import asyncio

from app.domains.command_center import service


async def test_stale_result_is_served_while_it_rebuilds(monkeypatch):
    service._cache.clear()
    builds = []

    async def build():
        builds.append(1)
        await asyncio.sleep(0.01)
        return {"n": len(builds)}

    assert await service.cached(("k",), build) == {"n": 1}
    # Age the entry past CACHE_SECONDS but inside STALE_SECONDS.
    stamp, value = service._cache[("k",)]
    service._cache[("k",)] = (stamp - service.CACHE_SECONDS - 1, value)

    assert await service.cached(("k",), build) == {"n": 1}  # old value, no wait
    await asyncio.gather(*service._background)
    assert await service.cached(("k",), build) == {"n": 2}  # rebuilt in the background
    assert len(builds) == 2


async def test_concurrent_requests_share_one_build():
    service._cache.clear()
    builds = []

    async def build():
        builds.append(1)
        await asyncio.sleep(0.02)
        return {"ok": True}

    results = await asyncio.gather(*(service.cached(("shared",), build) for _ in range(5)))
    assert results == [{"ok": True}] * 5
    assert len(builds) == 1


async def test_refresh_button_forces_a_new_build():
    service._cache.clear()
    calls = []

    async def build():
        calls.append(1)
        return {"n": len(calls)}

    await service.cached(("f",), build)
    assert await service.cached(("f",), build, fresh=True) == {"n": 2}
