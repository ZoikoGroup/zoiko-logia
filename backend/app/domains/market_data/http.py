"""Shared async HTTP for provider adapters.

One place decides timeouts, what is worth retrying, and how a provider's error
shape maps onto our typed errors — so four adapters do not each invent their
own retry policy and four different ways of missing a rate limit.

Retry policy, deliberately narrow:
  - 429 and 5xx and transport failures  → retried with exponential backoff
  - 401/403                             → never retried; a rejected key stays rejected
  - 4xx other than 429                  → never retried; the request is wrong
Blind retrying of auth failures is how an account gets locked and how a
rate-limit breach becomes a rate-limit ban.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

from app.domains.market_data.schemas import (
    ProviderAuthError,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
DEFAULT_RETRIES = 2


def _base_backoff() -> float:
    try:
        return float(os.getenv("STOCK_WS_RECONNECT_DELAY", "0.5"))
    except ValueError:
        return 0.5


def _max_backoff() -> float:
    try:
        return float(os.getenv("STOCK_WS_MAX_RECONNECT_DELAY", "8"))
    except ValueError:
        return 8.0


def _redact(params: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Query params minus anything that looks like a credential. Every log line
    in this module goes through here — an API key in a log is an API key
    leaked, and several of these providers pass keys as query params."""
    if not params:
        return {}
    secret = {"apikey", "api_key", "apiKey", "token", "api_token", "key", "access_key"}
    return {k: ("<redacted>" if k in secret else v) for k, v in params.items()}


async def request_json(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    auth: Optional[httpx.Auth] = None,
    retries: int = DEFAULT_RETRIES,
    correlation_id: str = "",
) -> Any:
    """GET `url` and return parsed JSON, or raise a typed ProviderError.

    `auth` covers providers that authenticate with HTTP Basic (Companies House)
    rather than a header or query parameter.
    """
    attempt = 0
    while True:
        try:
            response = await client.get(
                url, params=params, headers=headers, **({"auth": auth} if auth is not None else {})
            )
        except httpx.TimeoutException as exc:
            if attempt >= retries:
                raise ProviderUnavailable(provider, f"timed out after {attempt + 1} attempts") from exc
            await _sleep_backoff(attempt)
            attempt += 1
            continue
        except httpx.HTTPError as exc:
            if attempt >= retries:
                raise ProviderUnavailable(provider, f"connection failed: {type(exc).__name__}") from exc
            await _sleep_backoff(attempt)
            attempt += 1
            continue

        status = response.status_code

        if status in (401, 403):
            # Never retried — see module docstring.
            raise ProviderAuthError(provider, f"authentication rejected (HTTP {status})")

        if status == 429:
            retry_after = _retry_after_seconds(response)
            if attempt >= retries:
                raise ProviderRateLimited(provider, "rate limit exceeded", retry_after)
            await _sleep_backoff(attempt, floor=retry_after)
            attempt += 1
            continue

        if status >= 500:
            if attempt >= retries:
                raise ProviderUnavailable(provider, f"upstream error (HTTP {status})")
            await _sleep_backoff(attempt)
            attempt += 1
            continue

        if status >= 400:
            raise ProviderBadResponse(provider, f"request rejected (HTTP {status})")

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderBadResponse(provider, "response body was not valid JSON") from exc


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        # Retry-After may be an HTTP-date; treating it as "unknown" and using
        # our own backoff is safer than parsing dates wrong and hammering.
        return None


async def _sleep_backoff(attempt: int, floor: Optional[float] = None) -> None:
    delay = _base_backoff() * (2**attempt)
    if floor is not None:
        delay = max(delay, floor)
    await asyncio.sleep(min(delay, _max_backoff()))


def make_client(timeout: float = DEFAULT_TIMEOUT, **kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, **kwargs)


def as_float(value: Any) -> Optional[float]:
    """Provider numerics arrive as strings, nulls, "None", "-" and occasionally
    NaN. Anything not a finite number becomes None so it can be reported as
    missing rather than rendered as a bogus figure."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed
