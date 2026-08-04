import httpx
import pytest
from datetime import datetime
from urllib.parse import parse_qs

from app.domains.live_sources.classifier import detect_live_data_intent
from app.domains.live_sources.connectors.cellar import CellarConnector
from app.domains.live_sources.connectors.legislation_gov_uk import LegislationGovUKConnector
from app.domains.live_sources.connectors.sam_gov import SAMGovConnector
from app.domains.live_sources.connectors.sanctions_feeds import CSVSanctionsFeedConnector, OFACFeedConnector, UNSanctionsFeedConnector
from app.domains.live_sources.connectors.ted import TEDConnector
from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent
from app.domains.risk_safety.risk_classifier import classify, pre_screen


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.mark.asyncio
async def test_cellar_returns_direct_celex_url_and_escaped_query():
    def handler(request):
        assert '\\"' in parse_qs(request.content.decode())["query"][0]
        return httpx.Response(200, json={"results": {"bindings": [{
            "work": {"value": "http://publications.europa.eu/resource/cellar/abc"},
            "celex": {"value": "32024R1689"}, "title": {"value": "Artificial Intelligence Act"},
            "date": {"value": "2024-07-12"},
        }]}})
    async with _client(handler) as client:
        result = await CellarConnector("https://example.test/sparql").search(
            EvidenceSearchIntent(provider_key="cellar", query='AI "Act"'), timeout=1, client=client)
    assert result.records[0].record_id == "32024R1689"
    assert "CELEX:32024R1689" in str(result.records[0].source_url)


@pytest.mark.asyncio
async def test_legislation_gov_uk_parses_atom_feed():
    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://www.legislation.gov.uk/ukpga/2026/1</id>
    <title>Example Act 2026</title><updated>2026-01-02T00:00:00Z</updated>
    <link rel="alternate" href="https://www.legislation.gov.uk/ukpga/2026/1"/><summary>Official act</summary></entry></feed>'''
    async with _client(lambda request: httpx.Response(200, content=atom)) as client:
        result = await LegislationGovUKConnector("https://example.test").search(
            EvidenceSearchIntent(provider_key="legislation_gov_uk", query="Example Act"), timeout=1, client=client)
    assert result.records[0].title == "Example Act 2026"


@pytest.mark.asyncio
async def test_ted_v3_posts_bounded_expert_search():
    def handler(request):
        assert request.method == "POST"
        return httpx.Response(200, json={"notices": [{"notice-id": "123-2026", "notice-title": "Audit services",
            "publication-date": "2026-07-01", "links": {"html": ["https://ted.europa.eu/en/notice/-/detail/123-2026"]}}]})
    async with _client(handler) as client:
        result = await TEDConnector("https://example.test/v3").search(
            EvidenceSearchIntent(provider_key="ted", query="audit services"), timeout=1, client=client)
    assert result.records[0].record_id == "123-2026"


@pytest.mark.asyncio
async def test_sam_gov_requires_key_and_date_bounds():
    with pytest.raises(ValueError, match="SAM_GOV_API_KEY"):
        await SAMGovConnector("https://example.test/search", "").search(
            EvidenceSearchIntent(provider_key="sam_gov", query="audit"), timeout=1)
    def handler(request):
        posted_from = datetime.strptime(request.url.params["postedFrom"], "%m/%d/%Y").date()
        posted_to = datetime.strptime(request.url.params["postedTo"], "%m/%d/%Y").date()
        assert (posted_to - posted_from).days == 364
        return httpx.Response(200, json={"opportunitiesData": [{"noticeId": "n1", "title": "Audit support",
            "type": "Solicitation", "postedDate": "2026-07-01", "uiLink": "https://sam.gov/opp/n1/view"}]})
    async with _client(handler) as client:
        result = await SAMGovConnector("https://example.test/search", "key").search(
            EvidenceSearchIntent(provider_key="sam_gov", query="audit"), timeout=1, client=client)
    assert result.records[0].record_id == "n1"


@pytest.mark.asyncio
async def test_sam_gov_http_error_does_not_expose_api_key():
    async with _client(lambda request: httpx.Response(400, text="bad request")) as client:
        with pytest.raises(RuntimeError, match=r"SAM.gov API request failed with HTTP 400") as error:
            await SAMGovConnector("https://example.test/search", "secret-key").search(
                EvidenceSearchIntent(provider_key="sam_gov", query="audit"), timeout=1, client=client)
    assert "secret-key" not in str(error.value)


@pytest.mark.asyncio
async def test_ofac_parser_preserves_aliases_programs_and_hash():
    xml = b'''<sdnList><sdnEntry><uid>36</uid><firstName>ALPHA</firstName><lastName>ENTITY</lastName><sdnType>Entity</sdnType>
    <programList><program>TEST</program></programList><akaList><aka><firstName>A</firstName><lastName>ENTITY</lastName></aka></akaList></sdnEntry></sdnList>'''
    async with _client(lambda request: httpx.Response(200, content=xml)) as client:
        result = await OFACFeedConnector("https://example.test/sdn.xml").fetch_snapshot(timeout=1, max_bytes=10000, client=client)
    assert result.entries[0].aliases == ("A ENTITY",)
    assert result.entries[0].programs == ("TEST",)
    assert len(result.content_sha256) == 64


@pytest.mark.asyncio
async def test_un_parser_handles_individual_and_entity():
    xml = b'''<CONSOLIDATED_LIST><INDIVIDUAL><DATAID>1</DATAID><FIRST_NAME>Jane</FIRST_NAME><SECOND_NAME>Doe</SECOND_NAME>
    <UN_LIST_TYPE>Test</UN_LIST_TYPE><LISTED_ON>2026-01-01</LISTED_ON><INDIVIDUAL_ALIAS><ALIAS_NAME>J Doe</ALIAS_NAME></INDIVIDUAL_ALIAS></INDIVIDUAL>
    <ENTITY><DATAID>2</DATAID><FIRST_NAME>Example Ltd</FIRST_NAME></ENTITY></CONSOLIDATED_LIST>'''
    async with _client(lambda request: httpx.Response(200, content=xml)) as client:
        result = await UNSanctionsFeedConnector("https://example.test/un.xml").fetch_snapshot(timeout=1, max_bytes=10000, client=client)
    assert [entry.primary_name for entry in result.entries] == ["Jane Doe", "Example Ltd"]


@pytest.mark.asyncio
async def test_csv_parser_groups_alias_rows_by_unique_id():
    csv_body = b"Unique ID,Name 1,Name 2,Regime Name,Individual Entity Ship\nU1,Alpha,Ltd,Test,Entity\nU1,A,Limited,Test,Entity\n"
    connector = CSVSanctionsFeedConnector("uk_sanctions", "https://example.test/list.csv",
                                           "https://example.test/landing", "GB")
    async with _client(lambda request: httpx.Response(200, content=csv_body)) as client:
        result = await connector.fetch_snapshot(timeout=1, max_bytes=10000, client=client)
    assert len(result.entries) == 1
    assert result.entries[0].aliases == ("A Limited",)


def test_phase2_and_phase3_query_routing():
    cases = {
        "Find EU legislation about Artificial Intelligence Act": "cellar",
        "Search legislation.gov.uk for Companies Act": "legislation_gov_uk",
        "Find EU tender about audit services": "ted",
        "Search SAM.gov for accounting support": "sam_gov",
        'Screen "ALPHA ENTITY" against OFAC': "ofac",
        'Check "Jane Doe" against UN sanctions': "un_sanctions",
        'Screen "Example Ltd" against UK sanctions': "uk_sanctions",
        'Check "Example SA" against EU sanctions': "eu_sanctions",
    }
    for query, provider in cases.items():
        intent = detect_live_data_intent(query)
        assert intent is not None and intent.provider_key == provider, query


def test_sanctions_screening_retrieves_then_requires_human_review():
    query = 'Screen "ALPHA ENTITY" against OFAC'
    assert pre_screen(query) is None
    decision = classify(query)
    assert decision is not None
    assert decision["risk_level"] == "HIGH"
    assert decision["route"] == "HUMAN_REVIEW"
    assert decision["requires_human_review"] is True
