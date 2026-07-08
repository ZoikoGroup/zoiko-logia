"""
Replay manifest builder and historical reconstruction (Sections 7, 8.1).

Reconstructs everything the ledger knows about a correlation_id (a query_id,
source_id, or prompt_id) and states its own completeness honestly — a
manifest that presents itself as complete when events are missing is worse
than one that clearly declares its known gaps.

Pulls from two places: the native, chain-hashed AuditEvent ledger (fed by
source_library and model_gateway), and risk_safety's existing SafetyEvent
ledger (read-only merge — that table isn't chain-hashed yet, so those rows
are surfaced as unverified supporting evidence rather than pretending they
carry the same integrity guarantee).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domains.audit_ledger.chain_integrity import verify_event_self_consistency
from app.domains.audit_ledger.models import AuditEvent
from app.domains.risk_safety.models import SafetyEvent

# If a correlation_id's ledger events belong to this subject_type, at least
# one of these event names must be present or we flag a known gap.
_REQUIRED_EVENT_HINTS = {
    "query": [
        "risk_classification_applied",
        "risk_classification_uncertain",
        "restricted_topic_blocked",
        "safety_refusal_returned",
    ],
    "source": ["source_ingestion_event"],
    "prompt": ["prompt_template_approved", "model_run_completed"],
}


def _manifest_hash(manifest: dict) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")).hexdigest()


async def build_replay_manifest(db: AsyncSession, sync_db: Session, correlation_id: str) -> dict:
    result = await db.execute(
        select(AuditEvent)
        .where(AuditEvent.correlation_id == correlation_id)
        .order_by(AuditEvent.event_time.asc())
    )
    ledger_events = list(result.scalars().all())

    safety_events = (
        sync_db.query(SafetyEvent)
        .filter(SafetyEvent.query_id == correlation_id)
        .order_by(SafetyEvent.timestamp.asc())
        .all()
    )

    timeline = [
        {
            "event_id": e.id,
            "event_name": e.event_name,
            "event_time": e.event_time.isoformat() if e.event_time else None,
            "emitting_service": e.emitting_service,
            "payload": e.payload,
            "chain_hash": e.chain_hash,
            "replay_relevance": e.replay_relevance,
            "source": "audit_ledger",
        }
        for e in ledger_events
    ] + [
        {
            "event_id": f"safety-{e.id}",
            "event_name": e.event_type,
            "event_time": e.timestamp.isoformat() if e.timestamp else None,
            "emitting_service": "risk_safety",
            "payload": e.payload,
            "chain_hash": None,
            "replay_relevance": "REQUIRED",
            "source": "risk_safety_ledger",
        }
        for e in safety_events
    ]
    timeline.sort(key=lambda item: item["event_time"] or "")

    generated_at = datetime.now(timezone.utc).isoformat()

    if not timeline:
        manifest = {
            "correlation_id": correlation_id,
            "completeness_status": "INCOMPLETE_UNKNOWN",
            "known_gaps": [
                {
                    "event_class": "unknown",
                    "expected_event_name": "any",
                    "gap_reason": "No audit or safety events found for this correlation_id.",
                    "impact_on_replay": "Nothing can be reconstructed for this identifier.",
                }
            ],
            "manifest_trustworthiness": "INCONCLUSIVE",
            "chain_verification_result": "NOT_APPLICABLE",
            "generated_by": "audit_ledger.replay_manifest_builder",
            "generated_at": generated_at,
            "events": [],
        }
        manifest["manifest_hash"] = _manifest_hash(manifest)
        return manifest

    # Self-consistency, not full contiguity: these events are an arbitrary
    # subset of the tenant's chain (filtered by correlation_id), so the prior
    # event in each one's previous_chain_hash usually isn't in this subset.
    # Full contiguous-chain verification across the whole stream is what
    # GET /audit/chain-verify does.
    chain_passed, broken_event_id = verify_event_self_consistency(ledger_events)

    subject_type = ledger_events[0].subject_type if ledger_events else ("query" if safety_events else None)
    expected_names = _REQUIRED_EVENT_HINTS.get(subject_type, [])
    present_names = {item["event_name"] for item in timeline}

    known_gaps = []
    if expected_names and not present_names.intersection(expected_names):
        known_gaps.append(
            {
                "event_class": subject_type,
                "expected_event_name": " or ".join(expected_names),
                "gap_reason": "None of the expected event names for this subject type were found.",
                "impact_on_replay": "The decision path for this subject cannot be fully reconstructed.",
            }
        )
    if not chain_passed:
        known_gaps.append(
            {
                "event_class": "audit_ledger",
                "expected_event_name": "self-consistent chain_hash per event",
                "gap_reason": f"Event {broken_event_id}'s chain_hash does not match its own recorded fields.",
                "impact_on_replay": "This specific event may have been altered after being written.",
            }
        )

    completeness_status = "PARTIAL_KNOWN_GAPS" if known_gaps else "COMPLETE"
    manifest_trustworthiness = "LIMITED" if known_gaps else "AUTHORITATIVE"

    manifest = {
        "correlation_id": correlation_id,
        "completeness_status": completeness_status,
        "known_gaps": known_gaps,
        "manifest_trustworthiness": manifest_trustworthiness,
        "chain_verification_result": "PASS" if chain_passed else "FAIL",
        "generated_by": "audit_ledger.replay_manifest_builder",
        "generated_at": generated_at,
        "events": timeline,
    }
    manifest["manifest_hash"] = _manifest_hash(manifest)
    return manifest
