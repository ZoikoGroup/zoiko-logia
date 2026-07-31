"""
Live/dynamic external data source — orchestration entry point. This is the
ONLY module callers outside app/domains/live_sources should import from;
callers never call a connector or the cache directly (mirrors how
orchestration/service.py never queries source_library tables directly,
always through source_library.service).

fetch_live_data() never raises to its caller — a failed/absent live fetch
must degrade silently, leaving the existing static-document answer path
completely unaffected (this is a peer retrieval method, not a replacement,
and per-request availability of one external API must not be able to break
answers that don't need it).
"""
from __future__ import annotations

import asyncio

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.live_sources import cache
from app.domains.live_sources.classifier import (
    build_company_lookup_intent_from_name,
    company_lookup_needs_llm_fallback,
    detect_company_lookup_intent,
    detect_live_data_intent,
    live_data_needs_llm_fallback,
    resolve_live_data_intent_from_llm_guess,
)
from app.domains.live_sources.llm_fallback import extract_company_name_via_llm, extract_live_data_intent_via_llm
from app.domains.live_sources.connectors.bank_of_england import BankOfEnglandConnector
from app.domains.live_sources.connectors.companies_house import CompaniesHouseConnector
from app.domains.live_sources.connectors.fred import FREDConnector
from app.domains.live_sources.connectors.frankfurter import FrankfurterConnector
from app.domains.live_sources.connectors.gleif import GLEIFConnector
from app.domains.live_sources.connectors.oecd import OECDConnector
from app.domains.live_sources.connectors.ons import ONSConnector
from app.domains.live_sources.connectors.sec_edgar import SECEdgarConnector
from app.domains.live_sources.connectors.world_bank import WorldBankConnector
from app.domains.live_sources.connectors.ecb import ECBConnector
from app.domains.live_sources.connectors.imf import IMFConnector
from app.domains.live_sources.connectors.vies import VIESConnector
from app.domains.live_sources.connectors.regulations_gov import RegulationsGovLiveConnector
from app.domains.live_sources.connectors.evidence_live import EvidenceLiveConnector
from app.domains.live_sources.connectors.cellar import CellarConnector
from app.domains.live_sources.connectors.legislation_gov_uk import LegislationGovUKConnector
from app.domains.live_sources.connectors.ted import TEDConnector
from app.domains.live_sources.connectors.sam_gov import SAMGovConnector
from app.domains.live_sources.connectors.sanctions_live import SanctionsLiveConnector
from app.domains.live_sources.schemas import LiveFetchOutcome, NormalizedResponse
from app.orchestration.schemas import SourceSummary

settings = get_settings()

_PROVIDER_CATEGORIES = {
    "vies": "tax-compliance",
    "regulations_gov": "us-regulations",
    "cellar": "eu-legislation",
    "legislation_gov_uk": "uk-legislation",
    "ted": "public-procurement",
    "sam_gov": "public-procurement",
    "ofac": "financial-crime",
    "un_sanctions": "financial-crime",
    "uk_sanctions": "financial-crime",
    "eu_sanctions": "financial-crime",
    "sec_edgar": "company-financials",
    "companies_house": "company-financials",
    "gleif": "company-financials",
    "frankfurter": "fx-rates",
}

_CONNECTORS = {
    "world_bank": WorldBankConnector(base_url=settings.WORLD_BANK_API_BASE_URL),
    "ons": ONSConnector(base_url=settings.ONS_API_BASE_URL),
    "bank_of_england": BankOfEnglandConnector(base_url=settings.BANK_OF_ENGLAND_API_BASE_URL),
    "frankfurter": FrankfurterConnector(base_url=settings.FRANKFURTER_API_BASE_URL),
    "fred": FREDConnector(base_url=settings.FRED_API_BASE_URL, api_key=settings.FRED_API_KEY),
    "sec_edgar": SECEdgarConnector(base_url=settings.SEC_EDGAR_API_BASE_URL, user_agent=settings.SEC_EDGAR_USER_AGENT),
    "companies_house": CompaniesHouseConnector(
        base_url=settings.COMPANIES_HOUSE_API_BASE_URL, api_key=settings.COMPANIES_HOUSE_API_KEY
    ),
    "oecd": OECDConnector(base_url=settings.OECD_API_BASE_URL),
    "gleif": GLEIFConnector(base_url=settings.GLEIF_API_BASE_URL),
    "ecb": ECBConnector(base_url=settings.ECB_API_BASE_URL),
    "imf": IMFConnector(base_url=settings.IMF_API_BASE_URL),
    "vies": VIESConnector(base_url=settings.VIES_API_BASE_URL),
    "regulations_gov": RegulationsGovLiveConnector(
        base_url=settings.REGULATIONS_GOV_API_BASE_URL, api_key=settings.REGULATIONS_GOV_API_KEY,
    ),
    "cellar": EvidenceLiveConnector("cellar", CellarConnector(settings.CELLAR_SPARQL_URL)),
    "legislation_gov_uk": EvidenceLiveConnector(
        "legislation_gov_uk", LegislationGovUKConnector(settings.LEGISLATION_GOV_UK_BASE_URL),
    ),
    "ted": EvidenceLiveConnector("ted", TEDConnector(settings.TED_API_BASE_URL)),
    "sam_gov": EvidenceLiveConnector(
        "sam_gov", SAMGovConnector(settings.SAM_GOV_OPPORTUNITIES_URL, settings.SAM_GOV_API_KEY),
    ),
    "ofac": SanctionsLiveConnector("ofac", "OFAC SDN List", "https://ofac.treasury.gov/sanctions-list-service"),
    "un_sanctions": SanctionsLiveConnector(
        "un_sanctions", "UN Security Council Consolidated List",
        "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list",
    ),
    "uk_sanctions": SanctionsLiveConnector(
        "uk_sanctions", "UK Sanctions List", "https://www.gov.uk/government/publications/the-uk-sanctions-list",
    ),
    "eu_sanctions": SanctionsLiveConnector(
        "eu_sanctions", "EU Consolidated Financial Sanctions List",
        "https://finance.ec.europa.eu/eu-and-world/sanctions-restrictive-measures_en",
    ),
}


from app.domains.live_sources.http_client import get_shared_http_client


async def fetch_live_data(db: AsyncSession, *, query: str, tenant_id: str, jurisdiction: str = "") -> LiveFetchOutcome:
    # Tier 0/1: keyword + semantic exemplar matching (classifier.py) —
    # handles the large majority of queries at near-zero latency and cost.
    intent = detect_live_data_intent(query, jurisdiction=jurisdiction)

    # Tier 2: LLM-reasoning fallback, only reached when Tier 0/1 either
    # found nothing at all, or found a real indicator but silently
    # defaulted the country to "World" (see
    # classifier.py's live_data_needs_llm_fallback() for the exact two
    # cases). Tier 3 validation happens inside
    # resolve_live_data_intent_from_llm_guess() — the LLM's guess is never
    # routed to directly, so a failed/malformed call or an unsupported
    # country/indicator just leaves `intent` exactly as Tier 0/1 left it,
    # never worse.
    if live_data_needs_llm_fallback(query, jurisdiction, existing_intent=intent):
        llm_result = await extract_live_data_intent_via_llm(query)
        corrected = resolve_live_data_intent_from_llm_guess(llm_result, jurisdiction, existing_intent=intent)
        if corrected is not None:
            intent = corrected

    # Company lookup ("tell me about company X") is a different question
    # than country+indicator — tried third, only if the above finds
    # nothing, never both (see classifier.py's detect_company_lookup_intent
    # docstring for why this stays a separate function).
    if intent is None:
        intent = detect_company_lookup_intent(query, jurisdiction=jurisdiction)
    if intent is None and company_lookup_needs_llm_fallback(query, jurisdiction=jurisdiction):
        # Tier 2: the regex name-extraction pattern requires a specific
        # trailing anchor ("X's filings", "revenue of X") and misses
        # verb-based phrasing ("what did Apple make last quarter"). Only
        # reached when Tier 1 already confirmed this is worth the round
        # trip (see classifier.py's company_lookup_needs_llm_fallback) —
        # extract_company_name_via_llm() never raises, degrades to None on
        # any failure, same as every other unmatched case here.
        llm_name = await extract_company_name_via_llm(query)
        if llm_name is not None:
            intent = build_company_lookup_intent_from_name(llm_name, jurisdiction, query=query)
    if intent is None:
        return LiveFetchOutcome(intent=None)

    cache_key = cache.make_cache_key(intent)
    try:
        cached = await cache.get_cached(db, cache_key)
    except Exception:
        # Cache availability must never decide whether authoritative data
        # can be fetched or whether the enclosing Ask request survives.
        cached = None
    if cached is not None:
        return LiveFetchOutcome(intent=intent, cache_hit=True, succeeded=True, normalized=cached)

    connector = _CONNECTORS.get(intent.provider_key)
    if connector is None:
        return LiveFetchOutcome(intent=intent, cache_hit=False, succeeded=False, error=f"no connector for {intent.provider_key}")

    last_error: Exception | None = None
    attempts = max(1, settings.LIVE_SOURCE_MAX_ATTEMPTS)
    for attempt in range(attempts):
        try:
            shared_client = get_shared_http_client()
            normalized = await connector.fetch(
                intent,
                timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS,
                client=shared_client,
            )
            try:
                await cache.set_cached(
                    db,
                    cache_key=cache_key,
                    provider_key=intent.provider_key,
                    normalized=normalized,
                    ttl_seconds=settings.LIVE_SOURCE_CACHE_TTL_SECONDS,
                )
            except Exception:
                await db.rollback()
            return LiveFetchOutcome(intent=intent, cache_hit=False, succeeded=True, normalized=normalized)
        except Exception as exc:
            last_error = exc
            retryable = isinstance(exc, httpx.TransportError) or (
                isinstance(exc, httpx.HTTPStatusError)
                and (exc.response.status_code == 429 or exc.response.status_code >= 500)
            )
            if not retryable or attempt + 1 >= attempts:
                break
            delay = settings.LIVE_SOURCE_RETRY_BACKOFF_SECONDS * (attempt + 1)
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                retry_after = exc.response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    delay = min(float(retry_after), 5.0)
            await asyncio.sleep(delay)

    try:
        stale = await cache.get_cached(db, cache_key, ignore_ttl=True)
    except Exception:
        stale = None
    if stale is not None:
        return LiveFetchOutcome(intent=intent, cache_hit=True, succeeded=True, normalized=stale)
    return LiveFetchOutcome(
        intent=intent,
        cache_hit=False,
        succeeded=False,
        error=str(last_error) if last_error is not None else "live source fetch failed",
    )


def make_live_source_id(normalized: NormalizedResponse) -> str:
    base = f"live-{normalized.provider_key}-{normalized.indicator_code}-{normalized.country_code}"
    # Company-lookup results (SEC EDGAR/Companies House) need the company
    # in the id too — otherwise two different companies' identical
    # indicator_code (e.g. both "Assets") would collide onto the same
    # source_id. license_gate.py's _live_provider_key_of() only ever reads
    # the second dash-separated segment, so appending more segments here
    # is always safe regardless of what a company name itself contains.
    if normalized.company_query:
        return f"{base}-{normalized.company_query}"
    return base


def to_source_summary(normalized: NormalizedResponse) -> SourceSummary:
    return SourceSummary(
        id=make_live_source_id(normalized),
        title=normalized.citation_title,
        category=_PROVIDER_CATEGORIES.get(normalized.provider_key, "macro-economic-data"),
        jurisdiction_scope=normalized.country_label,
        version_label=normalized.observation_period,
        status="ACTIVE",
        source_type="live_api",
    )


def _format_value(value) -> str:
    """Human-readable rendering of a raw connector value before it ever
    enters the model's context — confirmed real failure: World Bank's
    GDP-in-current-US$ value (a Python float like 3956067115771.6304)
    landed in context completely unformatted, and the model — correctly
    following the "cite figures from context, never invent your own" rule
    — dutifully quoted it verbatim as "$3,956,067,115,771.63" in the final
    answer. Fixing the model's phrasing alone can't solve this: the
    instruction not to alter retrieved figures is exactly what makes
    fixing the number AT THE SOURCE the right layer, not the prompt layer.

    World Bank sets unit="" for every indicator (confirmed: grep across
    every connector), so unit can't be used to distinguish "this is a
    percentage" from "this is a dollar figure" — scale is the only signal
    that generalizes across all 9 connectors without per-indicator special
    cases. Values under 1000 (every percentage/rate/index this system
    handles) just get capped to 2 decimal places; anything bigger gets a
    human-scale suffix instead of raw digits."""
    if not isinstance(value, (int, float)):
        return str(value)
    abs_value = abs(value)
    if abs_value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:,.2f} trillion"
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:,.2f} billion"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:,.2f} million"
    if abs_value >= 1000:
        return f"{value:,.2f}"
    return f"{value:.2f}"


def to_synthetic_chunk(normalized: NormalizedResponse, summary: SourceSummary) -> dict:
    """Shape-matches the dict app.domains.rag.retrieval.retrieve_documents()
    returns for a real vector chunk, so it can ride through the existing
    reranked-chunk -> build_grounded_context() -> [REF-N] citation pipeline
    unmodified (app/domains/rag/context_fit.py expects chunk['text'] and
    chunk['metadata']['title'/'version'/'jurisdiction'/'file_path'])."""
    text = (
        f"{normalized.indicator_label} for {normalized.country_label} "
        f"({normalized.observation_period}): {_format_value(normalized.value)}"
        + (f" {normalized.unit}" if normalized.unit else "")
    )
    return {
        "text": text,
        "node_id": summary.id,
        "metadata": {
            "title": normalized.citation_title,
            "version": normalized.observation_period,
            "jurisdiction": normalized.country_label,
            "file_path": normalized.source_url,
            "source_id": summary.id,
            "source_type": "live_api",
        },
    }
