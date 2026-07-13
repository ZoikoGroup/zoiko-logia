"""
Pydantic request / response schemas for the Safety Service API.

These schemas define the JSON contracts between:
  • Query Orchestrator  →  Safety Service  (ClassifyRequest)
  • Safety Service      →  Kriton / Frontend (SafetyDecision)
  • Frontend            →  Escalation API    (EscalationOut, EscalationAction)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ─── Classification Request / Response ──────────────────────────────────────

class ClassifyRequest(BaseModel):
    """Payload sent by the Query Orchestrator to the Safety Service."""
    query: str = Field(..., min_length=1, description="User question text")
    user_id: str = Field(default="anonymous")
    role: str = Field(default="Learner")
    tenant_id: str = Field(default="default")
    jurisdiction: str = Field(default="")
    mode: str = Field(default="Workflow", description="Learning | Practice | Workflow | Review | Admin | Support")
    source_confidence: str = Field(default="HIGH_CONFIDENCE", description="HIGH_CONFIDENCE, SUFFICIENT, LOW_CONFIDENCE, NO_ELIGIBLE_SOURCE, CONFLICT_UNRESOLVED")
    pre_bundle_state: str = Field(default="OK", description="OK, LICENSE_BLOCKED, ONTOLOGY_UNRESOLVED")
    privacy_class: str = Field(default="NONE", description="NONE, PII, MINOR_DATA, TENANT_CONFIDENTIAL, LEGAL_HOLD, SECRETS, PROTECTED_SOURCE")
    tenant_policy_conflict: bool = Field(default=False)
    tool_required: bool = Field(default=False)


class SafetyDecision(BaseModel):
    """Structured decision returned by the Safety Service."""
    allowed: bool
    risk_level: str                            # LOW | MEDIUM | HIGH | RESTRICTED
    restricted_sub_class: Optional[str] = None
    route: str                                 # LLM | HUMAN_REVIEW | REFUSAL | CLARIFICATION | …
    confidence: float = 1.0
    requires_sources: bool = False
    requires_human_review: bool = False
    requires_citation: bool = False
    requires_professional_boundary: bool = False
    limitations: list[str] = Field(default_factory=list)
    refusal_text: Optional[str] = None
    safe_alternative: Optional[str] = None
    rules_applied: list[str] = Field(default_factory=list)
    query_id: Optional[str] = None
    classifier_version: Optional[str] = None
    policy_version: Optional[str] = None


# ─── Escalation Schemas ────────────────────────────────────────────────────

class EscalationOut(BaseModel):
    """Read-only representation of an escalation case for the frontend."""
    id: str
    query_id: str
    query_text: str
    topic: str
    risk_level: str
    restricted_sub_class: Optional[str] = None
    jurisdiction: str
    owner: Optional[str] = None
    reviewer_role: Optional[str] = None
    sla_deadline: Optional[datetime] = None
    status: str
    route_reason: Optional[str] = None
    detail: Optional[str] = None
    evidence_refs: list[str] = Field(default_factory=list)
    reviewer_decision: Optional[str] = None
    reviewer_id: Optional[str] = None
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EscalationAction(BaseModel):
    """Payload for a reviewer taking action on an escalation case."""
    action: str = Field(..., description="approve | refuse | escalate | request_info")
    reviewer_id: str
    reason: str = ""


class EscalationStatsOut(BaseModel):
    total: int
    pending: int
    under_review: int
    resolved: int
    refused: int
    escalated: int
    over_sla: int


# ─── Risk Policy Schemas ───────────────────────────────────────────────────

class RiskPolicyOut(BaseModel):
    """Read-only representation of a risk policy for the frontend."""
    id: str
    version: str
    scope: str
    owner: str
    rules: list
    effective_from: Optional[datetime] = None
    approver: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─── Safety Override Schema ────────────────────────────────────────────────

class OverrideRequest(BaseModel):
    """Request to create a time-bounded safety override."""
    actor_id: str
    authority_role: str
    original_route: str
    new_route: str
    scope: str
    reason: str
    duration_hours: int = Field(default=24, le=72, description="Max 72 hours per ZL-T0-04 §10.1")


class SafetyOverrideOut(BaseModel):
    id: str
    actor_id: str
    authority_role: str
    original_route: str
    new_route: str
    scope: str
    reason: str
    created_at: datetime
    expires_at: datetime
    post_action_review_due: Optional[datetime] = None
    is_active: bool

    model_config = {"from_attributes": True}


class EmergencyBlockRequest(BaseModel):
    """Request to create a time-bounded emergency block."""
    invoker: str
    approver: str
    scope: str
    reason: str
    duration_hours: int = Field(default=24, le=72, description="Max 72 hours per ZL-T0-04 §14")
