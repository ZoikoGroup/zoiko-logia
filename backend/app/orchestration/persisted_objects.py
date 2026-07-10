"""
Persisted objects for escalation and incident handling — ZL-ENG-02 §11.

create_review_case()       — §11.1: created on route == HUMAN_REVIEW
create_security_incident() — §11.2: created on route == SECURITY_INCIDENT

Per §8.1: returning HUMAN_REVIEW label without a persisted object is non-compliant.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.orchestration.models import ReviewCase
from app.orchestration.routing_matrix import CLASSIFIER_VERSION, POLICY_VERSION


def _evidence_ref(trigger: str, trigger_detail: str, query_id: str) -> str:
    """SHA-256 reference to the triggering evidence (never stores raw query)."""
    raw = json.dumps({"trigger": trigger, "detail": trigger_detail, "query_id": query_id}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def create_review_case(
    db: AsyncSession,
    *,
    query_id: str,
    correlation_id: str,
    tenant_id: str,
    risk_level: str,
    confidence_state: str,
    reason: str,
    assigned_queue: str = "accounting_review",
) -> ReviewCase:
    """
    Persist a review case for HUMAN_REVIEW route — §11.1.
    Must be written before response is returned.
    """
    case = ReviewCase(
        query_id=query_id,
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        risk_level=risk_level,
        confidence_state=confidence_state,
        reason=reason,
        assigned_queue=assigned_queue,
        policy_version=POLICY_VERSION,
        classifier_version=CLASSIFIER_VERSION,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


def create_security_incident_sync(
    db: Session,
    *,
    query_id: str,
    correlation_id: str,
    tenant_id: str,
    trigger: str,
    trigger_detail: str,
) -> dict:
    """
    Persist a security incident object for SECURITY_INCIDENT route — §11.2.
    Uses sync session because pre-screen runs before the async pipeline.
    Returns the incident dict (the model lives in support_incident domain).
    """
    from app.domains.support_incident.models import SecurityIncident

    evidence_ref = _evidence_ref(trigger, trigger_detail, query_id)

    incident = SecurityIncident(
        tenant_id=tenant_id,
        title=f"Pre-screen security incident: {trigger}",
        severity="High",
        containment_status="OPEN",
        source=trigger.upper(),
        query_id=query_id,
        restricted_sub_class="RESTRICTED_CONTROL_BYPASS",
        timeline=[{
            "timestamp": "auto",
            "actor": "system",
            "action": "created",
            "note": f"Auto-created by pre-screen safety gate. Trigger: {trigger}. Evidence ref: {evidence_ref}",
            "correlation_id": correlation_id,
        }],
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    return {
        "incident_id": incident.id,
        "query_id": query_id,
        "correlation_id": correlation_id,
        "tenant_id": tenant_id,
        "trigger": trigger,
        "evidence_reference": evidence_ref,
        "status": "open",
    }
