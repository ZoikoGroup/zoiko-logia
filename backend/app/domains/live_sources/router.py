"""
Official evidence-search REST API.

POST /api/v1/live-sources/evidence/search

Why this exists as its own endpoint rather than more Ask Kriton routing:
Ask Kriton answers a question and cites the single best record. An evidence
search answers "show me every current official record matching this", which
is a different task with a different output shape — a reviewer working
through open rulemakings or tenders needs the list, not the top hit. Before
this endpoint, EvidenceSearchConnector could return up to 25 records and the
only caller (connectors/evidence_live.py) discarded all but the first.

Governance is not bypassed here. The provider must have an ACTIVE, licence-
permitted LiveSourceProvider row, checked against the same registry table
and the same tenant-privacy rule the licence gate applies to a live source
used in an answer.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.live_sources import evidence_service
from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent, EvidenceSearchResponse
from app.domains.live_sources.models import LiveSourceProvider

router = APIRouter(prefix="/live-sources", tags=["Authoritative Live Sources"])
settings = get_settings()


class ProviderHealth(BaseModel):
    provider_key: str
    display_name: str
    status: str
    integration_type: str
    jurisdiction: str
    authority_rank: int
    last_successful_sync: datetime | None = None
    last_content_hash: str | None = None
    freshness_sla_seconds: int | None = None
    age_seconds: int | None = None
    # unknown = never contacted, fresh = inside its SLA, stale = past it,
    # unmonitored = no SLA declared. Kept as a derived field so a caller
    # never has to re-implement the comparison and get it subtly wrong.
    freshness: str


def _to_health(row: LiveSourceProvider, now: datetime) -> ProviderHealth:
    age = None
    if row.last_successful_sync is not None:
        last = row.last_successful_sync
        # SQLite hands back naive datetimes; treat them as UTC rather than
        # letting the subtraction raise.
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = int((now - last).total_seconds())

    if age is None:
        freshness = "unknown"
    elif not row.freshness_sla_seconds:
        freshness = "unmonitored"
    elif age > row.freshness_sla_seconds:
        freshness = "stale"
    else:
        freshness = "fresh"

    return ProviderHealth(
        provider_key=row.provider_key, display_name=row.display_name, status=row.status,
        integration_type=row.integration_type, jurisdiction=row.jurisdiction,
        authority_rank=row.authority_rank, last_successful_sync=row.last_successful_sync,
        last_content_hash=row.last_content_hash, freshness_sla_seconds=row.freshness_sla_seconds,
        age_seconds=age, freshness=freshness,
    )


async def _assert_provider_permitted(db: AsyncSession, provider_key: str, tenant_id: str) -> LiveSourceProvider:
    result = await db.execute(
        select(LiveSourceProvider).where(LiveSourceProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        # Deliberately not 404-with-detail on an unseeded provider vs an
        # unknown one: both mean "this deployment cannot serve that source",
        # and distinguishing them leaks the registry's contents.
        raise HTTPException(status_code=404, detail=f"No active official source '{provider_key}'")
    if provider.status != "ACTIVE":
        raise HTTPException(status_code=409, detail=f"Official source '{provider_key}' is disabled")
    if provider.licence_state == "restricted":
        raise HTTPException(status_code=403, detail=f"Official source '{provider_key}' is licence-restricted")
    if provider.is_tenant_private and provider.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"No active official source '{provider_key}'")
    return provider


@router.get("/health", response_model=list[ProviderHealth])
async def provider_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProviderHealth]:
    """Freshness of every registered official source.

    Authenticated deliberately: last-sync times, content hashes and the
    registry's contents are operational detail, not public information.

    This answers the question Kriton could not answer before — "is that
    source actually current?" — which matters because the answer path is
    built to hide the alternative. A failed live fetch never raises, falls
    back to a stale cache entry, and is audited as an ordinary cache hit
    (see live_sources/service.py), so a source dead for six weeks looks from
    the inside like a well-cached one.
    """
    result = await db.execute(select(LiveSourceProvider).order_by(LiveSourceProvider.provider_key))
    now = datetime.now(timezone.utc)
    return [_to_health(row, now) for row in result.scalars().all()]


@router.get("/evidence/providers", response_model=list[str])
async def list_evidence_providers() -> list[str]:
    """Provider keys this deployment can search. Availability still depends
    on the registry row and, for Regulations.gov and SAM.gov, on a key."""
    return list(evidence_service.available_providers())


@router.post("/evidence/search", response_model=EvidenceSearchResponse)
@limiter.limit("20/minute")
async def search_evidence(
    request: Request,
    payload: EvidenceSearchIntent,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceSearchResponse:
    if payload.provider_key not in evidence_service.available_providers():
        raise HTTPException(status_code=404, detail=f"No evidence-search connector for '{payload.provider_key}'")
    await _assert_provider_permitted(db, payload.provider_key, current_user.tenant_id)
    try:
        return await evidence_service.search_authoritative_evidence(payload)
    except ValueError as exc:
        # Connector-level refusals — an unconfigured API key, an upstream
        # that returned nothing usable. These are the operator's problem to
        # fix and safe to state; they carry no credential material (see
        # connectors/sam_gov.py, which strips the key from its own errors).
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        # Anything else is an upstream fault. The message can contain a full
        # request URL, so it is logged by the handler, never returned.
        raise HTTPException(
            status_code=502,
            detail=f"Official source '{payload.provider_key}' could not be reached",
        ) from exc
