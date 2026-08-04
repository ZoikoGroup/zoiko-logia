"""
The single retry/backoff policy for outbound official-source calls.

This existed twice — once inside service.fetch_live_data()'s metric path and
once inside evidence_service.search_authoritative_evidence()'s record path —
with identical rules and no shared definition, so "how many times does
Kriton retry an official source, and against which status codes" had two
answers that could drift apart silently. One definition, both callers.

Only genuinely transient conditions are retried: a transport failure, a 429,
or a 5xx. A 403 (an authority refusing this deployment's egress) and a 404
are stable answers, and hammering a government host with them is both
pointless and rude.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

import httpx

from app.core.config import get_settings

T = TypeVar("T")

_MAX_RETRY_AFTER_SECONDS = 5.0


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


def _delay_for(exc: BaseException, attempt: int, backoff_seconds: float) -> float:
    delay = backoff_seconds * (attempt + 1)
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        # Honour Retry-After when the authority states one, but never let a
        # remote host park a user's request for an unbounded time.
        retry_after = exc.response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), _MAX_RETRY_AFTER_SECONDS)
    return delay


async def call_with_retries(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int | None = None,
    backoff_seconds: float | None = None,
) -> T:
    """Runs `operation`, retrying only transient failures. Re-raises the last
    exception when every attempt is exhausted — callers decide whether a
    failed official source is fatal or degrades silently."""
    settings = get_settings()
    total = max(1, attempts if attempts is not None else settings.LIVE_SOURCE_MAX_ATTEMPTS)
    backoff = backoff_seconds if backoff_seconds is not None else settings.LIVE_SOURCE_RETRY_BACKOFF_SECONDS

    last_error: BaseException | None = None
    for attempt in range(total):
        try:
            return await operation()
        except Exception as exc:
            last_error = exc
            if not is_retryable(exc) or attempt + 1 >= total:
                break
            await asyncio.sleep(_delay_for(exc, attempt, backoff))

    assert last_error is not None
    raise last_error
