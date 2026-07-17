"""
Live external data source path — classifier, cache roundtrip, and the
license_gate/bundle_builder invariant that live sources ride through the
existing SourceBundle pipeline unmodified.

Requires a live DB for the cache/eligibility tests (creates real
LiveSourceProvider/LiveFetchCache rows) — run inside the backend container:
    docker compose exec backend python3 tests/test_live_sources_connector.py

test_world_bank_connector_fetches_real_data additionally makes a live HTTP
call to the World Bank API — no key required, but needs network access.
"""
import asyncio
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.domains.live_sources import cache, service as live_sources_service
from app.domains.live_sources.classifier import detect_live_data_intent
from app.domains.live_sources.connectors.world_bank import WorldBankConnector
from app.domains.live_sources.models import LiveSourceProvider
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse
from app.domains.massarius.bundle_builder import build_bundle
from app.domains.massarius.license_gate import check_eligibility
from app.orchestration.schemas import SourceBundle

settings = get_settings()


def test_classifier_detects_gdp_and_country():
    intent = detect_live_data_intent("What is India's current GDP?")
    assert intent is not None
    assert intent.provider_key == "world_bank"
    assert intent.indicator_code == "NY.GDP.MKTP.CD"
    assert intent.country_code == "IN"
    print("test_classifier_detects_gdp_and_country: PASSED")


def test_classifier_defaults_to_world_when_no_country_matched():
    intent = detect_live_data_intent("What is the global inflation rate?")
    assert intent is not None
    assert intent.country_code == "WLD"
    print("test_classifier_defaults_to_world_when_no_country_matched: PASSED")


def test_classifier_returns_none_for_unrelated_query():
    intent = detect_live_data_intent("What does IFRS 16 say about leases?")
    assert intent is None
    print("test_classifier_returns_none_for_unrelated_query: PASSED")


async def test_world_bank_connector_fetches_real_data():
    connector = WorldBankConnector(base_url=settings.WORLD_BANK_API_BASE_URL)
    intent = LiveDataIntent(
        provider_key="world_bank", indicator_code="NY.GDP.MKTP.CD", indicator_label="GDP (current US$)",
        country_code="IN", country_label="India",
    )
    normalized = await connector.fetch(intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
    assert normalized.provider_key == "world_bank"
    assert normalized.value not in (None, "")
    print("test_world_bank_connector_fetches_real_data: PASSED")


async def test_cache_roundtrip():
    # Uses a provider_key no real query will ever classify to (classifier.py
    # only ever emits "world_bank"), so this test's fake cache row can never
    # collide with — and silently serve stale data to — an actual query.
    fake_provider_key = f"test_provider_{uuid.uuid4().hex[:8]}"
    intent = LiveDataIntent(
        provider_key=fake_provider_key, indicator_code="NY.GDP.MKTP.CD", indicator_label="GDP (current US$)",
        country_code="IN", country_label="India",
    )
    normalized = NormalizedResponse(
        provider_key=fake_provider_key, indicator_code="NY.GDP.MKTP.CD", indicator_label="GDP (current US$)",
        country_code="IN", country_label="India", value=3000.0, unit="", observation_period="2023",
        as_of="2026-07-17T00:00:00+00:00", source_url="https://example.test",
        citation_title="World Bank — India, GDP (current US$), 2023",
    )
    cache_key = cache.make_cache_key(intent)
    async with AsyncSessionLocal() as db:
        try:
            assert await cache.get_cached(db, cache_key) is None
            await cache.set_cached(db, cache_key=cache_key, provider_key=fake_provider_key, normalized=normalized, ttl_seconds=3600)
            cached = await cache.get_cached(db, cache_key)
            assert cached is not None
            assert cached.value == 3000.0
        finally:
            from app.domains.live_sources.models import LiveFetchCache
            await db.execute(LiveFetchCache.__table__.delete().where(LiveFetchCache.cache_key == cache_key))
            await db.commit()
    print("test_cache_roundtrip: PASSED")


async def test_live_source_survives_license_gate_and_bundle_builder():
    """Proves the zero-touch bundle_builder.py invariant: a live source
    with an ACTIVE, permitted LiveSourceProvider row rides through
    check_eligibility() and build_bundle() exactly like a document source."""
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        provider = LiveSourceProvider(
            provider_key=f"test_wb_{uuid.uuid4().hex[:8]}",
            display_name="Test World Bank", category="macro-economic-data",
            base_url="https://example.test", auth_mode="none",
            licence_state="permitted", authority_level="primary",
            is_tenant_private=False, status="ACTIVE",
        )
        db.add(provider)
        await db.flush()
        await db.commit()

        normalized = NormalizedResponse(
            provider_key=provider.provider_key, indicator_code="NY.GDP.MKTP.CD",
            indicator_label="GDP (current US$)", country_code="IN", country_label="India",
            value=3000.0, unit="", observation_period="2023", as_of="2026-07-17T00:00:00+00:00",
            source_url="https://example.test",
            citation_title="World Bank — India, GDP (current US$), 2023",
        )
        live_summary = live_sources_service.to_source_summary(normalized)

        preliminary = SourceBundle(
            source_bundle_id="sb-test-live", confidence_state="sufficient", sources=[live_summary],
        )
        licence_result = await check_eligibility(db, preliminary.sources, tenant_id=tenant_id)
        final_bundle = build_bundle(preliminary, licence_result)

        assert live_summary.id in {s.id for s in final_bundle.sources}
        assert final_bundle.eligible_source_count == 1

        await db.execute(LiveSourceProvider.__table__.delete().where(LiveSourceProvider.id == provider.id))
        await db.commit()
    print("test_live_source_survives_license_gate_and_bundle_builder: PASSED")


async def main():
    test_classifier_detects_gdp_and_country()
    test_classifier_defaults_to_world_when_no_country_matched()
    test_classifier_returns_none_for_unrelated_query()
    await test_world_bank_connector_fetches_real_data()
    await test_cache_roundtrip()
    await test_live_source_survives_license_gate_and_bundle_builder()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
