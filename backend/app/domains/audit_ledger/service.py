# Audit ledger domain business logic - see Kriton Audit Logging Evidence Ledger spec
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domains.audit_ledger import compensating_events as compensating_events_module
from app.domains.audit_ledger.chain_integrity import verify_chain
from app.domains.audit_ledger.models import AuditEvent, CompensatingEvent
from app.domains.audit_ledger.replay import build_replay_manifest
from app.domains.audit_ledger.schemas import CompensatingEventCreate
from app.domains.risk_safety.models import SafetyEvent


def _ledger_event_to_dict(e: AuditEvent) -> dict:
    return {
        "id": e.id,
        "event_name": e.event_name,
        "payload_schema_version": e.payload_schema_version,
        "event_time": e.event_time,
        "ingested_at": e.ingested_at,
        "emitting_service": e.emitting_service,
        "tenant_id": e.tenant_id,
        "actor_type": e.actor_type,
        "actor_id": e.actor_id,
        "subject_type": e.subject_type,
        "subject_id": e.subject_id,
        "correlation_id": e.correlation_id,
        "causation_id": e.causation_id,
        "payload": e.payload,
        "payload_hash": e.payload_hash,
        "previous_chain_hash": e.previous_chain_hash,
        "chain_hash": e.chain_hash,
        "classification": e.classification,
        "replay_relevance": e.replay_relevance,
        "validation_status": e.validation_status,
        "legal_hold_id": e.legal_hold_id,
        "archived": e.archived,
        "source": "audit_ledger",
    }


def _safety_event_to_dict(e: SafetyEvent) -> dict:
    # SafetyEvent predates the generic ledger and isn't chain-hashed or
    # tenant-scoped as a first-class column yet, so it's merged in read-only,
    # honestly labeled with source="risk_safety_ledger" and no chain_hash.
    payload = e.payload or {}
    return {
        "id": f"safety-{e.id}",
        "event_name": e.event_type,
        "payload_schema_version": e.payload_schema_version,
        "event_time": e.timestamp,
        "ingested_at": e.timestamp,
        "emitting_service": "risk_safety",
        "tenant_id": payload.get("tenant_id") or "GLOBAL_CONTROL",
        "actor_type": "system",
        "actor_id": payload.get("reviewer_id") or payload.get("user_id"),
        "subject_type": "query",
        "subject_id": e.query_id or "unknown",
        "correlation_id": e.query_id,
        "causation_id": None,
        "payload": payload,
        "payload_hash": None,
        "previous_chain_hash": None,
        "chain_hash": None,
        "classification": "INTERNAL",
        "replay_relevance": "REQUIRED",
        "validation_status": "ACCEPTED",
        "legal_hold_id": None,
        "archived": False,
        "source": "risk_safety_ledger",
    }


async def list_events(
    db: AsyncSession,
    sync_db: Session,
    *,
    event_name: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Unified, time-ordered view across the native ledger and risk_safety's
    existing event log — this is what "every governed action" means in
    practice until every domain writes to the same table."""
    query = select(AuditEvent).order_by(AuditEvent.ingested_at.desc()).limit(limit)
    if event_name:
        query = query.where(AuditEvent.event_name == event_name)
    if subject_type:
        query = query.where(AuditEvent.subject_type == subject_type)
    if subject_id:
        query = query.where(AuditEvent.subject_id == subject_id)
    if correlation_id:
        query = query.where(AuditEvent.correlation_id == correlation_id)
    if tenant_id:
        query = query.where(AuditEvent.tenant_id == tenant_id)
    result = await db.execute(query)
    merged = [_ledger_event_to_dict(e) for e in result.scalars().all()]

    if subject_type in (None, "query"):
        safety_query = sync_db.query(SafetyEvent)
        if event_name:
            safety_query = safety_query.filter(SafetyEvent.event_type == event_name)
        if subject_id:
            safety_query = safety_query.filter(SafetyEvent.query_id == subject_id)
        if correlation_id:
            safety_query = safety_query.filter(SafetyEvent.query_id == correlation_id)
        safety_query = safety_query.order_by(SafetyEvent.timestamp.desc()).limit(limit)
        merged += [_safety_event_to_dict(e) for e in safety_query.all()]

    merged.sort(key=lambda item: item["ingested_at"] or item["event_time"], reverse=True)
    return merged[:limit]


async def get_event(db: AsyncSession, event_id: str) -> Optional[AuditEvent]:
    return await db.get(AuditEvent, event_id)


async def list_compensating_events(
    db: AsyncSession, corrects_event_id: Optional[str] = None
) -> list[CompensatingEvent]:
    query = select(CompensatingEvent).order_by(CompensatingEvent.created_at.desc())
    if corrects_event_id:
        query = query.where(CompensatingEvent.corrects_event_id == corrects_event_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def issue_compensating_event(
    db: AsyncSession, event_id: str, issued_by: str, payload: CompensatingEventCreate
) -> CompensatingEvent:
    return await compensating_events_module.issue_compensating_event(
        db,
        corrects_event_id=event_id,
        correction_type=payload.correction_type,
        correction_reason=payload.correction_reason,
        issued_by=issued_by,
        approver_id=payload.approver_id,
        corrected_fields_summary=payload.corrected_fields_summary,
        is_material=payload.is_material,
        effective_for_replay=payload.effective_for_replay,
    )


async def verify_tenant_chain(db: AsyncSession, tenant_id: str) -> dict:
    result = await db.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.ingested_at.asc())
    )
    events = list(result.scalars().all())
    passed, broken_event_id = verify_chain(events)
    return {
        "tenant_id": tenant_id,
        "passed": passed,
        "events_checked": len(events),
        "first_broken_event_id": broken_event_id,
    }


async def get_replay_manifest(db: AsyncSession, sync_db: Session, correlation_id: str) -> dict:
    return await build_replay_manifest(db, sync_db, correlation_id)
