"""
Canonical audit event envelope (Section 4).

Every domain that emits an audit event goes through record_event_async (for
domains on the async ORM session, e.g. source_library, model_gateway) or
record_event_sync (for domains on the sync session, e.g. risk_safety) so
every event is hashed and chained the same way regardless of caller.

Envelope rule: payload fields vary by event_name, but envelope fields do not.
"""
from __future__ import annotations

import asyncio
import contextvars
import time
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domains.audit_ledger.chain_integrity import compute_chain_hash, compute_payload_hash
from app.domains.audit_ledger.models import AuditEvent, _event_id, _now

settings = get_settings()

# A transient DB fault mid-request has two flavours, and both are recoverable:
#   1. Supabase's pooler reaps the pooled connection while it sits idle during
#      the long web-search + LLM calls between audit writes → the next
#      statement fails with a "connection is closed" DBAPIError whose
#      connection_invalidated flag is set.
#   2. The reconnect that recovery attempts can itself briefly fail if the
#      local network/DNS blinks at that exact moment → a raw OSError such as
#      "[Errno 11001] getaddrinfo failed" (host lookup failed).
# A single instant retry handles (1) but not (2): a network blink usually
# clears in well under a second, and retrying instantly just hits the same
# blink. So retry a few times with a short, growing backoff, which gives the
# network time to come back before giving up.
_DB_RETRY_BACKOFFS = (0.4, 1.2, 3.0)  # seconds between attempts; len+1 = max tries


def _is_transient_db_error(exc: BaseException) -> bool:
    """True for the recoverable connection faults above: a reaped pooled
    connection (DBAPIError with connection_invalidated) or a network/DNS blink
    on reconnect (OSError, e.g. getaddrinfo failed). A real query/constraint
    error is NOT transient and must propagate."""
    if isinstance(exc, DBAPIError):
        return bool(exc.connection_invalidated)
    return isinstance(exc, OSError)

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


async def _execute_reconnect(db: AsyncSession, stmt, params=None):
    """Run a statement, retrying transient connection faults (see
    _is_transient_db_error) with a short growing backoff. pool_pre_ping only
    validates at checkout (request start), not mid-request, so any of the DB
    touches in a single ask_kriton() request can hit a reaped connection — not
    just the commit. rollback discards the dead connection; the retry then
    acquires a fresh, pre-pinged one from the pool once the network is back."""
    for backoff in _DB_RETRY_BACKOFFS:
        try:
            return await db.execute(stmt, params)
        except (DBAPIError, OSError) as exc:
            if not _is_transient_db_error(exc):
                raise
            try:
                await db.rollback()
            except Exception:
                pass  # rolling back a dead connection may itself fail — ignore
            await asyncio.sleep(backoff)
    # Final attempt: let a still-failing error propagate to the caller.
    return await db.execute(stmt, params)


async def record_event_async(db: AsyncSession, *, tenant_id: str = "GLOBAL_CONTROL", **kwargs) -> AuditEvent:
    # For request-scoped events the actor is also the authenticated user whose
    # id get_db() placed in app.user_id.  Keep it before commit so both RLS
    # settings can be restored if SQLAlchemy checks out a different pooled
    # connection afterwards.
    rls_user_id = kwargs.get("actor_id") or ""
    previous_chain_hash = _cached_previous_chain_hash.get()
    if previous_chain_hash is None:
        # Only hit the DB for the first event of this request (task) — every
        # subsequent event in the same request already knows its own
        # immediately-previous write from the cache below, with no lookup.
        result = await _execute_reconnect(
            db,
            select(AuditEvent.chain_hash)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.ingested_at.desc())
            .limit(1),
        )
        previous_chain_hash = result.scalar_one_or_none()

    row = _build_row(tenant_id=tenant_id, previous_chain_hash=previous_chain_hash, **kwargs)
    # Captured before commit — expire_on_commit invalidates row's attributes
    # afterward, so reading row.chain_hash post-commit would silently trigger
    # another round-trip to reload it. Nothing computed it DB-side anyway;
    # _build_row already derived it in Python.
    new_chain_hash = row.chain_hash
    db.add(row)
    # Commit with the same transient-fault backoff retry as _execute_reconnect:
    # the pooler can reap the connection mid-request, and the reconnect can hit
    # a brief network/DNS blink — both recover once a fresh connection is
    # acquired. rollback discards the dead connection; re-adding the row lets
    # the retried commit write it on the new one.
    for backoff in _DB_RETRY_BACKOFFS:
        try:
            await db.commit()
            break
        except (DBAPIError, OSError) as exc:
            if not _is_transient_db_error(exc):
                raise
            try:
                await db.rollback()
            except Exception:
                pass
            db.add(row)
            await asyncio.sleep(backoff)
    else:
        await db.commit()  # final attempt — propagate if still failing
    _cached_previous_chain_hash.set(new_chain_hash)

    # This commit just ended the transaction get_db() originally scoped to
    # this tenant (app/core/database.py). SQLAlchemy's connection pool may
    # hand the *next* statement a different physical connection than the one
    # that had app.tenant_id set on it — under concurrent load this
    # intermittently makes RLS-protected queries later in the same request
    # see zero rows, since the new connection never had it set at all.
    # Every orchestration call site already passes the request's real tenant
    # and actor ids here. Re-assert both: workspace-document policies require
    # app.user_id as well as app.tenant_id, so restoring only the tenant makes
    # valid document chunks disappear without a query error.
    if not settings.is_sqlite:
        await _execute_reconnect(
            db,
            text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
            {"tenant_id": tenant_id},
        )
        await _execute_reconnect(
            db,
            text("SELECT set_config('app.user_id', :user_id, false)"),
            {"user_id": rls_user_id},
        )

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
    # Same transient-fault backoff retry as the async path above (see its
    # comment) — the sync session is likewise held idle across the slow calls
    # and can be reaped by the pooler, and its reconnect can hit a network
    # blink. Uses time.sleep since this is a synchronous code path.
    for backoff in _DB_RETRY_BACKOFFS:
        try:
            db.commit()
            break
        except (DBAPIError, OSError) as exc:
            if not _is_transient_db_error(exc):
                raise
            try:
                db.rollback()
            except Exception:
                pass
            db.add(row)
            time.sleep(backoff)
    else:
        db.commit()  # final attempt — propagate if still failing
    db.refresh(row)
    return row
