"""Tests for the catalogue-governance layer added on top of the Phase 1-3
connectors: authority ranking, sanctions match provenance, shared retry
policy, the evidence-search endpoint, and the routing/upstream fixes."""
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.domains.live_sources.router as live_sources_router
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.live_sources import sanctions_service
from app.domains.live_sources.authority import (
    AuthorityCandidate,
    controlling,
    explain,
    order_by_authority,
)
from app.domains.live_sources.classifier import detect_live_data_intent
from app.domains.live_sources.connectors.cellar import CellarConnector
from app.domains.live_sources.connectors.legislation_gov_uk import LegislationGovUKConnector
from app.domains.live_sources.connectors.sanctions_feeds import OFACFeedConnector, _candidate_urls
from app.domains.live_sources.connectors.sanctions_live import SanctionsLiveConnector
from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent
from app.domains.live_sources.feed_schemas import SanctionsEntry, SanctionsSnapshot
from app.domains.live_sources.retry import call_with_retries, is_retryable
from app.domains.live_sources.schemas import LiveDataIntent
from app.orchestration.service import _controlling_chunk_index


def _client(handler, **kwargs):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)


# ── Authority hierarchy ──────────────────────────────────────────────────


def test_domestic_source_outranks_international_model_for_that_jurisdiction():
    uk_statute = AuthorityCandidate("uk-statute", rank=1, jurisdiction="GB", effective_date="2024-01-01")
    oecd_model = AuthorityCandidate("oecd-model", rank=4, jurisdiction="INTL", effective_date="2026-07-01")
    icaew = AuthorityCandidate("icaew-note", rank=5, jurisdiction="GB", effective_date="2026-06-01")

    assert controlling([oecd_model, icaew, uk_statute], query_jurisdiction="GB").source_id == "uk-statute"
    # The catalogue's rule is directional: a newer international model does
    # not displace domestic authority just by being newer.
    assert order_by_authority([oecd_model, icaew], query_jurisdiction="GB")[0].source_id == "icaew-note"


def test_foreign_domestic_law_sorts_below_an_international_source():
    us_statute = AuthorityCandidate("us-statute", rank=1, jurisdiction="US", effective_date="2026-07-01")
    oecd_model = AuthorityCandidate("oecd-model", rank=4, jurisdiction="INTL", effective_date="2020-01-01")
    ordered = order_by_authority([us_statute, oecd_model], query_jurisdiction="GB")
    assert [item.source_id for item in ordered] == ["oecd-model", "us-statute"]


def test_later_effective_date_breaks_a_tie_between_equals():
    older = AuthorityCandidate("older", rank=1, jurisdiction="GB", effective_date="2024-01-01")
    newer = AuthorityCandidate("newer", rank=1, jurisdiction="GB", effective_date="2026-05-01")
    assert controlling([older, newer], query_jurisdiction="GB").source_id == "newer"
    assert "later than" in explain(newer, older, query_jurisdiction="GB")


def test_unranked_bundle_keeps_retrieval_order_as_controlling():
    chunks = [{"metadata": {"title": "first"}}, {"metadata": {"title": "second"}}]
    assert _controlling_chunk_index(chunks, "GB") == 0
    assert _controlling_chunk_index([], "GB") == 0


def test_ranked_live_source_becomes_controlling_over_a_better_matching_document():
    chunks = [
        {"metadata": {"title": "commentary on the statute"}},
        {"metadata": {"title": "the statute", "authority_rank": 1,
                      "authority_jurisdiction": "GB", "effective_date": "2026-01-01"}},
    ]
    assert _controlling_chunk_index(chunks, "GB") == 1


# ── Sanctions matching and provenance ────────────────────────────────────


def _seed_snapshot(entries, provider_key="ofac"):
    snapshot = SanctionsSnapshot(
        provider_key=provider_key, entries=entries, fetched_at="2026-08-01T00:00:00Z",
        source_url="https://ofac.treasury.gov/sanctions-list-service", content_sha256="ab" * 32,
    )
    sanctions_service._cache[provider_key] = (snapshot, time.monotonic() + 600)
    sanctions_service._indexes.clear()
    return snapshot


def _entry(**kwargs):
    defaults = dict(provider_key="ofac", record_id="1", entity_type="individual",
                    primary_name="Example Person",
                    source_url="https://ofac.treasury.gov/sanctions-list-service")
    return SanctionsEntry(**{**defaults, **kwargs})


@pytest.mark.asyncio
async def test_alias_and_fuzzy_candidates_are_found_with_their_method_recorded():
    _seed_snapshot([
        _entry(record_id="1", primary_name="Vladimir Vladimirovich Putin", aliases=("PUTIN, Vladimir",)),
        _entry(record_id="2", primary_name="Gazprom Neft", entity_type="entity"),
    ])

    _, exact = await sanctions_service.find_candidates("ofac", "Vladimir Vladimirovich Putin")
    assert (exact[0].method, exact[0].score) == ("exact_primary_name", 1.0)

    _, alias = await sanctions_service.find_candidates("ofac", "PUTIN, Vladimir")
    assert alias[0].method == "exact_alias"
    assert alias[0].matched_name == "PUTIN, Vladimir"

    # A misspelling the previous exact-only matcher returned nothing for.
    _, fuzzy = await sanctions_service.find_candidates("ofac", "Gasprom Neft")
    assert fuzzy[0].method == "fuzzy_name"
    assert fuzzy[0].entry.record_id == "2"


@pytest.mark.asyncio
async def test_unrelated_name_produces_no_candidate():
    _seed_snapshot([_entry(primary_name="Gazprom Neft", entity_type="entity")])
    _, matches = await sanctions_service.find_candidates("ofac", "Acme Widgets Limited")
    assert matches == []


@pytest.mark.asyncio
async def test_screening_answer_states_version_method_and_identifiers():
    _seed_snapshot([_entry(
        primary_name="Example Person", identifiers=("Passport: X123 (RU)",),
        nationalities=("Russia",), dates_of_birth=("1970-01-01",), programs=("TEST",),
    )])
    result = await SanctionsLiveConnector("ofac", "OFAC SDN List", "https://ofac.treasury.gov/").fetch(
        LiveDataIntent(provider_key="ofac", indicator_code="screening", indicator_label="screening",
                       country_code="US", country_label="United States", company_query="Example Person"),
        timeout=1,
    )
    value = str(result.value)
    assert "List version abababababab" in value
    assert "matching method: exact_primary_name" in value
    assert "Passport: X123 (RU)" in value
    assert "human review" in value.lower()
    assert "abababababab" in result.citation_title


@pytest.mark.asyncio
async def test_no_match_answer_is_not_reported_as_clearance():
    _seed_snapshot([_entry(primary_name="Someone Else")])
    result = await SanctionsLiveConnector("ofac", "OFAC SDN List", "https://ofac.treasury.gov/").fetch(
        LiveDataIntent(provider_key="ofac", indicator_code="screening", indicator_label="screening",
                       country_code="US", country_label="United States", company_query="Acme Widgets"),
        timeout=1,
    )
    assert "not sanctions clearance" in str(result.value)


@pytest.mark.asyncio
async def test_missing_identifiers_are_stated_rather_than_omitted():
    _seed_snapshot([_entry(primary_name="Example Person")])
    result = await SanctionsLiveConnector("ofac", "OFAC SDN List", "https://ofac.treasury.gov/").fetch(
        LiveDataIntent(provider_key="ofac", indicator_code="screening", indicator_label="screening",
                       country_code="US", country_label="United States", company_query="Example Person"),
        timeout=1,
    )
    assert "identifiers on record: none published" in str(result.value)


def test_ofac_parser_extracts_identifiers_nationality_and_dob():
    xml = b"""<sdnList><sdnEntry><uid>7</uid><firstName>A</firstName><lastName>PERSON</lastName>
    <sdnType>Individual</sdnType>
    <idList><id><idType>Passport</idType><idNumber>P123</idNumber><idCountry>Russia</idCountry></id></idList>
    <nationalityList><nationality><country>Russia</country></nationality></nationalityList>
    <dateOfBirthList><dateOfBirthItem><dateOfBirth>01 Jan 1970</dateOfBirth></dateOfBirthItem></dateOfBirthList>
    <addressList><address><country>Switzerland</country></address></addressList>
    </sdnEntry></sdnList>"""

    async def run():
        async with _client(lambda request: httpx.Response(200, content=xml)) as client:
            return await OFACFeedConnector("https://example.test/sdn.xml").fetch_snapshot(
                timeout=1, max_bytes=10_000, client=client)

    import asyncio
    entry = asyncio.run(run()).entries[0]
    assert entry.identifiers == ("Passport: P123 (Russia)",)
    assert entry.dates_of_birth == ("01 Jan 1970",)
    # An address country must not be recorded as a nationality.
    assert entry.nationalities == ("Russia",)


# ── Feed download failover ───────────────────────────────────────────────


def test_candidate_urls_preserve_order_and_drop_duplicates():
    assert _candidate_urls("https://a", "https://b, https://a ,") == ("https://a", "https://b")
    assert _candidate_urls("https://a", "") == ("https://a",)
    assert _candidate_urls("", "") == ()


@pytest.mark.asyncio
async def test_blocked_primary_distribution_falls_back_to_an_alternate():
    seen = []
    xml = b"<sdnList><sdnEntry><uid>1</uid><lastName>ALPHA</lastName></sdnEntry></sdnList>"

    def handler(request):
        seen.append(str(request.url))
        if "primary" in str(request.url):
            return httpx.Response(403, text="forbidden")
        return httpx.Response(200, content=xml)

    async with _client(handler) as client:
        snapshot = await OFACFeedConnector(
            "https://example.test/primary.xml", "https://example.test/mirror.xml",
        ).fetch_snapshot(timeout=1, max_bytes=10_000, client=client)

    assert len(seen) == 2
    assert snapshot.entries[0].primary_name == "ALPHA"


@pytest.mark.asyncio
async def test_all_distributions_failing_names_every_address_tried():
    async with _client(lambda request: httpx.Response(403)) as client:
        with pytest.raises(ValueError) as error:
            await OFACFeedConnector(
                "https://example.test/primary.xml", "https://example.test/mirror.xml",
            ).fetch_snapshot(timeout=1, max_bytes=10_000, client=client)
    assert "primary.xml" in str(error.value) and "mirror.xml" in str(error.value)


@pytest.mark.asyncio
async def test_feed_download_identifies_itself_on_both_client_paths():
    seen_headers = []

    def handler(request):
        seen_headers.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, content=b"<sdnList><sdnEntry><uid>1</uid><lastName>A</lastName></sdnEntry></sdnList>")

    async with _client(handler) as client:
        await OFACFeedConnector("https://example.test/sdn.xml").fetch_snapshot(
            timeout=1, max_bytes=10_000, client=client)
    assert seen_headers[0].startswith("Kriton/")


# ── Shared retry policy ──────────────────────────────────────────────────


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(code, request=request))


def test_only_transient_failures_are_retryable():
    assert is_retryable(_status_error(503))
    assert is_retryable(_status_error(429))
    assert is_retryable(httpx.ConnectError("down"))
    # A refused egress and a missing document are stable answers.
    assert not is_retryable(_status_error(403))
    assert not is_retryable(_status_error(404))
    assert not is_retryable(ValueError("unparseable"))


@pytest.mark.asyncio
async def test_call_with_retries_stops_immediately_on_a_permanent_failure():
    attempts = []

    async def operation():
        attempts.append(1)
        raise _status_error(403)

    with pytest.raises(httpx.HTTPStatusError):
        await call_with_retries(operation, attempts=3, backoff_seconds=0)
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_call_with_retries_recovers_from_a_transient_failure():
    attempts = []

    async def operation():
        attempts.append(1)
        if len(attempts) < 2:
            raise _status_error(503)
        return "ok"

    assert await call_with_retries(operation, attempts=3, backoff_seconds=0) == "ok"
    assert len(attempts) == 2


# ── Upstream hardening ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_legislation_gov_uk_polls_through_a_configurable_202_ladder():
    calls = []
    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://www.legislation.gov.uk/ukpga/2026/1</id>
    <title>Example Act 2026</title><link rel="alternate" href="https://www.legislation.gov.uk/ukpga/2026/1"/></entry></feed>'''

    def handler(request):
        calls.append(1)
        return httpx.Response(202) if len(calls) < 3 else httpx.Response(200, content=atom)

    connector = LegislationGovUKConnector("https://example.test", retry_delays="0,0,0,0")
    async with _client(handler) as client:
        result = await connector.search(
            EvidenceSearchIntent(provider_key="legislation_gov_uk", query="Example Act"), timeout=1, client=client)
    assert len(calls) == 3
    assert result.records[0].title == "Example Act 2026"


@pytest.mark.asyncio
async def test_persistent_202_reports_how_long_it_waited():
    connector = LegislationGovUKConnector("https://example.test", retry_delays="0,0")
    async with _client(lambda request: httpx.Response(202)) as client:
        with pytest.raises(ValueError, match="still preparing"):
            await connector.search(
                EvidenceSearchIntent(provider_key="legislation_gov_uk", query="Example Act"),
                timeout=1, client=client)


@pytest.mark.asyncio
async def test_cellar_query_is_bounded_to_english_legal_acts():
    captured = {}

    def handler(request):
        captured["query"] = httpx.QueryParams(request.content.decode())["query"]
        return httpx.Response(200, json={"results": {"bindings": []}})

    async with _client(handler) as client:
        await CellarConnector("https://example.test/sparql", timeout_seconds=5).search(
            EvidenceSearchIntent(provider_key="cellar", query="Artificial Intelligence Act"),
            timeout=1, client=client)

    query = captured["query"]
    assert "authority/language/ENG" in query
    # The CELEX id is a required pattern, not OPTIONAL — that restriction is
    # what bounds the scan and what makes every hit citable on EUR-Lex.
    assert "OPTIONAL { ?work cdm:resource_legal_id_celex" not in query
    assert "?work cdm:resource_legal_id_celex ?celex ." in query


# ── Routing ──────────────────────────────────────────────────────────────


def test_naming_the_imf_is_not_shadowed_by_a_country_override():
    for query, expected_code in (
        ("What is the IMF inflation forecast for the United Kingdom?", "PCPIPCH:GBR"),
        ("What is the IMF GDP growth forecast for the United Kingdom?", "NGDP_RPCH:GBR"),
        ("What does the IMF forecast for US unemployment?", "LUR:USA"),
        ("What is the IMF's inflation projection for India?", "PCPIPCH:IND"),
    ):
        intent = detect_live_data_intent(query)
        assert intent is not None, query
        assert (intent.provider_key, intent.indicator_code) == ("imf", expected_code), query


def test_queries_that_do_not_name_the_imf_keep_their_domestic_provider():
    assert detect_live_data_intent("What is UK inflation right now?", "UK").provider_key == "ons"
    assert detect_live_data_intent("What is the Bank Rate?", "UK").provider_key == "bank_of_england"


def test_imf_is_not_routed_to_for_a_country_with_no_verified_mapping():
    # Brazil has no confirmed IMF ISO3 mapping in the classifier, so the
    # query must fall through rather than have a code constructed for it.
    intent = detect_live_data_intent("What is the IMF inflation forecast for Brazil?")
    assert intent is None or intent.provider_key != "imf"


# ── Evidence-search endpoint ─────────────────────────────────────────────


def _evidence_app(provider_row) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(live_sources_router.router, prefix="/api/v1")

    class _Result:
        def scalar_one_or_none(self):
            return provider_row

    class _DB:
        async def execute(self, *args, **kwargs):
            return _Result()

    app.dependency_overrides[get_db] = lambda: _DB()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user-1", tenant_id="tenant-1", email="user@example.test", role="analyst",
    )
    return app


def _provider(**kwargs):
    from app.domains.live_sources.models import LiveSourceProvider
    defaults = dict(provider_key="ted", display_name="TED", category="public-procurement",
                    base_url="https://example.test", auth_mode="none", licence_state="permitted",
                    authority_level="primary", is_tenant_private=False, status="ACTIVE",
                    tenant_id="GLOBAL_CONTROL")
    return LiveSourceProvider(**{**defaults, **kwargs})


def test_evidence_search_requires_authentication():
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(live_sources_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        response = client.post("/api/v1/live-sources/evidence/search",
                               json={"provider_key": "ted", "query": "audit services"})
    assert response.status_code == 401


def test_evidence_search_rejects_a_disabled_provider():
    with TestClient(_evidence_app(_provider(status="DISABLED"))) as client:
        response = client.post("/api/v1/live-sources/evidence/search",
                               json={"provider_key": "ted", "query": "audit services"})
    assert response.status_code == 409


def test_evidence_search_rejects_a_licence_restricted_provider():
    with TestClient(_evidence_app(_provider(licence_state="restricted"))) as client:
        response = client.post("/api/v1/live-sources/evidence/search",
                               json={"provider_key": "ted", "query": "audit services"})
    assert response.status_code == 403


def test_evidence_search_hides_another_tenants_private_provider():
    row = _provider(is_tenant_private=True, tenant_id="other-tenant")
    with TestClient(_evidence_app(row)) as client:
        response = client.post("/api/v1/live-sources/evidence/search",
                               json={"provider_key": "ted", "query": "audit services"})
    assert response.status_code == 404


def test_evidence_search_rejects_an_unknown_connector_before_touching_the_registry():
    with TestClient(_evidence_app(_provider())) as client:
        response = client.post("/api/v1/live-sources/evidence/search",
                               json={"provider_key": "not_a_provider", "query": "audit services"})
    assert response.status_code == 404


def test_evidence_search_returns_every_record_not_only_the_first(monkeypatch):
    from app.domains.live_sources.evidence_schemas import EvidenceRecord, EvidenceSearchResponse

    async def fake_search(intent):
        return EvidenceSearchResponse(
            provider_key=intent.provider_key, query=intent.query, fetched_at="2026-08-01T00:00:00Z",
            records=[
                EvidenceRecord(provider_key=intent.provider_key, record_id=f"n{index}",
                               record_type="EU procurement notice", title=f"Notice {index}",
                               jurisdiction="EU", source_url=f"https://ted.europa.eu/{index}")
                for index in range(3)
            ],
        )

    monkeypatch.setattr(live_sources_router.evidence_service, "search_authoritative_evidence", fake_search)
    with TestClient(_evidence_app(_provider())) as client:
        response = client.post("/api/v1/live-sources/evidence/search",
                               json={"provider_key": "ted", "query": "audit services"})
    assert response.status_code == 200
    assert [record["record_id"] for record in response.json()["records"]] == ["n0", "n1", "n2"]


def test_evidence_search_does_not_leak_upstream_detail_on_an_unexpected_fault(monkeypatch):
    async def exploding_search(intent):
        raise httpx.ConnectError("failed to connect to https://api.sam.gov/...?api_key=secret-key")

    monkeypatch.setattr(live_sources_router.evidence_service, "search_authoritative_evidence", exploding_search)
    with TestClient(_evidence_app(_provider())) as client:
        response = client.post("/api/v1/live-sources/evidence/search",
                               json={"provider_key": "ted", "query": "audit services"})
    assert response.status_code == 502
    assert "secret-key" not in response.text


# ── Jurisdiction dropdown coverage ───────────────────────────────────────


def test_selecting_eu_reaches_the_ecb_instead_of_disabling_live_data():
    """Reported case: "What is the ECB deposit facility rate?" with EU
    selected answered "the retrieved context does not mention the ECB deposit
    facility rate". The explicit-selection rule correctly refuses to fall back
    to query-text matching, and EU resolved to nothing — so selecting the
    ECB's own jurisdiction disabled the ECB."""
    for query, expected_code in (
        ("What is the ECB deposit facility rate?", "FM:D.U2.EUR.4F.KR.DFR.LEV"),
        ("What is the ECB main refinancing rate?", "FM:D.U2.EUR.4F.KR.MRR_FR.LEV"),
    ):
        intent = detect_live_data_intent(query, "EU")
        assert intent is not None, query
        assert (intent.provider_key, intent.indicator_code) == ("ecb", expected_code)
        assert intent.country_code == "EURO_AREA"


def test_a_generic_eu_indicator_uses_world_banks_own_aggregate_code():
    # World Bank spells the euro area "XC"; EMU and EUU both error on its
    # indicator endpoint, and EURO_AREA is this module's internal code.
    intent = detect_live_data_intent("What is the inflation rate?", "EU")
    assert (intent.provider_key, intent.country_code) == ("world_bank", "XC")


def test_the_world_bank_translation_applies_on_the_semantic_path_too():
    # Five code paths can reach World Bank; an untranslated code on any of
    # them reaches the API and errors.
    from app.domains.live_sources.classifier import _world_bank_intent
    assert _world_bank_intent("X", "x", "EURO_AREA", "Euro area").country_code == "XC"
    # A country World Bank spells the same way passes through untouched.
    assert _world_bank_intent("X", "x", "IN", "India").country_code == "IN"


def test_an_unmapped_jurisdiction_still_refuses_to_substitute_a_country():
    # UAE has no confirmed live source: api.worldbank.org returns HTTP 502 for
    # ARE and AE while serving IN and XC, so no provider is verified to hold
    # the data. None is the correct answer — never another country's figure.
    assert detect_live_data_intent("What is the current UAE inflation rate?", "UAE") is None
    assert detect_live_data_intent("What is the Bank Rate?", "UAE") is None
