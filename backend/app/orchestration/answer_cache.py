"""
Composed-answer cache for Ask Kriton™.

The provider allowance, not latency, is what this exists for. Groq's
on-demand tier gives 8,000 tokens a MINUTE, and a document-grounded question
spends most of one: ~2,200 for the system prompt, ~1,600 for the prompt
scaffolding, plus the evidence and the answer. Two such questions inside a
minute exceed the cap, the 429 names a reset tens of seconds away — far
beyond the single short retry groq_adapter.py performs — and the user is
shown a composition failure. Serving a repeat from cache spends nothing at
all, which is the only response to a token ceiling that actually works.

What is cached is the composed ANSWER TEXT, keyed by the exact grounded
prompt. Not the response object: query ids, audit chain ids and the ordered
audit trail must be fresh for every request, and validation, disclaimer and
visualization all still run on the way out. This skips the model call, never
the governance around it.

Two things are deliberately never cached:

  - answers built on live or delayed market data. A share price served from
    an hour-old answer is stated as current and is wrong, and the reader has
    no way to tell. frankfurter/market_data/fred mark their sources with a
    freshness, which is exactly the signal needed here.
  - failed or provider-error text, for the same reason websearch.py refuses
    to cache an empty result: a transient outage would otherwise be pinned in
    place long after it cleared.
"""
from __future__ import annotations

import asyncio
import hashlib
import os

from app.orchestration.websearch import WebSource

try:
    import redis.asyncio as _redis
except Exception:                   # pragma: no cover - package absent/broken
    _redis = None

# Bumped when the prompt scaffolding or the answer contract changes: entries
# written by an older build then miss rather than returning an answer shaped
# for a contract that no longer holds.
_CACHE_KEY_PREFIX = "answer:v5:"

# DB 3 alongside the web-search cache — both are derived, both are safe to
# lose, and keeping them together means one flush clears both.
_CACHE_REDIS_DEFAULT_URL = "redis://localhost:6379/3"

# A stalled Redis must stay cheaper than the model call it replaces.
_CACHE_SOCKET_TIMEOUT = 0.5

# Freshness values that make an answer unsafe to reuse. A "historical" or
# "filing" source is a statement about a fixed past period and does not go
# stale; a quote does, within seconds.
_VOLATILE_FRESHNESS = {"realtime", "delayed"}


def _cache_ttl() -> float:
    """Seconds a composed answer stays reusable. 0 or less disables the cache.

    An hour by default, matching the web-search cache: the evidence behind a
    document or guidance answer reads the same at 11:02 as at 11:22. Anything
    that does not is excluded by is_cacheable() rather than by a shorter TTL,
    because the right window for a share price is not "shorter" but "never".
    """
    try:
        return float(os.getenv("ANSWER_CACHE_TTL_SECONDS", "3600"))
    except ValueError:
        return 3600.0


def _cache_redis_url() -> str:
    return (
        os.getenv("ANSWER_CACHE_REDIS_URL")
        or os.getenv("SEARXNG_CACHE_REDIS_URL")
        or os.getenv("REDIS_URL")
        or _CACHE_REDIS_DEFAULT_URL
    )


_redis_client = None
_redis_client_loop = None


def _client():
    """Shared client, or None when Redis is unusable (callers treat that as a
    miss). Rebuilt when the event loop changes — see websearch._client for why.
    """
    global _redis_client, _redis_client_loop
    if _redis is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _redis_client is not None and _redis_client_loop is loop:
        return _redis_client
    try:
        _redis_client = _redis.from_url(
            _cache_redis_url(),
            decode_responses=True,
            socket_timeout=_CACHE_SOCKET_TIMEOUT,
            socket_connect_timeout=_CACHE_SOCKET_TIMEOUT,
        )
        _redis_client_loop = loop
    except Exception:
        _redis_client = None
        _redis_client_loop = None
    return _redis_client


def cache_key(grounded_prompt: str, model: str | None) -> str:
    """Key an answer by the exact prompt that would have produced it.

    The prompt already contains the question, every evidence snippet and the
    instructions, so identical prompts cannot mean different answers. That
    makes document identity, document content and retrieval ranking part of
    the key for free: edit or re-upload a document and its chunks change, the
    prompt changes, and the old answer is unreachable rather than stale.

    The model is in the key because a ZERO/LOW-risk question is answered by
    the smaller fast model — the same prompt genuinely produces a different
    answer through it, and serving one for the other would misrepresent which
    model was used in an audited pipeline.
    """
    digest = hashlib.sha256(grounded_prompt.encode("utf-8")).hexdigest()
    return f"{_CACHE_KEY_PREFIX}{model or 'default'}:{digest}"


def is_cacheable(sources: list[WebSource]) -> bool:
    """False when any evidence behind the answer goes stale on its own.

    A quote, an exchange rate or a delayed price is true for seconds. Reusing
    an answer built on one presents an old figure as current, with nothing in
    the text to warn the reader — the precise failure the freshness labels
    were introduced to prevent.
    """
    return not any(
        (source.freshness or "").lower() in _VOLATILE_FRESHNESS
        for source in sources
    )


async def get_answer(key: str) -> str | None:
    client = _client()
    if client is None:
        return None
    try:
        return await client.get(key)
    except Exception:
        # Refused, down, or past the socket timeout. Fail open: a cache
        # outage costs the tokens it would have saved, never the answer.
        return None


async def put_answer(key: str, answer: str) -> None:
    # An empty or provider-error answer is never stored, for the same reason
    # websearch.py refuses to cache an empty result set: the two are
    # indistinguishable from a transient outage at this layer, and pinning one
    # in place turns a moment's failure into an hour of it.
    if not answer or not answer.strip():
        return
    ttl = _cache_ttl()
    if ttl <= 0:
        return
    client = _client()
    if client is None:
        return
    try:
        await client.psetex(key, max(1, int(ttl * 1000)), answer)
    except Exception:
        return
