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

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_sync_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user, require_admin, require_safety_reviewer
from app.domains.risk_safety import classifier_metrics, llm_classifier
from app.domains.risk_safety import service as safety_service
from app.domains.risk_safety import refusal_templates
from app.domains.risk_safety.schemas import (
    ClassifyRequest,
    SafetyDecision,
    EscalationOut,
    EscalationAction,
    RiskPolicyOut,
    EscalationStatsOut,
    SafetyOverrideOut,
    OverrideRequest,
    EmergencyBlockOut,
    EmergencyBlockCreateRequest,
    EmergencyBlockDisposeRequest,
)
from app.domains.risk_safety.models import RiskPolicy, SafetyEvent

router = APIRouter(prefix="/safety", tags=["AI Safety & Risk Classification"])


# ─── Classification ─────────────────────────────────────────────────────────

@router.post("/classify", response_model=SafetyDecision)
def classify_query(
    request: ClassifyRequest,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """
    Classify a user query against the risk taxonomy.

    Returns a structured SafetyDecision that tells the Query Orchestrator
    whether generation is allowed and under what constraints.
    """
    trusted_request = request.model_copy(update={
        "user_id": current_user.id,
        "tenant_id": current_user.tenant_id,
        "role": current_user.role,
    })
    return safety_service.evaluate(trusted_request, db=db)


# ─── Output Validation ──────────────────────────────────────────────────────

class ValidateOutputRequest(BaseModel):
    text: str
    tenant_id: str = "default"


@router.post("/validate-output")
def validate_output(request: ValidateOutputRequest, _current_user: User = Depends(get_current_user)):
    """
    Post-generation boundary check on LLM output.

    Scans for prohibited professional assertions and returns cleaned text
    with appropriate disclaimers appended.
    """
    return safety_service.validate_output(request.text, tenant_id=request.tenant_id)


# ─── Escalation Queue ───────────────────────────────────────────────────────

@router.get("/classifier-metrics")
def get_classifier_metrics(_current_user: User = Depends(get_current_user)):
    """Whether the LLM classifier is being consulted, and whether it answers.

    The two questions that decide if RISK_LLM_CLASSIFIER_MODE should stay on:
    `llm_answer_rate` near zero with a non-zero total means the provider is
    failing on every call (check the key, the model name, the provider), and a
    low `within_budget_rate` means QUERY_UNDERSTANDING_REMOTE_TIMEOUT_SECONDS
    is too tight for the configured model.

    Authenticated: rollout mode and provider behaviour are operational detail.
    """
    return {
        "mode": llm_classifier.configured_mode(),
        "local_ml_enabled": os.getenv("ENABLE_ML_CLASSIFIER", "").lower() in {"1", "true", "yes"},
        # Stated because of a config interaction that surprises people: with
        # the local model disabled, "fallback" is not a fallback — the local
        # classifier is always unavailable, so the LLM fires for every query
        # that no deterministic pattern already settled.
        "llm_is_effective_primary": (
            llm_classifier.configured_mode() in {"fallback", "shadow", "primary"}
            and os.getenv("ENABLE_ML_CLASSIFIER", "").lower() not in {"1", "true", "yes"}
        ),
        **classifier_metrics.snapshot(),
    }


@router.get("/escalations/stats", response_model=EscalationStatsOut)
def get_escalation_stats(
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """Summary counts for the escalation queue dashboard."""
    return safety_service.get_escalation_stats(db, current_user.tenant_id)


@router.get("/escalations", response_model=list[EscalationOut])
def list_escalations(
    status: Optional[str] = None,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """List escalation cases, optionally filtered by status."""
    cases = safety_service.get_escalations(db, current_user.tenant_id, status=status)
    return cases


@router.post("/escalations/{case_id}/action", response_model=EscalationOut)
def act_on_escalation(
    case_id: str,
    action: EscalationAction,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_safety_reviewer),
):
    """Record a reviewer decision on an escalation case."""
    case = safety_service.resolve_escalation(
        db=db,
        case_id=case_id,
        action=action.action,
        reviewer_id=current_user.id,
        tenant_id=current_user.tenant_id,
        reason=action.reason,
    )
    if not case:
        raise HTTPException(status_code=404, detail="Escalation case not found.")
    return case


# ─── Safety Overrides ───────────────────────────────────────────────────────

@router.get("/overrides", response_model=list[SafetyOverrideOut])
def list_safety_overrides(
    active_only: bool = True,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """List safety overrides."""
    return safety_service.list_safety_overrides(db, current_user.tenant_id, active_only=active_only)


@router.post("/overrides", response_model=SafetyOverrideOut)
def create_safety_override(
    request: OverrideRequest,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_admin),
):
    """Create a new time-bounded safety override."""
    trusted_request = request.model_copy(update={
        "actor_id": current_user.id,
        "authority_role": current_user.role,
    })
    return safety_service.create_safety_override(db, trusted_request, current_user.tenant_id)


# ─── Emergency Safety Blocks (ZL-T0-04 §14) ─────────────────────────────────

@router.get("/emergency-blocks", response_model=list[EmergencyBlockOut])
def list_emergency_blocks(
    active_only: bool = True,
    db: Session = Depends(get_sync_db),
):
    """List emergency safety blocks."""
    return safety_service.list_emergency_blocks(db, active_only=active_only)


@router.post("/emergency-blocks", response_model=EmergencyBlockOut)
def create_emergency_block(
    request: EmergencyBlockCreateRequest,
    db: Session = Depends(get_sync_db),
):
    """Create a new time-bounded (max 72h) emergency safety block. invoker
    and approver must be different people (maker-checker, ZL-T0-04 §14)."""
    try:
        return safety_service.create_emergency_block(db, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/emergency-blocks/{block_id}/dispose", response_model=EmergencyBlockOut)
def dispose_emergency_block(
    block_id: str,
    request: EmergencyBlockDisposeRequest,
    db: Session = Depends(get_sync_db),
):
    """Manually release or roll back an emergency block before its natural expiry."""
    block = safety_service.dispose_emergency_block(db, block_id, request.reviewer, request.disposition)
    if block is None:
        raise HTTPException(status_code=404, detail="Emergency safety block not found")
    return block


# ─── Risk Policies ──────────────────────────────────────────────────────────

@router.get("/policies", response_model=list[RiskPolicyOut])
def list_policies(
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """List all active risk policies."""
    policies = db.query(RiskPolicy).order_by(RiskPolicy.created_at.desc()).all()
    return policies


# ─── Refusal Templates ─────────────────────────────────────────────────────

@router.get("/templates")
def list_templates(_current_user: User = Depends(get_current_user)):
    """List all registered refusal and limitation templates."""
    return refusal_templates.get_all_templates()


# ─── Safety Event Log ──────────────────────────────────────────────────────

@router.get("/events")
def list_events(
    limit: int = 50,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):

    """List recent safety events from the audit ledger."""
    events = (
        db.query(SafetyEvent)
        .filter(SafetyEvent.tenant_id == current_user.tenant_id)
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
