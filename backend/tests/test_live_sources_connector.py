"""
Live external data source path — classifier, cache roundtrip, and the
license_gate/bundle_builder invariant that live sources ride through the
existing SourceBundle pipeline unmodified.

Requires a live DB for the cache/eligibility tests (creates real
LiveSourceProvider/LiveFetchCache rows) — run inside the backend container:
    docker compose exec backend python3 tests/test_live_sources_connector.py

test_world_bank_connector_fetches_real_data additionally makes a live HTTP
call to the World Bank API — no key required, but needs network access.
Same for the ONS/Bank of England connector tests below.
"""
import asyncio
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.domains.live_sources import cache, service as live_sources_service
from app.domains.live_sources.classifier import (
    detect_company_lookup_intent, detect_fx_intent, detect_live_data_intent,
)
from app.domains.live_sources.connectors.bank_of_england import BankOfEnglandConnector
from app.domains.live_sources.connectors.companies_house import CompaniesHouseConnector
from app.domains.live_sources.connectors.fred import FREDConnector
from app.domains.live_sources.connectors.frankfurter import FrankfurterConnector
from app.domains.live_sources.connectors.ons import ONSConnector
from app.domains.live_sources.connectors.sec_edgar import SECEdgarConnector
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


def test_classifier_routes_uk_bank_rate_to_bank_of_england():
    intent = detect_live_data_intent("What is the UK Bank Rate?")
    assert intent is not None
    assert intent.provider_key == "bank_of_england"
    assert intent.indicator_code == "IUDBEDR"
    print("test_classifier_routes_uk_bank_rate_to_bank_of_england: PASSED")


def test_classifier_bank_rate_implies_uk_with_no_country_mentioned():
    """'Bank Rate' is UK-specific vocabulary (no other central bank uses the
    term) so it should resolve to Bank of England even with zero country
    mention — unlike the genuinely ambiguous 'repo rate'/'interest rate'."""
    intent = detect_live_data_intent("What is the Bank Rate?")
    assert intent is not None
    assert intent.provider_key == "bank_of_england"
    assert intent.country_code == "GB"
    print("test_classifier_bank_rate_implies_uk_with_no_country_mentioned: PASSED")


def test_classifier_repo_rate_still_requires_explicit_country():
    """Unlike 'bank rate', 'repo rate' is ambiguous across countries and
    must NOT resolve to anything without an explicit UK mention."""
    intent = detect_live_data_intent("What is the repo rate?")
    assert intent is None
    print("test_classifier_repo_rate_still_requires_explicit_country: PASSED")


def test_classifier_jurisdiction_dropdown_blocks_bank_rate_uk_override():
    """Regression test for the reported bug: selecting US in the jurisdiction
    dropdown while asking a country-agnostic question ('What is the Bank
    Rate?') must NOT silently return UK data. Neither World Bank nor Bank of
    England has a US 'bank rate' series, so this should resolve to no live
    source at all rather than the wrong country's."""
    intent = detect_live_data_intent("What is the Bank Rate?", jurisdiction="US")
    assert intent is None
    print("test_classifier_jurisdiction_dropdown_blocks_bank_rate_uk_override: PASSED")


def test_classifier_jurisdiction_dropdown_supplies_country_when_text_has_none():
    """The jurisdiction dropdown should let a country-agnostic query still
    resolve correctly — e.g. selecting UK and asking just 'What is
    inflation?' (no country named in the text) should route to ONS."""
    intent = detect_live_data_intent("What is inflation?", jurisdiction="UK")
    assert intent is not None
    assert intent.provider_key == "ons"
    assert intent.country_code == "GB"
    print("test_classifier_jurisdiction_dropdown_supplies_country_when_text_has_none: PASSED")


def test_classifier_jurisdiction_dropdown_wins_over_conflicting_query_text():
    """Confirmed design choice: the dropdown wins even when the query text
    names a different country — selecting US while asking 'What is UK
    inflation?' should return US data via World Bank, not UK via ONS."""
    intent = detect_live_data_intent("What is UK inflation?", jurisdiction="US")
    assert intent is not None
    assert intent.provider_key == "world_bank"
    assert intent.country_code == "US"
    print("test_classifier_jurisdiction_dropdown_wins_over_conflicting_query_text: PASSED")


def test_classifier_explicit_unmapped_jurisdiction_returns_none_not_fallback():
    """Regression test for the reported bug: an EXPLICIT jurisdiction
    selection with no live-data country mapping (UAE/IFRS/EU) must return
    no live source at all — never fall back to query-text matching or an
    implied-country shortcut, since both could substitute a country the
    user never asked for. Selecting 'UAE' and asking 'What is the Bank
    Rate?' previously fell back to the UK-implied shortcut and silently
    returned the UK's Bank Rate; it must now return None."""
    for jurisdiction in ("UAE", "IFRS", "EU"):
        intent = detect_live_data_intent("What is the Bank Rate?", jurisdiction=jurisdiction)
        assert intent is None, f"jurisdiction={jurisdiction!r} should yield no live source, got {intent}"
        intent = detect_live_data_intent("What is inflation?", jurisdiction=jurisdiction)
        assert intent is None, f"jurisdiction={jurisdiction!r} should yield no live source, got {intent}"
    print("test_classifier_explicit_unmapped_jurisdiction_returns_none_not_fallback: PASSED")


def test_classifier_unset_jurisdiction_still_falls_back_to_query_text():
    """Contrast with the above: a genuinely UNSET jurisdiction ("" / Any) is
    the one case that should still fall back to query-text matching and
    default to the World aggregate when no country is named."""
    intent = detect_live_data_intent("What is inflation?", jurisdiction="")
    assert intent is not None
    assert intent.provider_key == "world_bank"
    assert intent.country_code == "WLD"
    print("test_classifier_unset_jurisdiction_still_falls_back_to_query_text: PASSED")


def test_classifier_routes_uk_inflation_to_ons():
    intent = detect_live_data_intent("What is UK inflation?")
    assert intent is not None
    assert intent.provider_key == "ons"
    assert intent.indicator_code == "CP00"
    print("test_classifier_routes_uk_inflation_to_ons: PASSED")


def test_classifier_uk_gdp_and_unemployment_now_route_to_ons():
    """ONS GDP/unemployment coverage was added this round — UK GDP and
    unemployment queries now route to ONS instead of falling through to
    World Bank (supersedes the old World Bank fallback behavior)."""
    gdp_intent = detect_live_data_intent("What is the UK GDP?")
    assert gdp_intent is not None
    assert gdp_intent.provider_key == "ons"
    assert gdp_intent.indicator_code == "A--T"
    assert gdp_intent.country_code == "GB"

    unemployment_intent = detect_live_data_intent("What is UK unemployment?")
    assert unemployment_intent is not None
    assert unemployment_intent.provider_key == "ons"
    assert unemployment_intent.indicator_code == "UNEMPLOYMENT_RATE"
    print("test_classifier_uk_gdp_and_unemployment_now_route_to_ons: PASSED")


def test_classifier_fred_implies_us_for_fed_funds_and_treasury():
    """'Fed funds rate'/'Treasury yield' are unambiguously US vocabulary,
    same implies_country treatment as 'Bank Rate' for GB — but never
    against an explicit, conflicting jurisdiction."""
    intent = detect_live_data_intent("What is the fed funds rate?")
    assert intent is not None
    assert intent.provider_key == "fred"
    assert intent.indicator_code == "FEDFUNDS"
    assert intent.country_code == "US"

    intent2 = detect_live_data_intent("What is the 10-year treasury yield?")
    assert intent2 is not None
    assert intent2.indicator_code == "DGS10"

    blocked = detect_live_data_intent("What is the fed funds rate?", jurisdiction="UK")
    assert blocked is None
    print("test_classifier_fred_implies_us_for_fed_funds_and_treasury: PASSED")


def test_classifier_fx_intent_detection():
    """FX pairs are cross-country — detected independent of jurisdiction."""
    intent = detect_fx_intent("What is the exchange rate from USD to GBP?")
    assert intent is not None
    assert intent.provider_key == "frankfurter"
    assert intent.indicator_code == "USD_GBP"

    # Not gated by jurisdiction — an unrelated/unmapped jurisdiction must
    # not block an FX query.
    via_full = detect_live_data_intent("What is the exchange rate from USD to GBP?", jurisdiction="UAE")
    assert via_full is not None
    assert via_full.provider_key == "frankfurter"

    # No FX trigger phrase and fewer than 2 currencies -> no match
    assert detect_fx_intent("What is the price of gold?") is None
    print("test_classifier_fx_intent_detection: PASSED")


def test_classifier_company_lookup_extracts_correct_name():
    """Regression test for a real extraction bug found during
    implementation: the company-name regex originally captured the whole
    leading clause ('Show me Apple') instead of just the company name,
    because [A-Z] under re.IGNORECASE matched the sentence-initial
    capitalized word 'Show' too. Must extract only 'Apple'."""
    intent = detect_company_lookup_intent("Show me Apple's filings", jurisdiction="US")
    assert intent is not None
    assert intent.provider_key == "sec_edgar"
    assert intent.company_query == "Apple"
    print("test_classifier_company_lookup_extracts_correct_name: PASSED")


def test_classifier_company_lookup_requires_resolvable_jurisdiction():
    """No jurisdiction, or one that doesn't resolve to US/UK, must return
    None rather than guessing which company registry to query."""
    assert detect_company_lookup_intent("Show me Apple's filings", jurisdiction="") is None
    assert detect_company_lookup_intent("Show me Apple's filings", jurisdiction="UAE") is None
    print("test_classifier_company_lookup_requires_resolvable_jurisdiction: PASSED")


def test_classifier_company_lookup_picks_provider_by_jurisdiction():
    us_intent = detect_company_lookup_intent("What is the revenue of Microsoft?", jurisdiction="US")
    assert us_intent is not None
    assert us_intent.provider_key == "sec_edgar"
    assert us_intent.indicator_code == "Revenues"
    assert us_intent.company_query == "Microsoft"

    uk_intent = detect_company_lookup_intent("What are the financials for Tesco?", jurisdiction="UK")
    assert uk_intent is not None
    assert uk_intent.provider_key == "companies_house"
    assert uk_intent.company_query == "Tesco"
    print("test_classifier_company_lookup_picks_provider_by_jurisdiction: PASSED")


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


async def test_ons_connector_fetches_real_data():
    connector = ONSConnector(base_url=settings.ONS_API_BASE_URL)
    intent = LiveDataIntent(
        provider_key="ons", indicator_code="CP00", indicator_label="CPIH Index (Overall Index, 2015=100)",
        country_code="GB", country_label="United Kingdom",
    )
    normalized = await connector.fetch(intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
    assert normalized.provider_key == "ons"
    assert normalized.value not in (None, "")
    assert "Index" in normalized.unit
    print("test_ons_connector_fetches_real_data: PASSED")


async def test_bank_of_england_connector_fetches_real_data():
    connector = BankOfEnglandConnector(base_url=settings.BANK_OF_ENGLAND_API_BASE_URL)
    intent = LiveDataIntent(
        provider_key="bank_of_england", indicator_code="IUDBEDR", indicator_label="Bank Rate",
        country_code="GB", country_label="United Kingdom",
    )
    normalized = await connector.fetch(intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
    assert normalized.provider_key == "bank_of_england"
    assert isinstance(normalized.value, float)
    print("test_bank_of_england_connector_fetches_real_data: PASSED")


async def test_ons_gdp_and_unemployment_connectors_fetch_real_data():
    connector = ONSConnector(base_url=settings.ONS_API_BASE_URL)

    gdp_intent = LiveDataIntent(
        provider_key="ons", indicator_code="A--T",
        indicator_label="Monthly GDP Index (Seasonally Adjusted, 2016=100)",
        country_code="GB", country_label="United Kingdom",
    )
    gdp_normalized = await connector.fetch(gdp_intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
    assert gdp_normalized.value not in (None, "")

    unemployment_intent = LiveDataIntent(
        provider_key="ons", indicator_code="UNEMPLOYMENT_RATE",
        indicator_label="Unemployment Rate (16+, Seasonally Adjusted)",
        country_code="GB", country_label="United Kingdom",
    )
    unemployment_normalized = await connector.fetch(unemployment_intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
    assert unemployment_normalized.value not in (None, "")
    print("test_ons_gdp_and_unemployment_connectors_fetch_real_data: PASSED")


async def test_frankfurter_connector_fetches_real_data():
    connector = FrankfurterConnector(base_url=settings.FRANKFURTER_API_BASE_URL)
    intent = LiveDataIntent(
        provider_key="frankfurter", indicator_code="USD_GBP", indicator_label="USD/GBP exchange rate",
        country_code="FX", country_label="Global",
    )
    normalized = await connector.fetch(intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
    assert normalized.provider_key == "frankfurter"
    assert isinstance(normalized.value, float)
    print("test_frankfurter_connector_fetches_real_data: PASSED")


async def test_sec_edgar_connector_fetches_real_data():
    connector = SECEdgarConnector(
        base_url=settings.SEC_EDGAR_API_BASE_URL,
        user_agent=settings.SEC_EDGAR_USER_AGENT or "KritonRAG-test test@example.com",
    )
    intent = LiveDataIntent(
        provider_key="sec_edgar", indicator_code="Assets", indicator_label="Total Assets",
        country_code="US", country_label="United States", company_query="Apple",
    )
    normalized = await connector.fetch(intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
    assert normalized.provider_key == "sec_edgar"
    assert normalized.value not in (None, "")
    assert normalized.company_query == "Apple"
    print("test_sec_edgar_connector_fetches_real_data: PASSED")


async def test_fred_connector_skips_gracefully_without_key():
    """FRED needs a real API key you register for yourself — this test
    stays green either way: it confirms the connector raises a clear,
    diagnosable error when unconfigured, and would exercise a real fetch
    the moment FRED_API_KEY is set in .env."""
    connector = FREDConnector(base_url=settings.FRED_API_BASE_URL, api_key=settings.FRED_API_KEY)
    intent = LiveDataIntent(
        provider_key="fred", indicator_code="FEDFUNDS", indicator_label="Federal Funds Effective Rate",
        country_code="US", country_label="United States",
    )
    if not settings.FRED_API_KEY:
        try:
            await connector.fetch(intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
            raise AssertionError("expected a clear error when FRED_API_KEY is unset")
        except ValueError as e:
            assert "FRED_API_KEY" in str(e)
        print("test_fred_connector_skips_gracefully_without_key: SKIPPED (no FRED_API_KEY configured)")
        return
    normalized = await connector.fetch(intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
    assert normalized.provider_key == "fred"
    print("test_fred_connector_skips_gracefully_without_key: PASSED (real key configured)")


async def test_companies_house_connector_skips_gracefully_without_key():
    """Same discipline as FRED above — Companies House needs a real key."""
    connector = CompaniesHouseConnector(
        base_url=settings.COMPANIES_HOUSE_API_BASE_URL, api_key=settings.COMPANIES_HOUSE_API_KEY
    )
    intent = LiveDataIntent(
        provider_key="companies_house", indicator_code="profile", indicator_label="Company Profile",
        country_code="GB", country_label="United Kingdom", company_query="Tesco",
    )
    if not settings.COMPANIES_HOUSE_API_KEY:
        try:
            await connector.fetch(intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
            raise AssertionError("expected a clear error when COMPANIES_HOUSE_API_KEY is unset")
        except ValueError as e:
            assert "COMPANIES_HOUSE_API_KEY" in str(e)
        print("test_companies_house_connector_skips_gracefully_without_key: SKIPPED (no COMPANIES_HOUSE_API_KEY configured)")
        return
    normalized = await connector.fetch(intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
    assert normalized.provider_key == "companies_house"
    print("test_companies_house_connector_skips_gracefully_without_key: PASSED (real key configured)")


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
    test_classifier_routes_uk_bank_rate_to_bank_of_england()
    test_classifier_bank_rate_implies_uk_with_no_country_mentioned()
    test_classifier_repo_rate_still_requires_explicit_country()
    test_classifier_jurisdiction_dropdown_blocks_bank_rate_uk_override()
    test_classifier_jurisdiction_dropdown_supplies_country_when_text_has_none()
    test_classifier_jurisdiction_dropdown_wins_over_conflicting_query_text()
    test_classifier_explicit_unmapped_jurisdiction_returns_none_not_fallback()
    test_classifier_unset_jurisdiction_still_falls_back_to_query_text()
    test_classifier_routes_uk_inflation_to_ons()
    test_classifier_uk_gdp_and_unemployment_now_route_to_ons()
    test_classifier_fred_implies_us_for_fed_funds_and_treasury()
    test_classifier_fx_intent_detection()
    test_classifier_company_lookup_extracts_correct_name()
    test_classifier_company_lookup_requires_resolvable_jurisdiction()
    test_classifier_company_lookup_picks_provider_by_jurisdiction()
    await test_world_bank_connector_fetches_real_data()
    await test_ons_connector_fetches_real_data()
    await test_ons_gdp_and_unemployment_connectors_fetch_real_data()
    await test_bank_of_england_connector_fetches_real_data()
    await test_frankfurter_connector_fetches_real_data()
    await test_sec_edgar_connector_fetches_real_data()
    await test_fred_connector_skips_gracefully_without_key()
    await test_companies_house_connector_skips_gracefully_without_key()
    await test_cache_roundtrip()
    await test_live_source_survives_license_gate_and_bundle_builder()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
