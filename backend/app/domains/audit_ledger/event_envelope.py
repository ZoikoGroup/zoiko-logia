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


async def _reassert_tenant_guc(db: AsyncSession, tenant_id: str) -> None:
    """Re-set app.tenant_id on whatever physical connection this Session
    currently holds — but skip the round trip if that exact connection is
    already known to have it set for this tenant.

    set_config(..., false) is session-scoped on Postgres, so it survives on
    a given physical connection across commits. What changes it is only the
    *pool* handing this Session a *different* physical connection after a
    commit releases the previous one back — which is the real scenario the
    unconditional re-assert below was guarding against. PoolProxiedConnection
    ("the DBAPI connection fairy").info is the SQLAlchemy-documented spot
    that persists for the lifetime of that physical connection across
    checkin/checkout, independent of any particular Session or Connection
    wrapper object — exactly what's needed to tell "same connection as last
    time" apart from "pool gave us a new one".

    Deliberately fails open to the old unconditional behavior: if this
    connection-identity lookup ever breaks (driver internals shift, a
    dialect that doesn't expose .connection the same way, etc.), we fall
    straight through to re-asserting every time, same as before this
    existed. Wrong here costs a redundant round trip, never a wrong tenant.
    """
    fairy = None
    try:
        conn = await db.connection()
        fairy = conn.sync_connection.connection
        if fairy.info.get("app_tenant_id") == tenant_id:
            return
    except Exception:
        fairy = None

    await db.execute(text("SELECT set_config('app.tenant_id', :tenant_id, false)"), {"tenant_id": tenant_id})
    if fairy is not None:
        fairy.info["app_tenant_id"] = tenant_id


async def record_event_async(
    db: AsyncSession, *, tenant_id: str = "GLOBAL_CONTROL", commit: bool = True, **kwargs
) -> AuditEvent:
    """
    commit=False batches this event into the session without ending the
    transaction — used for intermediate events within a hot phase of
    ask_kriton() (e.g. the several events emitted during retrieval) so a
    request doesn't pay ~15-20 separate commit round-trips. The row is
    still `db.add()`-ed and flushed (so constraint errors surface
    immediately) and the chain-hash contextvar is still updated — both are
    pure-Python/in-memory operations, correct regardless of commit timing.
    It's only durably persisted at the next commit=True call in the same
    request (a phase boundary, or the finalise step) — if the process
    crashes before that, this row is lost. This is an intentional, narrow
    trade: batch scope is one phase, not the whole request, so a crash
    still leaves an audit trail up to the last completed phase. See
    orchestration/audit_events.py's phase-boundary comments for which
    calls pass commit=False.
    """
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
    new_chain_hash = row.chain_hash
    db.add(row)
    _cached_previous_chain_hash.set(new_chain_hash)

    if not commit:
        # 2026-07-29 real incident: a dropped connection mid-flush here
        # (Supabase pooler / network blip) propagated unhandled, leaving the
        # session in a rolled-back state — every later query on the SAME
        # session in this request (the very next line of retrieval) then
        # failed immediately with PendingRollbackError, turning one lost
        # best-effort audit event (already an accepted trade-off per this
        # function's own docstring above) into a full request crash. Same
        # rollback-and-retry-once recovery as the commit=True path below,
        # just against flush() instead of commit() — a transient blip gets
        # one chance to recover instead of poisoning the rest of the request;
        # a sustained outage still surfaces (the retry's own exception
        # propagates), since that's a real failure the caller needs to know
        # about, not something to silently swallow.
        try:
            await db.flush()
        except Exception:
            await db.rollback()
            db.add(row)
            await db.flush()
        return row

    # Captured before commit — expire_on_commit invalidates row's attributes
    # afterward, so reading row.chain_hash post-commit would silently trigger
    # another round-trip to reload it. Nothing computed it DB-side anyway;
    # _build_row already derived it in Python.
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        db.add(row)
        await db.commit()

    # This commit just ended the transaction get_db() originally scoped to
    # this tenant (app/core/database.py). SQLAlchemy's connection pool may
    # hand the *next* statement a different physical connection than the one
    # that had app.tenant_id set on it — under concurrent load this
    # intermittently makes RLS-protected queries later in the same request
    # see zero rows, since the new connection never had it set at all.
    # Every orchestration call site already passes the request's real
    # tenant_id here, so this is insurance against exactly that race — but
    # see _reassert_tenant_guc: it only pays for a round trip when the pool
    # actually did hand back a different connection, not on every commit.
    if not settings.is_sqlite:
        await _reassert_tenant_guc(db, tenant_id)

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
