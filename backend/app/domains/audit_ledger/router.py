"""
Audit Ledger REST API — FastAPI router.

Endpoints:
  GET  /audit/events                       — search the append-only event ledger
  GET  /audit/events/{event_id}             — fetch a single native ledger event
  GET  /audit/replay/{correlation_id}       — build a replay manifest
  GET  /audit/chain-verify                  — verify the caller's tenant hash chain
  GET  /audit/compensating-events           — list corrections
  POST /audit/events/{event_id}/compensate  — issue a governed correction
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.domains.audit_ledger import service as audit_service
from app.domains.audit_ledger.compensating_events import CompensatingEventError
from app.domains.audit_ledger.schemas import (
    AuditEventPublic,
    ChainVerifyResult,
    CompensatingEventCreate,
    CompensatingEventPublic,
    ReplayManifest,
)
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user, require_admin

router = APIRouter(prefix="/audit", tags=["audit_ledger"])


@router.get("/events", response_model=list[AuditEventPublic])
async def get_events(
    event_name: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    sync_db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
) -> list[AuditEventPublic]:
    events = await audit_service.list_events(
        db,
        sync_db,
        event_name=event_name,
        subject_type=subject_type,
        subject_id=subject_id,
        correlation_id=correlation_id,
        tenant_id=current_user.tenant_id,
        limit=limit,
    )
    return [AuditEventPublic.model_validate(e) for e in events]


@router.get("/events/{event_id}", response_model=AuditEventPublic)
async def get_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuditEventPublic:
    event = await audit_service.get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")
    return AuditEventPublic.model_validate({**event.__dict__, "source": "audit_ledger"})


@router.get("/replay/{correlation_id}", response_model=ReplayManifest)
async def get_replay_manifest(
    correlation_id: str,
    db: AsyncSession = Depends(get_db),
    sync_db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
) -> ReplayManifest:
    manifest = await audit_service.get_replay_manifest(db, sync_db, correlation_id)
    return ReplayManifest.model_validate(manifest)


@router.get("/chain-verify", response_model=ChainVerifyResult)
async def get_chain_verify(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChainVerifyResult:
    result = await audit_service.verify_tenant_chain(db, current_user.tenant_id)
    return ChainVerifyResult.model_validate(result)


@router.get("/compensating-events", response_model=list[CompensatingEventPublic])
async def get_compensating_events(
    corrects_event_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CompensatingEventPublic]:
    rows = await audit_service.list_compensating_events(db, corrects_event_id)
    return [CompensatingEventPublic.model_validate(r) for r in rows]


@router.post("/events/{event_id}/compensate", response_model=CompensatingEventPublic)
async def post_compensate_event(
    event_id: str,
    payload: CompensatingEventCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> CompensatingEventPublic:
    try:
        row = await audit_service.issue_compensating_event(db, event_id, admin.id, payload)
    except CompensatingEventError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return CompensatingEventPublic.model_validate(row)
