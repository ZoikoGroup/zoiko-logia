"""Reliability boundary for official evidence-search APIs."""
from __future__ import annotations

from app.core.config import get_settings
from app.domains.live_sources.connectors.evidence_base import EvidenceSearchConnector
from app.domains.live_sources.connectors.regulations_gov import RegulationsGovConnector
from app.domains.live_sources.connectors.cellar import CellarConnector
from app.domains.live_sources.connectors.legislation_gov_uk import LegislationGovUKConnector
from app.domains.live_sources.connectors.ted import TEDConnector
from app.domains.live_sources.connectors.sam_gov import SAMGovConnector
from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent, EvidenceSearchResponse
from app.domains.live_sources.http_client import get_shared_http_client
from app.domains.live_sources.retry import call_with_retries

settings = get_settings()

_EVIDENCE_CONNECTORS: dict[str, EvidenceSearchConnector] = {
    "regulations_gov": RegulationsGovConnector(
        settings.REGULATIONS_GOV_API_BASE_URL, settings.REGULATIONS_GOV_API_KEY,
    ),
    "cellar": CellarConnector(settings.CELLAR_SPARQL_URL),
    "legislation_gov_uk": LegislationGovUKConnector(settings.LEGISLATION_GOV_UK_BASE_URL),
    "ted": TEDConnector(settings.TED_API_BASE_URL),
    "sam_gov": SAMGovConnector(settings.SAM_GOV_OPPORTUNITIES_URL, settings.SAM_GOV_API_KEY),
}


def available_providers() -> tuple[str, ...]:
    return tuple(_EVIDENCE_CONNECTORS)


async def search_authoritative_evidence(intent: EvidenceSearchIntent) -> EvidenceSearchResponse:
    """Multi-record search against one official evidence API.

    Distinct from live_sources.service.fetch_live_data(), which answers a
    question with a single figure or the single newest record. This returns
    the full result set, which is what a user reviewing "every current
    rulemaking on X" actually needs — an answer path that keeps only
    records[0] cannot express that.
    """
    connector = _EVIDENCE_CONNECTORS.get(intent.provider_key)
    if connector is None:
        raise ValueError(f"No evidence-search connector for {intent.provider_key}")
    return await call_with_retries(
        lambda: connector.search(
            intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS,
            client=get_shared_http_client(),
        )
    )
