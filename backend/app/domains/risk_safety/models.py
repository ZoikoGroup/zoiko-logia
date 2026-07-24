"""
Risk Safety domain — ORM models.

Implements the database-backed policy objects defined in ZL-T0-04 §14:
  • RiskPolicy          — versioned classification rule sets
  • EscalationCase      — human-review cases with SLA tracking
  • SafetyOverride      — time-bounded (max 72 h) override records
  • RefusalTemplateRow  — approved refusal / limitation message templates
  • SafetyEvent         — immutable ledger of every safety decision
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, DateTime, Float, Text, JSON, Boolean, Enum, Integer,
)
from app.db.base import Base


# ─── Enumerations ───────────────────────────────────────────────────────────

class RiskLevel(str, enum.Enum):
    ZERO = "ZERO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    RESTRICTED = "RESTRICTED"


class RestrictedSubClass(str, enum.Enum):
    ACADEMIC_INTEGRITY = "RESTRICTED_ACADEMIC_INTEGRITY"
    ADVICE_INSUFFICIENT_CONTEXT = "RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT"
    SOURCE_PROHIBITED = "RESTRICTED_SOURCE_PROHIBITED"
    CONTROL_BYPASS = "RESTRICTED_CONTROL_BYPASS"


class EscalationStatus(str, enum.Enum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    REFUSED = "REFUSED"


class Route(str, enum.Enum):
    LLM = "LLM"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    REFUSAL = "REFUSAL"
    CLARIFICATION = "CLARIFICATION"
    SAFE_EDUCATION = "SAFE_EDUCATION"
    LICENSE_PATH = "LICENSE_PATH"
    SECURITY_INCIDENT = "SECURITY_INCIDENT"


# ─── Helper ─────────────────────────────────────────────────────────────────

def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Models ─────────────────────────────────────────────────────────────────

class RiskPolicy(Base):
    """A versioned set of classification rules (ZL-T0-04 §14 risk_policy)."""
    __tablename__ = "risk_policies"

    id = Column(String, primary_key=True, default=lambda: _new_id("pol-"))
    version = Column(String, nullable=False)
    scope = Column(String, nullable=False, default="global")
    owner = Column(String, nullable=False, default="ai-risk-committee")
    rules = Column(JSON, nullable=False, default=list)
    effective_from = Column(DateTime, default=_utcnow)
    approver = Column(String, nullable=True)
    rollback_target = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class EscalationCase(Base):
    """A human-review case triggered by safety classification (ZL-T0-04 §10)."""
    __tablename__ = "escalation_cases"

    id = Column(String, primary_key=True, default=lambda: _new_id("ESC-"))
    query_id = Column(String, nullable=False)
    query_text = Column(Text, nullable=False)
    topic = Column(String, nullable=False)
    # Same schema-drift gap as SafetyEvent.tenant_id above — the live DB has
    # a NOT NULL tenant_id column here too, added outside this codebase's
    # own migrations, never declared on this model.
    tenant_id = Column(String, nullable=True)
    risk_level = Column(Enum(RiskLevel), nullable=False)
    restricted_sub_class = Column(Enum(RestrictedSubClass), nullable=True)
    jurisdiction = Column(String, nullable=False, default="GLOBAL")
    owner = Column(String, nullable=True)
    reviewer_role = Column(String, nullable=True)
    sla_deadline = Column(DateTime, nullable=True)
    status = Column(Enum(EscalationStatus), default=EscalationStatus.PENDING)
    route_reason = Column(String, nullable=True)
    detail = Column(Text, nullable=True)
    evidence_refs = Column(JSON, default=list)
    reviewer_decision = Column(String, nullable=True)
    reviewer_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    resolved_at = Column(DateTime, nullable=True)


class SafetyOverride(Base):
    """Time-bounded override — max 72 hours (ZL-T0-04 §10.1)."""
    __tablename__ = "safety_overrides"

    id = Column(String, primary_key=True, default=lambda: _new_id("ovr-"))
    actor_id = Column(String, nullable=False)
    authority_role = Column(String, nullable=False)
    original_route = Column(String, nullable=False)
    new_route = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=False)
    post_action_review_due = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)


class RefusalTemplateRow(Base):
    """Pre-approved refusal / limitation message template (ZL-T0-04 §9)."""
    __tablename__ = "refusal_templates"

    id = Column(String, primary_key=True, default=lambda: _new_id("tpl-"))
    template_type = Column(String, nullable=False)
    risk_scope = Column(String, nullable=True)
    restricted_sub_class = Column(Enum(RestrictedSubClass), nullable=True)
    mode_scope = Column(String, nullable=True)
    language = Column(String, default="en")
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    safe_alternative = Column(Text, nullable=True)
    approved_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class SafetyEvent(Base):
    """Immutable ledger record of a safety decision (ZL-T0-04 §15)."""
    __tablename__ = "safety_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String, nullable=False)
    query_id = Column(String, nullable=True)
    # The live DB has a NOT NULL tenant_id column added outside this
    # codebase's own migrations (not in _TENANT_SCOPED_TABLES in
    # app/main.py) — this model never declared it, so every insert here
    # silently sent NULL until the DB started enforcing it. Declared now to
    # match the real schema; nullable=True at the model level since not
    # every call site here has a tenant_id available yet (see
    # service.py's _log_safety_event vs. validate_output/
    # resolve_escalation/create_safety_override — those three don't
    # currently have tenant_id in scope and are a separate follow-up).
    tenant_id = Column(String, nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    timestamp = Column(DateTime, default=_utcnow)
    payload_schema_version = Column(String, default="1.0")


class EmergencySafetyBlock(Base):
    """Time-bounded emergency block (max 72 hours) - ZL-T0-04 §14."""
    __tablename__ = "emergency_safety_blocks"

    id = Column(String, primary_key=True, default=lambda: _new_id("blk-"))
    invoker = Column(String, nullable=False)
    approver = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=False)


class RollbackRecord(Base):
    """Audit record of a policy rollback - ZL-T0-04 §14."""
    __tablename__ = "rollback_records"

    id = Column(String, primary_key=True, default=lambda: _new_id("rbk-"))
    from_version = Column(String, nullable=False)
    to_version = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    approver = Column(String, nullable=False)
    impact_scan_ref = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class EscalationRule(Base):
    """Defines queue routing and SLAs - ZL-T0-04 §14."""
    __tablename__ = "escalation_rules"

    id = Column(String, primary_key=True, default=lambda: _new_id("rule-"))
    trigger_condition = Column(String, nullable=False)
    reviewer_role = Column(String, nullable=False)
    sla_hours = Column(Integer, nullable=False, default=24)
    severity = Column(String, nullable=False)
    notification_path = Column(String, nullable=False)


class RestrictedTopicRule(Base):
    """Maps a RESTRICTED sub-class to its refusal and clarification behavior - ZL-T0-04 §14."""
    __tablename__ = "restricted_topic_rules"

    id = Column(String, primary_key=True, default=lambda: _new_id("rtr-"))
    restricted_sub_class = Column(Enum(RestrictedSubClass), nullable=False, unique=True)
    allowed_safe_alternative = Column(Text, nullable=False)
    refusal_template_id = Column(String, nullable=False)
    clarification_permitted = Column(Boolean, nullable=False, default=False)

