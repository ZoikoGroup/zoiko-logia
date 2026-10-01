"""Web-search result cache — orchestration/websearch.py.

The cache exists to keep the upstream engines from blocking the instance, not
to save milliseconds, so these tests assert on CALL COUNT rather than timing.

The cache lives in Redis. These tests stand a fake in for it rather than
requiring a running server, but the fake stores the same serialised strings
the module writes, so the JSON round trip is still exercised — a fake holding
WebSource objects directly would hide exactly the bugs this layer introduced.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.orchestration import websearch
from app.orchestration.websearch import WebSource


class _FakeRedis:
    """Minimal async stand-in: the get/psetex pair the cache actually uses."""

    def __init__(self):
        self.store: dict[str, tuple[float, str]] = {}
        self.writes: list[tuple[str, int, str]] = []

    async def get(self, key):
        entry = self.store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self.store[key]
            return None
        return value

    async def psetex(self, key, ttl_ms, value):
        self.writes.append((key, ttl_ms, value))
        self.store[key] = (time.monotonic() + ttl_ms / 1000.0, value)


class _BrokenRedis:
    """Every call raises — stands in for a stopped or unreachable server."""

    async def get(self, key):
        raise ConnectionError("redis is down")

    async def psetex(self, key, ttl_ms, value):
        raise ConnectionError("redis is down")


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(websearch, "_client", lambda: fake)
    return fake


def _fake_searxng(monkeypatch, results, counter):
    """Replace the HTTP call with a counted stub returning `results`."""

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": results}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url="", *a, **kw):
            # Count trips to the search engine only — reading the top official
            # pages (websearch._with_page_extracts) is a separate request.
            if str(url).endswith("/search"):
                counter.append(1)
            return _Resp()

    monkeypatch.setattr(websearch.httpx, "AsyncClient", _Client)


_IRS_HIT = [
    {"title": "Federal income tax rates", "url": "https://www.irs.gov/filing/rates", "content": "Brackets."}
]


def test_second_identical_query_does_not_reach_the_engines(monkeypatch):
    """The whole point: a repeated question makes ONE upstream request.

    Development asked the same handful of questions dozens of times, which is
    what got the instance suspended by Google and CAPTCHA'd by DuckDuckGo.
    """
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    async def run():
        first = await websearch.web_search("How is federal income tax calculated in the US?")
        second = await websearch.web_search("How is federal income tax calculated in the US?")
        return first, second

    first, second = asyncio.run(run())

    assert len(calls) == 1, "second identical query went back out to the engines"
    assert [s.url for s in first] == [s.url for s in second]


def test_empty_results_are_never_cached(monkeypatch, fake_redis):
    """A blocked engine and a genuine no-match both look like results: [].

    Caching that would pin "no sources" in place for the whole TTL and keep
    serving it after the block lifted — so an empty result must always retry.
    """
    calls: list[int] = []
    _fake_searxng(monkeypatch, [], calls)

    async def run():
        await websearch.web_search("a question nothing matches")
        await websearch.web_search("a question nothing matches")

    asyncio.run(run())

    assert len(calls) == 2, "an empty result was cached, freezing the outage in"
    assert not fake_redis.store


def test_query_whitespace_and_case_share_one_entry(monkeypatch):
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    async def run():
        await websearch.web_search("federal income tax")
        await websearch.web_search("  Federal   INCOME  tax ")

    asyncio.run(run())
    assert len(calls) == 1


def test_jurisdiction_is_part_of_the_key(monkeypatch):
    """Different jurisdictions resolve different allowlists, so they must not
    share a cache entry — a UK answer served for a US question would cite the
    wrong authority."""
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    async def run():
        await websearch.web_search("vat threshold", jurisdiction="UK")
        await websearch.web_search("vat threshold", jurisdiction="US")

    asyncio.run(run())
    assert len(calls) == 2


def test_expired_entry_is_refetched(monkeypatch):
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)
    monkeypatch.setenv("SEARXNG_CACHE_TTL_SECONDS", "0.05")

    async def run():
        await websearch.web_search("federal income tax")
        await asyncio.sleep(0.1)
        await websearch.web_search("federal income tax")

    asyncio.run(run())
    assert len(calls) == 2


def test_ttl_of_zero_disables_the_cache(monkeypatch, fake_redis):
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)
    monkeypatch.setenv("SEARXNG_CACHE_TTL_SECONDS", "0")

    async def run():
        await websearch.web_search("federal income tax")
        await websearch.web_search("federal income tax")

    asyncio.run(run())
    assert len(calls) == 2
    assert not fake_redis.store


def test_entries_are_written_with_an_expiry(monkeypatch, fake_redis):
    """Expiry moved to the server when the dict went away.

    Nothing sweeps this cache any more, so a write without a TTL would sit in
    Redis until someone flushed it by hand — serving last month's guidance as
    though it were current.
    """
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)
    monkeypatch.setenv("SEARXNG_CACHE_TTL_SECONDS", "3600")

    asyncio.run(websearch.web_search("federal income tax"))

    assert len(fake_redis.writes) == 1
    key, ttl_ms, _ = fake_redis.writes[0]
    assert ttl_ms == 3_600_000
    assert key.startswith(websearch._CACHE_KEY_PREFIX), "cache key lost its version prefix"


def test_a_redis_outage_still_answers(monkeypatch):
    """Fail open. Losing the cache must cost the saved search, never the answer.

    This is the failure mode the dict could not have — it is the price of
    moving the cache out of process, and the reason every call is wrapped.
    """
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)
    monkeypatch.setattr(websearch, "_client", lambda: _BrokenRedis())

    async def run():
        first = await websearch.web_search("federal income tax")
        second = await websearch.web_search("federal income tax")
        return first, second

    first, second = asyncio.run(run())

    assert [s.url for s in first] == ["https://www.irs.gov/filing/rates"]
    assert [s.url for s in second] == ["https://www.irs.gov/filing/rates"]
    assert len(calls) == 2, "a dead cache should mean every query searches, not that it fails"


def test_an_unreadable_entry_is_treated_as_a_miss(monkeypatch, fake_redis):
    """Junk under a live key — a partial write, or a shape from an older build
    that shared this prefix — must refetch rather than raise."""
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    key = websearch._cache_key("federal income tax", "", 5)
    fake_redis.store[key] = (time.monotonic() + 60, "{not json at all")

    results = asyncio.run(websearch.web_search("federal income tax"))

    assert len(calls) == 1
    assert [s.url for s in results] == ["https://www.irs.gov/filing/rates"]


def test_provenance_fields_survive_the_round_trip(monkeypatch, fake_redis):
    """WebSource carries optional provenance. JSON is now in the middle of
    every hit, so a field dropped in encode/decode would silently strip
    freshness from a cached answer while the first answer kept it."""
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    source = WebSource(
        title="t",
        url="https://www.irs.gov/x",
        snippet="s",
        provider="searxng",
        fetched_at="2026-09-24T00:00:00Z",
        freshness="historical",
        source_id="doc-1",
    )
    assert websearch._decode(websearch._encode([source])) == [source]


def test_a_returned_list_cannot_mutate_the_cache(monkeypatch):
    """Callers get their own objects — appending to a result must not poison
    later hits."""
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    async def run():
        first = await websearch.web_search("federal income tax")
        first.append(WebSource(title="injected", url="https://example.com", snippet=""))
        return await websearch.web_search("federal income tax")

    second = asyncio.run(run())
    assert [s.url for s in second] == ["https://www.irs.gov/filing/rates"]
