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
from typing import Optional

from sqlalchemy import select
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


async def check_idempotency(
    db: AsyncSession, key: str, tenant_id: str, request_hash: str
) -> Optional[dict]:
    """
    Return the durable terminal response for this tenant/key. The request hash
    prevents a client from accidentally reusing one key for different input.
    """
    result = await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.idempotency_key == key,
    ))
    record = result.scalar_one_or_none()
    if record is None:
        return None
    envelope = record.response_json
    if envelope.get("request_hash") != request_hash:
        raise ValueError("Idempotency-Key was already used for a different request")
    return envelope.get("response")


async def store_idempotency(
    db: AsyncSession, key: str, tenant_id: str, request_hash: str, response: dict
) -> None:
    """Persist a terminal response so every API worker sees the same result."""
    result = await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.idempotency_key == key,
    ))
    record = result.scalar_one_or_none()
    envelope = {"request_hash": request_hash, "response": response}
    if record is None:
        db.add(IdempotencyRecord(
            tenant_id=tenant_id, idempotency_key=key, response_json=envelope,
        ))
    else:
        record.response_json = envelope
    await db.commit()
