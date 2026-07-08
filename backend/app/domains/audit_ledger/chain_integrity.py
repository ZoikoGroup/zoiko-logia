"""
Tenant-scoped hash chaining and chain integrity verification (Sections 6, 11).

Each AuditEvent's chain_hash links event_id + event_name + payload_hash to the
previous event's chain_hash for the same tenant. Recomputing the chain and
comparing against the stored chain_hash detects a missing, reordered, or
altered event.
"""
from __future__ import annotations

import hashlib
import json


def compute_payload_hash(payload: dict) -> str:
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_chain_hash(event_id: str, event_name: str, payload_hash: str, previous_chain_hash: str | None) -> str:
    material = f"{event_id}|{event_name}|{payload_hash}|{previous_chain_hash or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verify_chain(events: list) -> tuple[bool, str | None]:
    """Recompute the chain over `events` (must be the FULL, tenant-scoped
    ledger ordered oldest-first) — contiguity only means something over a
    complete sequential stream. Returns (passed, first_broken_event_id).
    """
    previous_hash: str | None = None
    for event in events:
        expected = compute_chain_hash(event.id, event.event_name, event.payload_hash, previous_hash)
        if expected != event.chain_hash:
            return False, event.id
        previous_hash = event.chain_hash
    return True, None


def verify_event_self_consistency(events: list) -> tuple[bool, str | None]:
    """Check each event's own chain_hash against its own recorded
    previous_chain_hash, independent of whether the prior event in the
    tenant's full chain is present in this subset.

    Use this for an arbitrary subset (e.g. one correlation_id's events out of
    a replay manifest) where full contiguity can't be assessed — it still
    confirms no single event's id, name, payload_hash, or previous_chain_hash
    was altered after the fact. Full contiguous-chain verification across a
    tenant's complete stream is verify_chain()'s job.
    """
    for event in events:
        expected = compute_chain_hash(event.id, event.event_name, event.payload_hash, event.previous_chain_hash)
        if expected != event.chain_hash:
            return False, event.id
    return True, None
