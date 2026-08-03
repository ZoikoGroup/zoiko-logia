"""Tests for the governance metadata that was recorded but not enforced:
freshness SLAs, document authority ranks, display permissions, and
identifier-based sanctions screening. Plus the canary's transition alerting
and the legislation.gov.uk edge-rejection fix.
"""
import importlib
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.domains.live_sources import sanctions_service
from app.domains.live_sources.authority import rank_for_document
from app.domains.live_sources.classifier import detect_live_data_intent
from app.domains.live_sources.connectors.legislation_gov_uk import LegislationGovUKConnector, _is_async_job
from app.domains.live_sources.connectors.sanctions_live import SanctionsLiveConnector
from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent
from app.domains.live_sources.feed_schemas import SanctionsEntry, SanctionsSnapshot
from app.domains.live_sources.models import LiveSourceProvider
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse
from app.domains.live_sources.service import (
    ProviderGovernance,
    evaluate_freshness,
    to_source_summary,
    to_synthetic_chunk,
)
from app.domains.massarius.license_gate import _resolve_live_display_state
from app.orchestration.service import _controlling_chunk_index

diff_health = importlib.import_module("scripts.diff_provider_health")


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _normalized(as_of: str, **kwargs) -> NormalizedResponse:
    defaults = dict(
        provider_key="ecb", indicator_code="FM:D", indicator_label="ECB deposit facility rate",
        country_code="EURO_AREA", country_label="Euro area", value=2.0, unit="%",
        observation_period="2026-01-05", as_of=as_of,
        source_url="https://data.ecb.europa.eu/x", citation_title="ECB — deposit facility rate",
    )
    return NormalizedResponse(**{**defaults, **kwargs})


# ── Freshness enforcement ────────────────────────────────────────────────


def test_a_figure_older_than_its_sla_is_flagged_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=42)).isoformat()
    stale, age = evaluate_freshness(_normalized(old), ProviderGovernance(freshness_sla_seconds=7 * 86400))
    assert stale is True
    assert age > 40 * 86400


def test_a_recent_figure_is_not_flagged():
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    stale, _ = evaluate_freshness(_normalized(recent), ProviderGovernance(freshness_sla_seconds=7 * 86400))
    assert stale is False


def test_a_provider_with_no_declared_sla_is_never_flagged():
    ancient = (datetime.now(timezone.utc) - timedelta(days=999)).isoformat()
    stale, age = evaluate_freshness(_normalized(ancient), ProviderGovernance())
    assert stale is False
    assert age is not None


def test_an_unparseable_timestamp_does_not_invent_an_age():
    # Guessing an age would drive a staleness claim nobody can check.
    stale, age = evaluate_freshness(_normalized("not-a-timestamp"),
                                    ProviderGovernance(freshness_sla_seconds=60))
    assert (stale, age) == (False, None)


def test_a_stale_figure_says_so_in_the_model_context():
    """fetch_live_data() returns succeeded=True after falling back to a
    stale cache entry, so without this the model receives a preserved figure
    indistinguishable from a current one."""
    stale_response = _normalized((datetime.now(timezone.utc) - timedelta(days=42)).isoformat())
    summary = to_source_summary(stale_response, is_stale=True)
    chunk = to_synthetic_chunk(stale_response, summary, is_stale=True, age_seconds=42 * 86400)
    assert "NOT CURRENT" in chunk["text"]
    assert "42 days ago" in chunk["text"]
    assert chunk["metadata"]["is_stale"] is True


def test_a_stale_figure_is_qualified_in_the_citation_title():
    stale_response = _normalized((datetime.now(timezone.utc) - timedelta(days=42)).isoformat())
    assert "may not be current" in to_source_summary(stale_response, is_stale=True).title
    # ...and a current one is not.
    assert "may not be current" not in to_source_summary(stale_response).title


def test_a_current_figure_carries_no_staleness_language():
    fresh = _normalized(datetime.now(timezone.utc).isoformat())
    chunk = to_synthetic_chunk(fresh, to_source_summary(fresh))
    assert "NOT CURRENT" not in chunk["text"]


# ── Document authority ranks ─────────────────────────────────────────────


def test_statutory_documents_outrank_professional_guidance():
    assert rank_for_document("primary", "Statutory Authority") == 1
    assert rank_for_document("secondary", "Professional Guidelines") == 5
    assert rank_for_document("internal", "Proprietary Document") == 6


def test_the_default_source_class_does_not_override_an_explicit_level():
    # "External Reference" is metadata_service's baseline default and
    # carries no information; matching on it would discard a level someone
    # actually set.
    assert rank_for_document("primary", "External Reference") == 2
    assert rank_for_document("secondary", "External Reference") == 5


def test_an_unrecognised_class_falls_back_to_the_authority_level():
    assert rank_for_document("primary", "Something Nobody Defined") == 2
    assert rank_for_document("", "") == 6


def test_a_document_only_bundle_is_ranked_by_authority_not_retrieval_order():
    """Previously every document defaulted to the weakest rank, so this
    bundle fell back to index 0 and cited the commentary as controlling."""
    chunks = [
        {"metadata": {"title": "ICAEW commentary", "source_id": "doc-guidance"}},
        {"metadata": {"title": "The Act", "source_id": "doc-statute", "jurisdiction": "GB"}},
    ]
    ranks = {"doc-guidance": 5, "doc-statute": 1}
    assert _controlling_chunk_index(chunks, "GB", ranks) == 1


def test_ranks_absent_for_every_chunk_still_fall_back_to_retrieval_order():
    chunks = [{"metadata": {"source_id": "a"}}, {"metadata": {"source_id": "b"}}]
    assert _controlling_chunk_index(chunks, "GB", {}) == 0


# ── display_permission ───────────────────────────────────────────────────


def _provider(**kwargs) -> LiveSourceProvider:
    defaults = dict(provider_key="x", display_name="X", category="c", base_url="u",
                    auth_mode="none", licence_state="permitted", authority_level="primary",
                    is_tenant_private=False, status="ACTIVE", display_permission="")
    return LiveSourceProvider(**{**defaults, **kwargs})


def test_display_permission_can_restrict_a_source_that_would_otherwise_show():
    assert _resolve_live_display_state(_provider()) == "show"
    assert _resolve_live_display_state(_provider(display_permission="summarise")) == "summarise"
    assert _resolve_live_display_state(
        _provider(display_permission="internal_reasoning_only")) == "internal_reasoning_only"


def test_display_permission_can_never_widen_exposure():
    # A licence state is a legal fact; a display preference is not
    # permission to override it.
    assert _resolve_live_display_state(
        _provider(licence_state="unknown", display_permission="show")) == "internal_reasoning_only"
    assert _resolve_live_display_state(
        _provider(authority_level="internal", display_permission="show")) == "summarise"


def test_an_invalid_display_permission_is_ignored_not_trusted():
    assert _resolve_live_display_state(_provider(display_permission="SHOW-EVERYTHING")) == "show"


# ── Identifier-based sanctions screening ─────────────────────────────────


def _seed(entries, provider_key="ofac") -> SanctionsSnapshot:
    snapshot = SanctionsSnapshot(
        provider_key=provider_key, entries=entries, fetched_at="2026-08-01T00:00:00Z",
        source_url="https://ofac.treasury.gov/x", content_sha256="ef" * 32,
    )
    sanctions_service._cache[provider_key] = (snapshot, time.monotonic() + 600)
    sanctions_service._indexes.clear()
    return snapshot


def _entry(**kwargs) -> SanctionsEntry:
    defaults = dict(provider_key="ofac", record_id="1", entity_type="individual",
                    primary_name="Ivan Ivanovich Petrov",
                    identifiers=("Passport: P1234567 (RU)",),
                    source_url="https://ofac.treasury.gov/x")
    return SanctionsEntry(**{**defaults, **kwargs})


@pytest.mark.asyncio
async def test_an_identifier_matches_even_when_the_name_does_not():
    """A passport number identifies a party; a name only describes one.
    Suppressing an identifier hit because the transliterated name differs
    would discard the strongest signal the list carries."""
    _seed([_entry()])
    _, matches = await sanctions_service.find_candidates(
        "ofac", "Completely Different Person", identifiers=("P1234567",))
    assert len(matches) == 1
    assert matches[0].method == "exact_identifier"
    assert matches[0].matched_identifier == "Passport: P1234567 (RU)"


@pytest.mark.asyncio
async def test_identifier_matching_tolerates_how_the_number_was_typed():
    _seed([_entry()])
    for supplied in ("P1234567", "p 1234 567", "P-1234567", "Passport P1234567"):
        _, matches = await sanctions_service.find_candidates("ofac", "Someone Else", identifiers=(supplied,))
        assert matches and matches[0].method == "exact_identifier", supplied


@pytest.mark.asyncio
async def test_a_short_or_unknown_identifier_produces_no_match():
    _seed([_entry()])
    # Too short to assert identity — a 3-character token collides with
    # fragments of unrelated numbers.
    _, short = await sanctions_service.find_candidates("ofac", "Someone", identifiers=("P12",))
    _, unknown = await sanctions_service.find_candidates("ofac", "Someone", identifiers=("Z99999999",))
    assert short == [] and unknown == []


@pytest.mark.asyncio
async def test_an_identifier_hit_outranks_a_name_hit_for_the_same_entry():
    _seed([_entry()])
    _, matches = await sanctions_service.find_candidates(
        "ofac", "Ivan Ivanovich Petrov", identifiers=("P1234567",))
    assert len(matches) == 1
    assert matches[0].method == "exact_identifier"


@pytest.mark.asyncio
async def test_the_screening_record_states_what_was_actually_compared():
    _seed([_entry()])
    connector = SanctionsLiveConnector("ofac", "OFAC SDN List", "https://ofac.treasury.gov/")
    with_ids = await connector.fetch(LiveDataIntent(
        provider_key="ofac", indicator_code="s", indicator_label="s", country_code="US",
        country_label="United States", company_query="Someone", screening_identifiers=("P1234567",),
    ), timeout=1)
    without = await connector.fetch(LiveDataIntent(
        provider_key="ofac", indicator_code="s", indicator_label="s", country_code="US",
        country_label="United States", company_query="Nobody Here",
    ), timeout=1)
    assert "Screened on name and 1 supplied identifier" in str(with_ids.value)
    # An unqualified "no match" would imply a stronger screen than happened.
    assert "Screened on name only; no identifiers were supplied" in str(without.value)
    assert "not sanctions clearance" in str(without.value)


def test_identifiers_are_extracted_from_a_screening_query():
    intent = detect_live_data_intent(
        'Screen "Ivan Petrov" against the OFAC SDN list, passport P1234567')
    assert intent.screening_identifiers == ("P1234567",)
    assert intent.indicator_code == "name_and_identifier_screening"


def test_a_query_with_no_identifier_is_recorded_as_a_name_only_screen():
    intent = detect_live_data_intent('Screen "Ivan Petrov" against OFAC')
    assert intent.screening_identifiers == ()
    assert intent.indicator_code == "exact_name_screening"


def test_an_unlabelled_number_is_not_screened_as_an_identifier():
    # A false identifier match is the most damaging result this path can
    # produce, so extraction is anchored to an explicit label.
    intent = detect_live_data_intent('Screen "Acme Ltd" against OFAC, invoice 4455667788')
    assert intent.screening_identifiers == ()


# ── legislation.gov.uk edge rejection ────────────────────────────────────


def test_an_empty_cloudfront_202_is_recognised_as_a_rejection():
    request = httpx.Request("GET", "https://www.legislation.gov.uk/all/data.feed")
    rejected = httpx.Response(202, headers={"x-cache": "Error from cloudfront"}, request=request)
    assert _is_async_job(rejected) is False
    # A genuine queued job announces itself.
    assert _is_async_job(httpx.Response(202, headers={"Retry-After": "5"}, request=request)) is True
    assert _is_async_job(httpx.Response(202, content=b"<feed/>", request=request)) is True


@pytest.mark.asyncio
async def test_an_edge_rejection_fails_immediately_instead_of_polling():
    """Confirmed against the live host: every endpoint returns an empty 202
    from CloudFront and never resolves, so polling only spends the user's
    latency budget to reach the same answer."""
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(202, headers={"x-cache": "Error from cloudfront"})

    async with _client(handler) as client:
        with pytest.raises(ValueError, match="rejection, not a queued feed build"):
            await LegislationGovUKConnector("https://example.test", retry_delays="0,0,0").search(
                EvidenceSearchIntent(provider_key="legislation_gov_uk", query="Companies Act"),
                timeout=1, client=client)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_genuine_async_202_is_still_polled():
    calls = []
    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://x/1</id>
    <title>Example Act</title><link rel="alternate" href="https://x/1"/></entry></feed>'''

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(202, headers={"Retry-After": "1"})
        return httpx.Response(200, content=atom)

    async with _client(handler) as client:
        result = await LegislationGovUKConnector("https://example.test", retry_delays="0,0,0").search(
            EvidenceSearchIntent(provider_key="legislation_gov_uk", query="Example Act"),
            timeout=1, client=client)
    assert len(calls) == 3
    assert result.records[0].title == "Example Act"


# ── Canary transition alerting ───────────────────────────────────────────


def _report(**statuses) -> dict:
    return {"summary": {"counts": {}},
            "providers": [{"provider": name, "status": status} for name, status in statuses.items()]}


def test_a_newly_broken_source_is_a_regression():
    changes = diff_health.compare(_report(ted="live"), _report(ted="failed"))
    assert changes["regressions"] == ["ted"]
    assert changes["recoveries"] == []


def test_a_persistently_broken_source_is_not_a_regression():
    """The EU FSF and OFAC distributions refuse this deployment's egress for
    reasons no code change fixes. Alerting on them every day is how an alert
    channel becomes noise, and then the alert that matters is muted."""
    changes = diff_health.compare(
        _report(eu_sanctions_feed="failed"), _report(eu_sanctions_feed="failed"))
    assert changes["regressions"] == []
    assert changes["persistent"] == ["eu_sanctions_feed"]


def test_a_recovery_is_reported_separately():
    changes = diff_health.compare(_report(cellar="failed"), _report(cellar="live"))
    assert changes["recoveries"] == ["cellar"]
    assert changes["regressions"] == []


def test_a_first_run_with_no_baseline_claims_nothing_about_history():
    changes = diff_health.compare({}, _report(ted="failed", cellar="live"))
    assert changes["regressions"] == []
    # An unknown previous state is not history to make claims about.
    assert changes["persistent"] == []
    assert changes["new"] == ["cellar", "ted"]


def test_a_source_going_stale_is_not_treated_as_unreachable():
    # Publishing late and being unreachable are different problems needing
    # different responses.
    changes = diff_health.compare(_report(ons="live"), _report(ons="stale"))
    assert changes["regressions"] == []


def test_a_stale_source_that_then_breaks_is_a_regression():
    changes = diff_health.compare(_report(ons="stale"), _report(ons="failed"))
    assert changes["regressions"] == ["ons"]
