from datetime import datetime, timezone

import httpx
import pytest

from app.domains.live_sources.classifier import detect_live_data_intent
from app.domains.live_sources.connectors.ecb import ECBConnector
from app.domains.live_sources.connectors.imf import IMFConnector
from app.domains.live_sources.connectors.regulations_gov import RegulationsGovConnector
from app.domains.live_sources.connectors.vies import VIESConnector
from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent
from app.domains.live_sources.schemas import LiveDataIntent


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_ecb_connector_normalizes_latest_csv_observation():
    def handler(request):
        assert request.url.params["lastNObservations"] == "1"
        return httpx.Response(200, text="TIME_PERIOD,OBS_VALUE,UNIT\n2026-07-30,2.0,Percent per annum\n")
    intent = LiveDataIntent(provider_key="ecb", indicator_code="FM:D.U2.EUR.4F.KR.DFR.LEV",
                            indicator_label="ECB deposit facility rate", country_code="EURO_AREA", country_label="Euro area")
    async with _client(handler) as client:
        result = await ECBConnector("https://example.test/service").fetch(intent, timeout=1, client=client)
    assert result.value == 2.0
    assert result.observation_period == "2026-07-30"


@pytest.mark.asyncio
async def test_imf_connector_requests_only_current_year():
    year = str(datetime.now(timezone.utc).year)
    def handler(request):
        assert request.url.params["periods"] == year
        return httpx.Response(200, json={"values": {"NGDP_RPCH": {"IND": {year: 6.5, "2031": 7.1}}}})
    intent = LiveDataIntent(provider_key="imf", indicator_code="NGDP_RPCH:IND",
                            indicator_label="Real GDP growth", country_code="IN", country_label="India")
    async with _client(handler) as client:
        result = await IMFConnector("https://example.test/api/v2").fetch(intent, timeout=1, client=client)
    assert result.value == 6.5
    assert result.observation_period == year


@pytest.mark.asyncio
async def test_vies_connector_preserves_explicit_invalid_result():
    def handler(request):
        return httpx.Response(200, json={"valid": False, "requestDate": "2026-07-31"})
    intent = LiveDataIntent(provider_key="vies", indicator_code="vat_validation",
                            indicator_label="EU VAT validation", country_code="DE", country_label="Germany",
                            company_query="DE123456789")
    async with _client(handler) as client:
        result = await VIESConnector("https://example.test/rest-api").fetch(intent, timeout=1, client=client)
    assert result.value == "Invalid"


@pytest.mark.asyncio
async def test_regulations_gov_returns_direct_official_record_urls():
    def handler(request):
        assert request.url.params["api_key"] == "test-key"
        return httpx.Response(200, json={"data": [{"id": "IRS-2026-0001-0001", "type": "documents", "attributes": {
            "title": "Example proposed tax rule", "documentType": "Proposed Rule", "postedDate": "2026-07-01",
            "agencyId": "IRS", "docketId": "IRS-2026-0001"}}]})
    intent = EvidenceSearchIntent(provider_key="regulations_gov", query="tax reporting")
    async with _client(handler) as client:
        result = await RegulationsGovConnector("https://example.test/v4", "test-key").search(intent, timeout=1, client=client)
    assert len(result.records) == 1
    assert str(result.records[0].source_url) == "https://www.regulations.gov/document/IRS-2026-0001-0001"


def test_phase1_queries_route_deterministically():
    assert detect_live_data_intent("What is the ECB deposit facility rate?").provider_key == "ecb"
    assert detect_live_data_intent("Show the IMF GDP growth forecast for India").provider_key == "imf"
    assert detect_live_data_intent("Validate VAT number DE123456789 using VIES", jurisdiction="EU").provider_key == "vies"
    assert detect_live_data_intent("Find the latest proposed rule about tax reporting").provider_key == "regulations_gov"
