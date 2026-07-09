"""
Retention policy lookup and legal hold controls (Section 9).

Final retention periods by event class/jurisdiction/tenant plan are an open
decision pending Legal/Compliance + Data Governance sign-off (Section 20).
This module provides the minimum viable lookup so every event can already
declare which policy governs it, rather than defaulting to "keep forever."
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.models import AuditEvent

RETENTION_MATRIX = {
    "risk_classification_applied": "7_YEARS_REGULATED_ANSWER",
    "risk_classification_uncertain": "7_YEARS_REGULATED_ANSWER",
    "restricted_topic_blocked": "7_YEARS_REGULATED_ANSWER",
    "safety_refusal_returned": "7_YEARS_REGULATED_ANSWER",
    "human_review_case_created": "7_YEARS_REGULATED_ANSWER",
    "human_review_decision_recorded": "7_YEARS_REGULATED_ANSWER",
    "security_incident_created": "RETAIN_WHILE_INCIDENT_OPEN",
    "source_ingestion_event": "LIFE_OF_SOURCE_PLUS_7_YEARS",
    "source_version_approved": "LIFE_OF_SOURCE_PLUS_7_YEARS",
    "model_run_completed": "RISK_TENANT_PROVIDER_DEPENDENT",
    "prompt_template_approved": "RISK_TENANT_PROVIDER_DEPENDENT",
}
DEFAULT_RETENTION = "OPEN_DECISION_PENDING_LEGAL_COMPLIANCE"


def retention_policy_for(event_name: str) -> str:
    return RETENTION_MATRIX.get(event_name, DEFAULT_RETENTION)


async def apply_legal_hold(db: AsyncSession, *, event_ids: list[str], legal_hold_id: str) -> int:
    """Overrides standard deletion/archival for the given events (Section 9)."""
    result = await db.execute(select(AuditEvent).where(AuditEvent.id.in_(event_ids)))
    events = list(result.scalars().all())
    for event in events:
        event.legal_hold_id = legal_hold_id
    await db.commit()
    return len(events)


async def release_legal_hold(db: AsyncSession, *, event_ids: list[str]) -> int:
    result = await db.execute(select(AuditEvent).where(AuditEvent.id.in_(event_ids)))
    events = list(result.scalars().all())
    for event in events:
        event.legal_hold_id = None
    await db.commit()
    return len(events)
