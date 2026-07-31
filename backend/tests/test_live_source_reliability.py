from unittest.mock import AsyncMock

import httpx
import pytest

from app.domains.live_sources import service
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


INTENT = LiveDataIntent(
    provider_key="reliability_test",
    indicator_code="VALUE",
    indicator_label="Test value",
    country_code="GB",
    country_label="United Kingdom",
)

NORMALIZED = NormalizedResponse(
    provider_key="reliability_test",
    indicator_code="VALUE",
    indicator_label="Test value",
    country_code="GB",
    country_label="United Kingdom",
    value=42.0,
    observation_period="2026",
    as_of="2026-07-30T00:00:00+00:00",
    source_url="https://example.test/value",
    citation_title="Reliability test value",
)


class _EventuallySuccessfulConnector:
    def __init__(self):
        self.calls = 0

    async def fetch(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise httpx.ReadTimeout("temporary timeout")
        return NORMALIZED


class _BrokenConnector:
    async def fetch(self, *args, **kwargs):
        raise ValueError("invalid provider response")


@pytest.mark.asyncio
async def test_transient_transport_failure_is_retried(monkeypatch):
    connector = _EventuallySuccessfulConnector()
    db = AsyncMock()
    monkeypatch.setattr(service, "detect_live_data_intent", lambda *args, **kwargs: INTENT)
    monkeypatch.setitem(service._CONNECTORS, INTENT.provider_key, connector)
    monkeypatch.setattr(service.cache, "get_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(service.cache, "set_cached", AsyncMock())
    monkeypatch.setattr(service.settings, "LIVE_SOURCE_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(service.settings, "LIVE_SOURCE_RETRY_BACKOFF_SECONDS", 0)

    outcome = await service.fetch_live_data(db, query="test", tenant_id="tenant")

    assert outcome.succeeded is True
    assert outcome.normalized == NORMALIZED
    assert connector.calls == 2


@pytest.mark.asyncio
async def test_cache_and_provider_failures_never_escape(monkeypatch):
    db = AsyncMock()
    monkeypatch.setattr(service, "detect_live_data_intent", lambda *args, **kwargs: INTENT)
    monkeypatch.setitem(service._CONNECTORS, INTENT.provider_key, _BrokenConnector())
    monkeypatch.setattr(service.cache, "get_cached", AsyncMock(side_effect=RuntimeError("cache unavailable")))
    monkeypatch.setattr(service.settings, "LIVE_SOURCE_MAX_ATTEMPTS", 2)

    outcome = await service.fetch_live_data(db, query="test", tenant_id="tenant")

    assert outcome.succeeded is False
    assert outcome.intent == INTENT
    assert "invalid provider response" in (outcome.error or "")


@pytest.mark.asyncio
async def test_successful_fetch_survives_cache_write_failure(monkeypatch):
    db = AsyncMock()

    class _SuccessfulConnector:
        async def fetch(self, *args, **kwargs):
            return NORMALIZED

    monkeypatch.setattr(service, "detect_live_data_intent", lambda *args, **kwargs: INTENT)
    monkeypatch.setitem(service._CONNECTORS, INTENT.provider_key, _SuccessfulConnector())
    monkeypatch.setattr(service.cache, "get_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(service.cache, "set_cached", AsyncMock(side_effect=RuntimeError("write failed")))

    outcome = await service.fetch_live_data(db, query="test", tenant_id="tenant")

    assert outcome.succeeded is True
    assert outcome.normalized == NORMALIZED
    db.rollback.assert_awaited_once()
