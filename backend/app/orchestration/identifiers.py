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


async def check_idempotency(db: AsyncSession, key: str, tenant_id: str) -> Optional[dict]:
    """
    Returns the cached terminal response if the idempotency key was already used
    for this tenant within the TTL window. Returns None if this is a fresh request.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_IDEMPOTENCY_TTL_SECONDS)
    result = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        return None
    created_at = record.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if created_at < cutoff:
        await db.delete(record)
        await db.commit()
        return None
    return record.response_json


async def store_idempotency(db: AsyncSession, key: str, tenant_id: str, response: dict) -> None:
    """Persist the terminal response for an idempotency key."""
    # Remove an expired record first so the tenant/key uniqueness constraint
    # remains the concurrency guard for live records.
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_IDEMPOTENCY_TTL_SECONDS)
    await db.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.idempotency_key == key,
            IdempotencyRecord.created_at < cutoff,
        )
    )
    existing = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(IdempotencyRecord(
            tenant_id=tenant_id,
            idempotency_key=key,
            response_json=response,
        ))
    await db.commit()
