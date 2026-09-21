"""Web-search result cache — orchestration/websearch.py.

The cache exists to keep the upstream engines from blocking the instance, not
to save milliseconds, so these tests assert on CALL COUNT rather than timing.
"""
from __future__ import annotations

import asyncio

import pytest

from app.orchestration import websearch
from app.orchestration.websearch import WebSource


@pytest.fixture(autouse=True)
def _clear_cache():
    websearch._search_cache.clear()
    yield
    websearch._search_cache.clear()


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

        async def get(self, *a, **kw):
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


def test_empty_results_are_never_cached(monkeypatch):
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
    assert not websearch._search_cache


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


def test_ttl_of_zero_disables_the_cache(monkeypatch):
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)
    monkeypatch.setenv("SEARXNG_CACHE_TTL_SECONDS", "0")

    async def run():
        await websearch.web_search("federal income tax")
        await websearch.web_search("federal income tax")

    asyncio.run(run())
    assert len(calls) == 2
    assert not websearch._search_cache


def test_cache_is_bounded_and_evicts_the_coldest(monkeypatch):
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    async def run():
        for i in range(websearch._CACHE_MAX_ENTRIES + 20):
            await websearch.web_search(f"question number {i}")

    asyncio.run(run())
    assert len(websearch._search_cache) == websearch._CACHE_MAX_ENTRIES


def test_a_returned_list_cannot_mutate_the_cache(monkeypatch):
    """Callers get a copy — appending to a result must not poison later hits."""
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    async def run():
        first = await websearch.web_search("federal income tax")
        first.append(WebSource(title="injected", url="https://example.com", snippet=""))
        return await websearch.web_search("federal income tax")

    second = asyncio.run(run())
    assert [s.url for s in second] == ["https://www.irs.gov/filing/rates"]
