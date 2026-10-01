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


def scope_idempotency_key(
    key: str, engagement_id: str | None, actor_id: str | None = None,
) -> str:
    """Prevent tenant-wide collisions across engagement or personal scope."""
    scope = f"engagement:{engagement_id}" if engagement_id else f"actor:{actor_id or '_unknown'}"
    return f"{scope}:{key}"


async def check_idempotency(
    db: AsyncSession, key: str, tenant_id: str, request_hash: str | None = None
) -> Optional[dict]:
    """
    Return the durable terminal response for this tenant/key. When a request hash
    is supplied, it prevents a client from accidentally reusing one key for
    different input.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_IDEMPOTENCY_TTL_SECONDS)
    result = await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.idempotency_key == key,
        IdempotencyRecord.created_at > cutoff,
    ))
    row = result.scalar_one_or_none()
    if row is None or row.response_json.get("status") == _RUNNING:
        return None
    envelope = row.response_json
    if request_hash is not None and "request_hash" in envelope:
        if envelope["request_hash"] != request_hash:
            raise ValueError("Idempotency-Key was already used for a different request")
        return envelope.get("response")
    return envelope


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
    db: AsyncSession,
    key: str,
    tenant_id: str,
    request_hash: Optional[str] = None,
    response: Optional[dict] = None,
) -> None:
    """Persist a terminal response so every API worker sees the same result."""
    # Callers that do not hash the request pass the response in its place.
    if response is None:
        request_hash, response = None, request_hash
    result = await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.idempotency_key == key,
    ))
    record = result.scalar_one_or_none()
    if request_hash is None:
        envelope = response
    else:
        envelope = {"request_hash": request_hash, "response": response}
    if record is None:
        db.add(IdempotencyRecord(
            tenant_id=tenant_id, idempotency_key=key, response_json=envelope,
        ))
    else:
        record.response_json = envelope
    await db.commit()


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
