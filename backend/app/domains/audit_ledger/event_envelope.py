"""
Canonical audit event envelope (Section 4).

Every domain that emits an audit event goes through record_event_async (for
domains on the async ORM session, e.g. source_library, model_gateway) or
record_event_sync (for domains on the sync session, e.g. risk_safety) so
every event is hashed and chained the same way regardless of caller.

Envelope rule: payload fields vary by event_name, but envelope fields do not.
"""
from __future__ import annotations

import contextvars
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domains.audit_ledger.chain_integrity import compute_chain_hash, compute_payload_hash
from app.domains.audit_ledger.models import AuditEvent, _event_id, _now

settings = get_settings()

# A single ask_kriton() call emits ~15 audit events in strict sequence, and
# each one previously re-queried "what was the last chain_hash?" from
# Postgres before writing — a genuinely unnecessary round-trip, since this
# process already knows its own immediately-previous write (it just made
# it). Cached here per async task (i.e. per request — FastAPI/Starlette
# gives each request its own context, so this never leaks between
# concurrent requests), and only falls back to a real DB lookup for the
# first event of a request, when no prior write in this task is known yet.
_cached_previous_chain_hash: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "audit_previous_chain_hash", default=None
)


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
    previous_chain_hash = _cached_previous_chain_hash.get()
    if previous_chain_hash is None:
        # Only hit the DB for the first event of this request (task) — every
        # subsequent event in the same request already knows its own
        # immediately-previous write from the cache below, with no lookup.
        result = await db.execute(
            select(AuditEvent.chain_hash)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.ingested_at.desc())
            .limit(1)
        )
        previous_chain_hash = result.scalar_one_or_none()

    row = _build_row(tenant_id=tenant_id, previous_chain_hash=previous_chain_hash, **kwargs)
    # Captured before commit — expire_on_commit invalidates row's attributes
    # afterward, so reading row.chain_hash post-commit would silently trigger
    # another round-trip to reload it. Nothing computed it DB-side anyway;
    # _build_row already derived it in Python.
    new_chain_hash = row.chain_hash
    db.add(row)
    await db.commit()
    _cached_previous_chain_hash.set(new_chain_hash)

    # This commit just ended the transaction get_db() originally scoped to
    # this tenant (app/core/database.py). SQLAlchemy's connection pool may
    # hand the *next* statement a different physical connection than the one
    # that had app.tenant_id set on it — under concurrent load this
    # intermittently makes RLS-protected queries later in the same request
    # see zero rows, since the new connection never had it set at all.
    # Every orchestration call site already passes the request's real
    # tenant_id here, so re-asserting it right after commit is free
    # insurance against exactly that race, regardless of which connection
    # the pool hands back next.
    if not settings.is_sqlite:
        await db.execute(text("SELECT set_config('app.tenant_id', :tenant_id, false)"), {"tenant_id": tenant_id})

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
