"""
Identifier generation and idempotency store — ZL-ENG-02 §5.

Identifiers:
  query_id        — business-level query lifecycle ID
  correlation_id  — cross-service trace ID
  request_id      — HTTP request instance ID
  audit_chain_id  — audit ledger chain reference

MVP concession per §5: query_id is reused as correlation_id where documented.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.orchestration_state.models import IdempotencyRecord


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def generate_query_id() -> str:
    return _new_id("qry")


def generate_correlation_id() -> str:
    return _new_id("corr")


def generate_request_id() -> str:
    return _new_id("req")


def generate_audit_chain_id() -> str:
    return _new_id("aud")


_IDEMPOTENCY_TTL_SECONDS = 86_400  # 24 hours
_RUNNING = "__running__"


def scope_idempotency_key(key: str, engagement_id: str | None) -> str:
    """Prevent a tenant-wide key collision from crossing engagement scope."""
    return f"{engagement_id or '_personal'}:{key}"


async def check_idempotency(db: AsyncSession, key: str, tenant_id: str) -> Optional[dict]:
    """
    Returns the cached terminal response if the idempotency key was already used
    for this tenant within the TTL window. Returns None if this is a fresh request.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_IDEMPOTENCY_TTL_SECONDS)
    result = await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.idempotency_key == key,
        IdempotencyRecord.created_at > cutoff,
    ))
    row = result.scalar_one_or_none()
    if row and row.response_json.get("status") != _RUNNING:
        return row.response_json
    return None


async def claim_idempotency(db: AsyncSession, key: str, tenant_id: str) -> bool:
    """Atomically reserve a key across processes and workers."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_IDEMPOTENCY_TTL_SECONDS)
    await db.execute(delete(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.idempotency_key == key,
        IdempotencyRecord.created_at <= cutoff,
    ))
    try:
        async with db.begin_nested():
            db.add(IdempotencyRecord(
                tenant_id=tenant_id,
                idempotency_key=key,
                response_json={"status": _RUNNING},
            ))
            await db.flush()
        # Reservation must be visible before expensive work begins.
        await db.commit()
        return True
    except IntegrityError:
        await db.rollback()
        return False


async def store_idempotency(
    db: AsyncSession, key: str, tenant_id: str, response: dict
) -> None:
    """Stage a terminal response for the final audit transaction."""
    result = await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.idempotency_key == key,
    ))
    row = result.scalar_one()
    row.response_json = response


async def abandon_idempotency(db: AsyncSession, key: str, tenant_id: str) -> None:
    """Release a failed/timed-out reservation so a retry can execute."""
    result = await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.idempotency_key == key,
    ))
    row = result.scalar_one_or_none()
    if row and row.response_json.get("status") == _RUNNING:
        await db.delete(row)
        await db.commit()
