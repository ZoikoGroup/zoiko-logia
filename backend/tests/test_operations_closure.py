"""Operations Closure (4 Nov 2026): the service-health panel keeps operational,
not configured and down apart with totals that add up, carries each check's
result, says why the AI control plane is unknown, and checks Tavily (the
primary web search) rather than only its SearXNG backup."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.operations import service as operations
from app.domains.operations.models import ServiceHealthSample
from app.domains.platform import service as platform
from app.orchestration import websearch

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def _sample(key: str, state: str, detail: str = "") -> ServiceHealthSample:
    return ServiceHealthSample(service_key=key, state=state, checked_at=NOW - timedelta(minutes=2),
                               latency_ms=20.0 if state == "operational" else None, detail=detail)


async def test_the_counts_keep_the_three_states_apart_and_add_up(db) -> None:
    # The founder's screenshot: four up, six not configured; Tavily not checked yet.
    up = ["api", "database", "supabase_auth", "groq"]
    off = ["google", "openai", "anthropic", "searxng", "kroki", "redis"]
    db.add_all([_sample(k, "operational", "HTTP 200") for k in up] + [_sample(k, "not_configured") for k in off])
    await db.commit()
    health = (await platform.command_overview(db, now=NOW))["health"]
    assert health["counts"] == {"operational": 4, "notConfigured": 6, "down": 0, "unchecked": 1, "total": 11}
    assert health["counts"]["total"] == len(operations.SERVICES)
    assert health["degraded"] == 0 and health["measured"] == 4
    assert {s["key"]: s["detail"] for s in health["services"]}["groq"] == "HTTP 200"


async def test_a_down_service_is_counted_once_as_down(db) -> None:
    db.add_all([_sample("groq", "down", "Credentials rejected (HTTP 401)"), _sample("kroki", "not_configured")])
    await db.commit()
    counts = (await platform.command_overview(db, now=NOW))["health"]["counts"]
    assert counts["down"] == 1 and counts["notConfigured"] == 1 and counts["operational"] == 0


async def test_unknown_control_plane_says_why(db) -> None:
    evaluation = (await platform.command_overview(db, now=NOW))["evaluation"]
    assert evaluation["state"] == "unknown"
    assert evaluation["reason"] == "No evaluation run is recorded yet"


@pytest.fixture
def tavily(monkeypatch):
    monkeypatch.setitem(websearch._tavily_paused, "until", 0.0)
    monkeypatch.setitem(websearch._tavily_paused, "reason", "")
    return monkeypatch


def test_web_search_health_checks_tavily_first(tavily) -> None:
    keys = [key for key, *_ in operations.SERVICES]
    assert keys.index("tavily") < keys.index("searxng")
    assert operations.SERVICE_NAMES["tavily"] == "Web search"
    assert operations.SERVICE_NAMES["searxng"] == "Web search backup"


def test_tavily_without_a_key_is_not_configured(tavily) -> None:
    tavily.delenv("TAVILY_API_KEY", raising=False)
    assert asyncio.run(operations._tavily_check())["state"] == "not_configured"


def test_tavily_with_a_key_and_no_rejection_is_operational(tavily) -> None:
    tavily.setenv("TAVILY_API_KEY", "tvly-test")
    check = asyncio.run(operations._tavily_check())
    assert check["state"] == "operational" and "not probed" in check["detail"]


@pytest.mark.parametrize("reason, cause", [
    ("HTTP 401: Unauthorized: missing or invalid API key acct-123", "Credentials rejected"),
    ("HTTP 432: This request exceeds your plan's set usage limit", "Usage limit reached"),
    ("HTTP 429: slow down", "Rate limited"),
])
def test_a_paused_tavily_is_down_with_the_cause_and_never_the_provider_message(tavily, reason, cause) -> None:
    tavily.setenv("TAVILY_API_KEY", "tvly-test")
    tavily.setitem(websearch._tavily_paused, "until", time.monotonic() + 600)
    tavily.setitem(websearch._tavily_paused, "reason", reason)
    check = asyncio.run(operations._tavily_check())
    assert check["state"] == "down"
    assert check["detail"] == f"{cause}; searches use the backup"
    assert "acct-123" not in check["detail"] and "plan" not in check["detail"]
