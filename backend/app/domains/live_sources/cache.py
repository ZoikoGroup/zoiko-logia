"""
Postgres-backed TTL cache for live source fetches. Deliberately not Redis —
see app/domains/live_sources/models.py's LiveFetchCache docstring. The
key scheme (provider_key + indicator + country -> payload/expires_at) is
designed to carry over unchanged if a faster L1 cache is added later.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.live_sources.models import LiveFetchCache
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


def make_cache_key(intent: LiveDataIntent) -> str:
    # company_query included when present — otherwise two different
    # companies' identical indicator_code (e.g. Apple's and Microsoft's
    # both "Assets") would collide onto the same cache row.
    raw = f"{intent.provider_key}:{intent.indicator_code}:{intent.country_code}:{intent.company_query or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


async def get_cached(db: AsyncSession, cache_key: str) -> NormalizedResponse | None:
    result = await db.execute(select(LiveFetchCache).where(LiveFetchCache.cache_key == cache_key))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at <= datetime.now(timezone.utc):
        return None
    return NormalizedResponse.model_validate(row.payload)


async def set_cached(
    db: AsyncSession,
    *,
    cache_key: str,
    provider_key: str,
    normalized: NormalizedResponse,
    ttl_seconds: int,
) -> None:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    payload = normalized.model_dump()

    # Plain select-then-write rather than a dialect-specific upsert (ON
    # CONFLICT), since this repo also supports a SQLite dev fallback
    # (settings.is_sqlite) elsewhere — a tiny race on first-ever write for a
    # given cache_key is harmless (worst case: one redundant row attempt).
    result = await db.execute(select(LiveFetchCache).where(LiveFetchCache.cache_key == cache_key))
    row = result.scalar_one_or_none()
    if row is not None:
        row.payload = payload
        row.fetched_at = now
        row.expires_at = expires_at
    else:
        db.add(LiveFetchCache(
            provider_key=provider_key,
            cache_key=cache_key,
            payload=payload,
            fetched_at=now,
            expires_at=expires_at,
        ))
    await db.commit()
