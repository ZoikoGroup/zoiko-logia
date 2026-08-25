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

import time
import uuid
from typing import Optional


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


# ── In-memory Idempotency Store ───────────────────────────────────────────────
# MVP: in-memory dict. Production requires a Redis/DB-backed store.

_idempotency_cache: dict[str, dict] = {}
_IDEMPOTENCY_TTL_SECONDS = 86_400  # 24 hours


def check_idempotency(key: str, tenant_id: str) -> Optional[dict]:
    """
    Returns the cached terminal response if the idempotency key was already used
    for this tenant within the TTL window. Returns None if this is a fresh request.
    """
    cache_key = f"{tenant_id}:{key}"
    entry = _idempotency_cache.get(cache_key)
    if entry and (time.monotonic() - entry["stored_at"]) < _IDEMPOTENCY_TTL_SECONDS:
        return entry["response"]
    return None


def store_idempotency(key: str, tenant_id: str, response: dict) -> None:
    """Persist the terminal response for an idempotency key."""
    cache_key = f"{tenant_id}:{key}"
    _idempotency_cache[cache_key] = {
        "response": response,
        "stored_at": time.monotonic(),
    }
