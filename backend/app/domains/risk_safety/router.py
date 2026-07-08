"""
Safety Service REST API — FastAPI router.

Endpoints:
  POST /classify           — Classify a query and return a safety decision
  POST /validate-output    — Post-generation professional boundary check
  GET  /escalations        — List escalation cases (filtered by status)
  POST /escalations/{id}/action — Reviewer action on an escalation case
  GET  /policies           — List active risk policies
  GET  /templates          — List refusal templates
  GET  /events             — List recent safety events (audit log)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_sync_db
from app.domains.risk_safety import service as safety_service
from app.domains.risk_safety import refusal_templates
from app.domains.risk_safety.schemas import (
    ClassifyRequest,
    SafetyDecision,
    EscalationOut,
    EscalationAction,
    RiskPolicyOut,
)
from app.domains.risk_safety.models import RiskPolicy, SafetyEvent

router = APIRouter(prefix="/safety", tags=["AI Safety & Risk Classification"])


# ─── Classification ─────────────────────────────────────────────────────────

@router.post("/classify", response_model=SafetyDecision)
def classify_query(request: ClassifyRequest, db: Session = Depends(get_sync_db)):
    """
    Classify a user query against the risk taxonomy.

    Returns a structured SafetyDecision that tells the Query Orchestrator
    whether generation is allowed and under what constraints.
    """
    return safety_service.evaluate(request, db=db)


# ─── Output Validation ──────────────────────────────────────────────────────

class ValidateOutputRequest(BaseModel):
    text: str


@router.post("/validate-output")
def validate_output(request: ValidateOutputRequest):
    """
    Post-generation boundary check on LLM output.

    Scans for prohibited professional assertions and returns cleaned text
    with appropriate disclaimers appended.
    """
    return safety_service.validate_output(request.text)


# ─── Escalation Queue ───────────────────────────────────────────────────────

@router.get("/escalations", response_model=list[EscalationOut])
def list_escalations(
    status: Optional[str] = None,
    db: Session = Depends(get_sync_db),
):
    """List escalation cases, optionally filtered by status."""
    cases = safety_service.get_escalations(db, status=status)
    return cases


@router.post("/escalations/{case_id}/action", response_model=EscalationOut)
def act_on_escalation(
    case_id: str,
    action: EscalationAction,
    db: Session = Depends(get_sync_db),
):
    """Record a reviewer decision on an escalation case."""
    case = safety_service.resolve_escalation(
        db=db,
        case_id=case_id,
        action=action.action,
        reviewer_id=action.reviewer_id,
        reason=action.reason,
    )
    if not case:
        raise HTTPException(status_code=404, detail="Escalation case not found.")
    return case


# ─── Risk Policies ──────────────────────────────────────────────────────────

@router.get("/policies", response_model=list[RiskPolicyOut])
def list_policies(db: Session = Depends(get_sync_db)):
    """List all active risk policies."""
    policies = db.query(RiskPolicy).order_by(RiskPolicy.created_at.desc()).all()
    return policies


# ─── Refusal Templates ─────────────────────────────────────────────────────

@router.get("/templates")
def list_templates():
    """List all registered refusal and limitation templates."""
    return refusal_templates.get_all_templates()


# ─── Safety Event Log ──────────────────────────────────────────────────────

@router.get("/events")
def list_events(limit: int = 50, db: Session = Depends(get_sync_db)):

    """List recent safety events from the audit ledger."""
    events = (
        db.query(SafetyEvent)
        .order_by(SafetyEvent.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "query_id": e.query_id,
            "payload": e.payload,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        }
        for e in events
    ]
