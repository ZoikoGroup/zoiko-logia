"""Measured health history for the Status & Health page.

Two sources, both real:
- every API request's duration and status, kept in memory and summarised
  into one "api" sample per interval (p50, p95, requests, server errors);
- a live check of each dependency (operations/service.py).

A background task stores one sample per service every
HEALTH_SAMPLE_INTERVAL_SECONDS and prunes samples older than the retention
window. Opening the Status page also records its live checks, at most once a
minute, so history exists even where the sampler is switched off.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.operations import service as operations
from app.domains.operations.models import ServiceHealthSample

logger = logging.getLogger(__name__)

_MAX_REQUESTS = 20_000
# Minimum spacing between samples recorded from page views.
PAGE_SAMPLE_MIN_SECONDS = 60


class _RequestRecorder:
    """Durations and status codes of recent API requests (this process)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: deque[tuple[float, float, int]] = deque(maxlen=_MAX_REQUESTS)

    def record(self, duration_ms: float, status: int) -> None:
        with self._lock:
            self._items.append((time.time(), duration_ms, status))

    def window(self, seconds: float) -> list[tuple[float, int]]:
        cutoff = time.time() - seconds
        with self._lock:
            return [(d, s) for t, d, s in self._items if t >= cutoff]


recorder = _RequestRecorder()


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def api_summary(seconds: float) -> dict:
    """The API's own health over the last `seconds`, from real requests."""
    items = recorder.window(seconds)
    durations = [d for d, _ in items]
    errors = sum(1 for _, s in items if s >= 500)
    p95 = _percentile(durations, 95)
    objective = get_settings().OPS_API_P95_OBJECTIVE_MS
    error_rate = errors / len(items) if items else 0.0
    state = "degraded" if items and (error_rate > 0.05 or (p95 or 0) > objective) else "operational"
    detail = (f"{len(items)} request(s), {errors} server error(s)" if items
              else "No requests in this window")
    return {"key": "api", "name": operations.SERVICE_NAMES["api"], "state": state,
            "latencyMs": None if p95 is None else round(p95), "p50Ms": _percentile(durations, 50),
            "requests": len(items), "errors": errors, "detail": detail}


def _sample(check: dict, now: datetime) -> ServiceHealthSample:
    return ServiceHealthSample(
        service_key=check["key"], checked_at=now, state=check["state"], latency_ms=check["latencyMs"],
        p50_ms=check.get("p50Ms"), requests=check.get("requests"), errors=check.get("errors"),
        detail=check["detail"][:500],
    )


async def record_samples(db: AsyncSession, checks: list[dict], now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    db.add_all(_sample(c, now) for c in checks if c["key"] in operations.SERVICE_NAMES)
    await db.commit()


async def latest_sample_at(db: AsyncSession) -> datetime | None:
    value = (await db.execute(select(func.max(ServiceHealthSample.checked_at)))).scalar_one_or_none()
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


async def take_sample(db: AsyncSession, window_seconds: float) -> list[dict]:
    checks = [api_summary(window_seconds), *await operations.dependency_checks(db)]
    await record_samples(db, checks)
    return checks


async def prune(db: AsyncSession, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=get_settings().HEALTH_SAMPLE_RETENTION_DAYS)
    await db.execute(delete(ServiceHealthSample).where(ServiceHealthSample.checked_at < cutoff))
    await db.commit()


async def run_sampler(session_factory) -> None:
    """Background loop started by the app lifespan. One short-lived session per
    round, so it never holds a pooled connection between rounds."""
    interval = max(60, get_settings().HEALTH_SAMPLE_INTERVAL_SECONDS)
    while True:
        try:
            async with session_factory() as db:
                await take_sample(db, interval)
                await prune(db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a failed round must not stop sampling
            logger.warning("Health sampling round failed (%s)", type(exc).__name__)
        await asyncio.sleep(interval)
