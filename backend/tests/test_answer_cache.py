"""Composed-answer cache — orchestration/answer_cache.py.

This exists for the provider's token allowance, not for latency. Groq's
on-demand tier gives 8,000 tokens a minute, and one document-grounded
question spends most of it; a second inside the same minute returns a 429
with a reset tens of seconds away and surfaces as a composition failure. A
cached answer spends nothing.

The tests that matter most here are the refusals. A cache that returns a
stale share price, or pins a provider outage in place, is worse than no
cache at all.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.orchestration import answer_cache
from app.orchestration.websearch import WebSource


class _FakeRedis:
    """get/psetex over a dict, holding the same strings the module writes."""

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
    async def get(self, key):
        raise ConnectionError("redis is down")

    async def psetex(self, key, ttl_ms, value):
        raise ConnectionError("redis is down")


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(answer_cache, "_client", lambda: fake)
    return fake


def _source(freshness: str | None) -> WebSource:
    return WebSource(title="t", url="", snippet="s", freshness=freshness)


def test_an_answer_round_trips():
    key = answer_cache.cache_key("a grounded prompt", None)

    async def run():
        assert await answer_cache.get_answer(key) is None
        await answer_cache.put_answer(key, "the answer")
        return await answer_cache.get_answer(key)

    assert asyncio.run(run()) == "the answer"


def test_a_different_prompt_cannot_collide():
    """The prompt carries the question, every evidence snippet and the
    instructions, so document identity and content are part of the key for
    free: re-upload a document and the old answer becomes unreachable."""
    assert answer_cache.cache_key("prompt A", None) != answer_cache.cache_key("prompt B", None)


def test_the_model_is_part_of_the_key():
    """A ZERO/LOW-risk question is answered by the smaller fast model. Serving
    one model's answer as the other's misrepresents an audited pipeline."""
    assert (
        answer_cache.cache_key("same prompt", None)
        != answer_cache.cache_key("same prompt", "openai/gpt-oss-20b")
    )


@pytest.mark.parametrize(
    "freshness, cacheable",
    [
        ("realtime", False),
        ("delayed", False),
        ("historical", True),
        ("filing", True),
        ("uploaded", True),
        (None, True),
    ],
)
def test_live_figures_are_never_reused(freshness, cacheable):
    """A quote is true for seconds. Serving an hour-old answer presents it as
    current, with nothing in the text to warn the reader."""
    assert answer_cache.is_cacheable([_source(freshness)]) is cacheable


def test_one_live_source_disqualifies_the_whole_answer():
    assert not answer_cache.is_cacheable([_source("uploaded"), _source("realtime")])


def test_a_blank_answer_is_never_stored(fake_redis):
    async def run():
        await answer_cache.put_answer(answer_cache.cache_key("p", None), "   ")

    asyncio.run(run())
    assert not fake_redis.store


def test_a_zero_ttl_disables_the_cache(monkeypatch, fake_redis):
    monkeypatch.setenv("ANSWER_CACHE_TTL_SECONDS", "0")

    async def run():
        await answer_cache.put_answer(answer_cache.cache_key("p", None), "an answer")

    asyncio.run(run())
    assert not fake_redis.store


def test_entries_expire(monkeypatch, fake_redis):
    monkeypatch.setenv("ANSWER_CACHE_TTL_SECONDS", "0.05")
    key = answer_cache.cache_key("p", None)

    async def run():
        await answer_cache.put_answer(key, "an answer")
        await asyncio.sleep(0.1)
        return await answer_cache.get_answer(key)

    assert asyncio.run(run()) is None


def test_a_redis_outage_fails_open(monkeypatch):
    """Losing the cache must cost the tokens it would have saved, never the
    answer."""
    monkeypatch.setattr(answer_cache, "_client", lambda: _BrokenRedis())
    key = answer_cache.cache_key("p", None)

    async def run():
        assert await answer_cache.get_answer(key) is None
        await answer_cache.put_answer(key, "an answer")   # must not raise

    asyncio.run(run())


def test_keys_are_versioned():
    """A changed prompt contract must not be answered from entries written
    for the old one."""
    assert answer_cache.cache_key("p", None).startswith(answer_cache._CACHE_KEY_PREFIX)
