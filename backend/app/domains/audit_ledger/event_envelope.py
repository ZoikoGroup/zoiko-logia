"""
Canonical audit event envelope (Section 4).

Every domain that emits an audit event goes through record_event_async (for
domains on the async ORM session, e.g. source_library, model_gateway) or
record_event_sync (for domains on the sync session, e.g. risk_safety) so
every event is hashed and chained the same way regardless of caller.

Envelope rule: payload fields vary by event_name, but envelope fields do not.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domains.audit_ledger.chain_integrity import compute_chain_hash, compute_payload_hash
from app.domains.audit_ledger.models import AuditEvent, _event_id, _now


def _build_row(
    *,
    event_name: str,
    emitting_service: str,
    subject_type: str,
    subject_id: str,
    payload: dict,
    previous_chain_hash: Optional[str],
    tenant_id: str = "GLOBAL_CONTROL",
    actor_id: Optional[str] = None,
    actor_type: str = "user",
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
    classification: str = "INTERNAL",
    replay_relevance: str = "SUPPORTING",
) -> AuditEvent:
    event_id = _event_id()
    payload_hash = compute_payload_hash(payload)
    chain_hash = compute_chain_hash(event_id, event_name, payload_hash, previous_chain_hash)
    return AuditEvent(
        id=event_id,
        event_name=event_name,
        event_time=_now(),
        ingested_at=_now(),
        emitting_service=emitting_service,
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        subject_type=subject_type,
        subject_id=subject_id,
        correlation_id=correlation_id or subject_id,
        causation_id=causation_id,
        payload=payload,
        payload_hash=payload_hash,
        previous_chain_hash=previous_chain_hash,
        chain_hash=chain_hash,
        classification=classification,
        replay_relevance=replay_relevance,
        validation_status="ACCEPTED",
    )


async def record_event_async(db: AsyncSession, *, tenant_id: str = "GLOBAL_CONTROL", **kwargs) -> AuditEvent:
    result = await db.execute(
        select(AuditEvent.chain_hash)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.ingested_at.desc())
        .limit(1)
    )
    previous_chain_hash = result.scalar_one_or_none()
    row = _build_row(tenant_id=tenant_id, previous_chain_hash=previous_chain_hash, **kwargs)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def record_event_sync(db: Session, *, tenant_id: str = "GLOBAL_CONTROL", **kwargs) -> AuditEvent:
    previous_chain_hash = (
        db.query(AuditEvent.chain_hash)
        .filter(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.ingested_at.desc())
        .limit(1)
        .scalar()
    )
    row = _build_row(tenant_id=tenant_id, previous_chain_hash=previous_chain_hash, **kwargs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
