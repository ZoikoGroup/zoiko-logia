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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.live_sources import cache
from app.domains.live_sources.classifier import detect_live_data_intent
from app.domains.live_sources.connectors.world_bank import WorldBankConnector
from app.domains.live_sources.schemas import LiveFetchOutcome, NormalizedResponse
from app.orchestration.schemas import SourceSummary

settings = get_settings()

_CONNECTORS = {
    "world_bank": WorldBankConnector(base_url=settings.WORLD_BANK_API_BASE_URL),
}


async def fetch_live_data(db: AsyncSession, *, query: str, tenant_id: str) -> LiveFetchOutcome:
    intent = detect_live_data_intent(query)
    if intent is None:
        return LiveFetchOutcome(intent=None)

    cache_key = cache.make_cache_key(intent)
    cached = await cache.get_cached(db, cache_key)
    if cached is not None:
        return LiveFetchOutcome(intent=intent, cache_hit=True, succeeded=True, normalized=cached)

    connector = _CONNECTORS.get(intent.provider_key)
    if connector is None:
        return LiveFetchOutcome(intent=intent, cache_hit=False, succeeded=False, error=f"no connector for {intent.provider_key}")

    try:
        normalized = await connector.fetch(intent, timeout=settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS)
        await cache.set_cached(
            db,
            cache_key=cache_key,
            provider_key=intent.provider_key,
            normalized=normalized,
            ttl_seconds=settings.LIVE_SOURCE_CACHE_TTL_SECONDS,
        )
        return LiveFetchOutcome(intent=intent, cache_hit=False, succeeded=True, normalized=normalized)
    except Exception as exc:
        return LiveFetchOutcome(intent=intent, cache_hit=False, succeeded=False, error=str(exc))


def make_live_source_id(normalized: NormalizedResponse) -> str:
    return f"live-{normalized.provider_key}-{normalized.indicator_code}-{normalized.country_code}"


def to_source_summary(normalized: NormalizedResponse) -> SourceSummary:
    return SourceSummary(
        id=make_live_source_id(normalized),
        title=normalized.citation_title,
        category="macro-economic-data",
        jurisdiction_scope=normalized.country_label,
        version_label=normalized.observation_period,
        status="ACTIVE",
        source_type="live_api",
    )


def to_synthetic_chunk(normalized: NormalizedResponse, summary: SourceSummary) -> dict:
    """Shape-matches the dict app.domains.rag.retrieval.retrieve_documents()
    returns for a real vector chunk, so it can ride through the existing
    reranked-chunk -> build_grounded_context() -> [REF-N] citation pipeline
    unmodified (app/domains/rag/context_fit.py expects chunk['text'] and
    chunk['metadata']['title'/'version'/'jurisdiction'/'file_path'])."""
    text = (
        f"{normalized.indicator_label} for {normalized.country_label} "
        f"({normalized.observation_period}): {normalized.value}"
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
