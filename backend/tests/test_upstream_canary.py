"""Tests for the upstream canary and the provider-health endpoint.

The canary's whole value is that it tells the truth about sources this
repository otherwise only ever talks to through a mock, so the assertions
here are mostly about it refusing to call something healthy when it isn't.
"""
import importlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.domains.live_sources.router as live_sources_router
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.live_sources.evidence_schemas import EvidenceRecord, EvidenceSearchResponse
from app.domains.live_sources.models import LiveSourceProvider
from app.domains.live_sources.router import _to_health
from app.domains.live_sources.schemas import NormalizedResponse

canary = importlib.import_module("scripts.check_external_sources")


def _response(**kwargs) -> EvidenceSearchResponse:
    defaults = dict(provider_key="ted", query="audit services", fetched_at="2026-08-01T00:00:00Z", records=[])
    return EvidenceSearchResponse(**{**defaults, **kwargs})


def _record(index: int = 0) -> EvidenceRecord:
    return EvidenceRecord(
        provider_key="ted", record_id=f"n{index}", record_type="EU procurement notice",
        title=f"Notice {index}", jurisdiction="EU", source_url=f"https://ted.europa.eu/{index}",
    )


def _normalized(**kwargs) -> NormalizedResponse:
    defaults = dict(
        provider_key="ons", indicator_code="CP00", indicator_label="CPIH", country_code="GB",
        country_label="United Kingdom", value=1.5, observation_period="2026-07",
        as_of="2026-08-01T00:00:00Z", source_url="https://ons.gov.uk/x", citation_title="ONS CPIH",
    )
    return NormalizedResponse(**{**defaults, **kwargs})


# ── The defect that made the old check lie ───────────────────────────────


def test_zero_records_is_a_failure_not_a_healthy_source():
    """A renamed upstream field yields HTTP 200 and an empty record list.
    The previous check tested `value in (None, [], {})`, which a response
    object carrying an empty list passes, so contract drift reported live."""
    with pytest.raises(canary.EmptyResponse):
        canary._require(_response(records=[]))


def test_a_populated_response_passes():
    assert canary._require(_response(records=[_record()])) is not None


def test_minimum_record_count_is_enforceable():
    with pytest.raises(canary.EmptyResponse):
        canary._require(_response(records=[_record()]), at_least=2)


def test_empty_list_and_none_are_failures():
    with pytest.raises(canary.EmptyResponse):
        canary._require([])
    with pytest.raises(canary.EmptyResponse):
        canary._require(None)


def test_a_metric_with_no_value_is_a_failure():
    with pytest.raises(canary.EmptyResponse):
        canary._require(_normalized(value=""))


def test_a_metric_with_no_observation_period_is_a_failure():
    with pytest.raises(canary.EmptyResponse):
        canary._require(_normalized(observation_period=""))


# ── Recency ──────────────────────────────────────────────────────────────


def test_an_observation_past_its_cadence_is_stale_not_failed():
    old = (datetime.now(timezone.utc).date() - timedelta(days=400)).isoformat()
    with pytest.raises(canary.StaleObservation):
        canary._recent_period(_normalized(observation_period=old), max_age_days=30, label="test")


def test_a_current_observation_passes():
    today = datetime.now(timezone.utc).date().isoformat()
    assert canary._recent_period(_normalized(observation_period=today), max_age_days=30, label="test")


def test_an_unparseable_period_is_not_judged():
    # Index codes and request dates are not calendar periods; inventing a
    # staleness verdict for them would generate noise, not signal.
    assert canary._recent_period(_normalized(observation_period="2015=100"), max_age_days=1, label="test")


def test_period_probes_track_the_current_year_rather_than_a_pinned_one():
    # A probe pinned to a past year answers forever out of an archive while
    # current data quietly stops flowing.
    assert canary._CURRENT_YEAR == str(datetime.now(timezone.utc).year)
    # The Congress number is arithmetic, not a constant to re-pin biennially.
    assert canary._CURRENT_CONGRESS == (datetime.now(timezone.utc).year - 1789) // 2 + 1


def test_probe_ceiling_exceeds_the_slowest_connector_budget():
    from app.core.config import get_settings
    # A ceiling below a connector's own timeout kills a request the runtime
    # would have allowed, reporting a timeout the runtime never sees.
    assert canary._PROBE_TIMEOUT_CEILING > get_settings().CELLAR_SPARQL_TIMEOUT_SECONDS


# ── Sanctions reachability, without downloading the feed ─────────────────


@pytest.mark.asyncio
async def test_feed_probe_requests_only_a_range_and_never_the_whole_list(monkeypatch):
    seen = {}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            seen["url"] = url
            seen["range"] = (headers or {}).get("Range")
            return httpx.Response(206, content=b"<sdnList>", request=httpx.Request("GET", url))

    monkeypatch.setattr(canary.httpx, "AsyncClient", _Client)
    result = await canary._probe_feed_reachable("https://example.test/sdn.xml", "")
    assert seen["range"] == "bytes=0-1023"
    assert result["reachable_url"] == "https://example.test/sdn.xml"


@pytest.mark.asyncio
async def test_feed_probe_tries_the_configured_fallback(monkeypatch):
    attempted = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            attempted.append(url)
            request = httpx.Request("GET", url)
            if "primary" in url:
                return httpx.Response(403, request=request)
            return httpx.Response(206, content=b"data", request=request)

    monkeypatch.setattr(canary.httpx, "AsyncClient", _Client)
    result = await canary._probe_feed_reachable("https://example.test/primary.xml", "https://example.test/mirror.xml")
    assert attempted == ["https://example.test/primary.xml", "https://example.test/mirror.xml"]
    assert "mirror" in result["reachable_url"]


@pytest.mark.asyncio
async def test_feed_probe_with_no_configured_url_fails():
    with pytest.raises(canary.EmptyResponse):
        await canary._probe_feed_reachable("", "")


# ── Runner behaviour ─────────────────────────────────────────────────────


def _limit():
    import asyncio
    return asyncio.Semaphore(1)


@pytest.mark.asyncio
async def test_unconfigured_is_reported_separately_from_healthy():
    result = await canary._run_probe("sam_gov", "sam_gov", lambda: None, False, _limit())
    assert result["status"] == "unconfigured"


@pytest.mark.asyncio
async def test_a_permanent_failure_is_not_retried():
    attempts = []

    async def probe():
        attempts.append(1)
        request = httpx.Request("GET", "https://example.test")
        raise httpx.HTTPStatusError("forbidden", request=request,
                                    response=httpx.Response(403, request=request))

    result = await canary._run_probe("ofac_feed", "ofac", probe, True, _limit())
    assert result["status"] == "failed"
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_once():
    attempts = []

    async def probe():
        attempts.append(1)
        if len(attempts) < 2:
            raise httpx.ConnectError("boom")
        return _response(records=[_record()])

    result = await canary._run_probe("ted", "ted", probe, True, _limit())
    assert result["status"] == "live"
    assert result["attempts"] == 2


@pytest.mark.asyncio
async def test_contract_drift_and_transport_failure_are_distinguishable():
    async def empty():
        raise canary.EmptyResponse("source returned 0 records, expected at least 1")

    async def down():
        raise httpx.ConnectError("no route to host")

    drift = await canary._run_probe("ted", "ted", empty, True, _limit())
    outage = await canary._run_probe("ted", "ted", down, True, _limit())
    assert drift["kind"] == "contract"
    assert outage["kind"] == "transport"


@pytest.mark.asyncio
async def test_a_lagging_source_reports_stale_rather_than_failed():
    async def probe():
        raise canary.StaleObservation("ONS CPIH last published 2024-01, over 120 days ago")

    result = await canary._run_probe("ons", "ons", probe, True, _limit())
    assert result["status"] == "stale"


def test_summary_counts_every_outcome_class():
    summary = canary._summarise([
        {"provider": "ted", "status": "live"},
        {"provider": "ons", "status": "stale"},
        {"provider": "ofac_feed", "status": "failed"},
        {"provider": "sam_gov", "status": "unconfigured"},
    ])
    assert summary["counts"] == {"live": 1, "stale": 1, "failed": 1, "unconfigured": 1}
    assert summary["failed"] == ["ofac_feed"]
    assert summary["unconfigured"] == ["sam_gov"]


@pytest.mark.asyncio
async def test_registry_check_skips_cleanly_without_a_database(monkeypatch):
    import app.core.database as database_module

    def explode(*args, **kwargs):
        raise RuntimeError("no database configured")

    monkeypatch.setattr(database_module, "AsyncSessionLocal", explode)
    result = await canary._check_registry({"ted"})
    assert result["status"] == "skipped"


def test_every_live_probe_maps_to_a_registry_key():
    # A probe with no provider_key can never stamp last_successful_sync and
    # is invisible to the health endpoint.
    probes = canary._build_probes()
    live_source_probes = {key for _, key, _, _ in probes if key}
    assert {"ted", "cellar", "ofac", "un_sanctions", "uk_sanctions", "eu_sanctions"} <= live_source_probes


# ── Credential redaction ─────────────────────────────────────────────────
#
# The report is printed to CI logs and uploaded as a 90-day artifact.
# httpx puts the full request URL into HTTPStatusError, and several of these
# APIs take their key as a query parameter, so an upstream 4xx reproduces
# the key verbatim. Found by running the canary for real: a Regulations.gov
# 400 printed the live key into the report.


def test_api_keys_in_error_urls_are_redacted():
    leaked = (
        "Client error '400 Bad Request' for url "
        "'https://api.regulations.gov/v4/documents?filter=x&api_key=SUPERSECRET&sort=-postedDate'"
    )
    redacted = canary._redact(leaked)
    assert "SUPERSECRET" not in redacted
    assert "api_key=[REDACTED]" in redacted
    # The rest of the message has to survive, or the report stops being useful.
    assert "400 Bad Request" in redacted


def test_every_credential_query_parameter_style_is_redacted():
    for url, secret in (
        ("https://api.bls.gov/x?registrationkey=abc123", "abc123"),
        ("https://apps.bea.gov/api/data?UserID=beakey&method=GetData", "beakey"),
        ("https://api.sam.gov/opportunities?api_key=samkey&limit=1", "samkey"),
        ("https://example.test/x?token=tok123", "tok123"),
    ):
        assert secret not in canary._redact(url), url


@pytest.mark.asyncio
async def test_a_failing_probe_never_reports_a_credential():
    async def probe():
        request = httpx.Request("GET", "https://api.regulations.gov/v4/documents?api_key=SUPERSECRET")
        raise httpx.HTTPStatusError("400", request=request, response=httpx.Response(400, request=request))

    result = await canary._run_probe("regulations_gov", "regulations_gov", probe, True, _limit())
    assert result["status"] == "failed"
    assert "SUPERSECRET" not in result["error"]


# ── Health endpoint ──────────────────────────────────────────────────────


def _provider(**kwargs) -> LiveSourceProvider:
    defaults = dict(provider_key="ted", display_name="TED", category="public-procurement",
                    base_url="https://example.test", auth_mode="none", licence_state="permitted",
                    authority_level="primary", is_tenant_private=False, status="ACTIVE",
                    tenant_id="GLOBAL_CONTROL", authority_rank=4, jurisdiction="EU",
                    integration_type="LIVE_API", freshness_sla_seconds=86400)
    return LiveSourceProvider(**{**defaults, **kwargs})


def test_never_contacted_provider_reads_unknown_not_fresh():
    health = _to_health(_provider(last_successful_sync=None), datetime.now(timezone.utc))
    assert health.freshness == "unknown"
    assert health.age_seconds is None


def test_provider_past_its_sla_reads_stale():
    now = datetime.now(timezone.utc)
    health = _to_health(_provider(last_successful_sync=now - timedelta(days=3)), now)
    assert health.freshness == "stale"
    assert health.age_seconds >= 3 * 86400


def test_provider_inside_its_sla_reads_fresh():
    now = datetime.now(timezone.utc)
    health = _to_health(_provider(last_successful_sync=now - timedelta(hours=2)), now)
    assert health.freshness == "fresh"


def test_provider_without_an_sla_reads_unmonitored():
    now = datetime.now(timezone.utc)
    health = _to_health(_provider(freshness_sla_seconds=None, last_successful_sync=now), now)
    assert health.freshness == "unmonitored"


def test_naive_timestamps_from_sqlite_do_not_raise():
    now = datetime.now(timezone.utc)
    naive = (now - timedelta(hours=1)).replace(tzinfo=None)
    assert _to_health(_provider(last_successful_sync=naive), now).freshness == "fresh"


def _health_app(rows) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(live_sources_router.router, prefix="/api/v1")

    class _Scalars:
        def all(self):
            return rows

    class _Result:
        def scalars(self):
            return _Scalars()

    class _DB:
        async def execute(self, *args, **kwargs):
            return _Result()

    app.dependency_overrides[get_db] = lambda: _DB()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user-1", tenant_id="tenant-1", email="user@example.test", role="analyst")
    return app


def test_health_endpoint_requires_authentication():
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(live_sources_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        assert client.get("/api/v1/live-sources/health").status_code == 401


def test_health_endpoint_reports_freshness_per_provider():
    now = datetime.now(timezone.utc)
    rows = [
        _provider(provider_key="ted", last_successful_sync=now - timedelta(hours=1)),
        _provider(provider_key="ofac", display_name="OFAC", last_successful_sync=None),
        _provider(provider_key="cellar", display_name="Cellar",
                  last_successful_sync=now - timedelta(days=5)),
    ]
    with TestClient(_health_app(rows)) as client:
        response = client.get("/api/v1/live-sources/health")
    assert response.status_code == 200
    by_key = {item["provider_key"]: item["freshness"] for item in response.json()}
    assert by_key == {"ted": "fresh", "ofac": "unknown", "cellar": "stale"}
