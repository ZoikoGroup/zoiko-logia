"""Reliability boundary for official evidence-search APIs."""
from __future__ import annotations

import asyncio

import httpx

from app.core.config import get_settings
from app.domains.live_sources.connectors.evidence_base import EvidenceSearchConnector
from app.domains.live_sources.connectors.regulations_gov import RegulationsGovConnector
from app.domains.live_sources.connectors.cellar import CellarConnector
from app.domains.live_sources.connectors.legislation_gov_uk import LegislationGovUKConnector
from app.domains.live_sources.connectors.ted import TEDConnector
from app.domains.live_sources.connectors.sam_gov import SAMGovConnector
from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent, EvidenceSearchResponse
from app.domains.live_sources.http_client import get_shared_http_client

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


async def search_authoritative_evidence(intent: EvidenceSearchIntent) -> EvidenceSearchResponse:
    connector = _EVIDENCE_CONNECTORS.get(intent.provider_key)
    if connector is None:
        raise ValueError(f"No evidence-search connector for {intent.provider_key}")
    last_error: Exception | None = None
    for attempt in range(max(1, settings.LIVE_SOURCE_MAX_ATTEMPTS)):
        try:
            return await connector.search(
                intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS,
                client=get_shared_http_client(),
            )
        except Exception as exc:
            last_error = exc
            retryable = isinstance(exc, httpx.TransportError) or (
                isinstance(exc, httpx.HTTPStatusError)
                and (exc.response.status_code == 429 or exc.response.status_code >= 500)
            )
            if not retryable or attempt + 1 >= settings.LIVE_SOURCE_MAX_ATTEMPTS:
                break
            delay = settings.LIVE_SOURCE_RETRY_BACKOFF_SECONDS * (attempt + 1)
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                retry_after = exc.response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    delay = min(float(retry_after), 5.0)
            await asyncio.sleep(delay)
    assert last_error is not None
    raise last_error
