"""
Safety Service Orchestrator — enforces governance, overrides, and audit.

Wires together the ML classifier, refusal templates, maker-checker logic,
and exact event payloads per ZL-T0-04 Section 15.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.domains.risk_safety import risk_classifier
from app.domains.risk_safety import refusal_templates
from app.domains.risk_safety import professional_boundary
from app.domains.risk_safety.models import (
    RiskLevel, RestrictedSubClass, Route,
    EscalationCase, EscalationStatus, SafetyOverride, SafetyEvent,
    _new_id, _utcnow,
)
from app.domains.risk_safety.schemas import SafetyDecision, ClassifyRequest


_SLA_HOURS = {
    RiskLevel.HIGH.value: 4,
    RiskLevel.RESTRICTED.value: 2,
    RiskLevel.MEDIUM.value: 24,
}

_REVIEWER_ROLES = {
    RestrictedSubClass.ACADEMIC_INTEGRITY.value: "Learning Lead",
    RestrictedSubClass.ADVICE_INSUFFICIENT_CONTEXT.value: "SME Reviewer",
    RestrictedSubClass.SOURCE_PROHIBITED.value: "Source Admin",
    RestrictedSubClass.CONTROL_BYPASS.value: "Security Lead",
}


def evaluate(request: ClassifyRequest, db: Optional[Session] = None) -> SafetyDecision:
    """Classify query, enrich with templates, create escalations, and log strictly."""
    result = risk_classifier.classify(
        query=request.query,
        jurisdiction=request.jurisdiction,
        mode=request.mode,
        tenant_id=request.tenant_id,
        source_confidence=request.source_confidence,
        pre_bundle_state=request.pre_bundle_state,
        privacy_class=request.privacy_class,
        tenant_policy_conflict=request.tenant_policy_conflict,
        tool_required=request.tool_required,
    )

    query_id = result["query_id"]
    refusal_text: Optional[str] = None
    safe_alternative: Optional[str] = None

    # Step 2 — Refusals & Limitations
    if not result["allowed"]:
        sub_class = result.get("restricted_sub_class")
        
        # Determine exact template
        if "l0-privacy-block" in result["rules_applied"]:
            template_key = "PRIVACY_SECURITY"
        elif "l0-license-blocked" in result["rules_applied"]:
            template_key = RestrictedSubClass.SOURCE_PROHIBITED.value
        elif "l0-ontology-unresolved" in result["rules_applied"]:
            template_key = "ONTOLOGY_UNRESOLVED"
        elif "l2-classification-uncertain" in result["rules_applied"]:
            template_key = "CLASSIFICATION_UNCERTAIN"
        else:
            template_key = sub_class or "SAFETY_DEGRADED"
            
        template = refusal_templates.get_template(template_key)
        refusal_text = f"**{template.title}**\n\n{template.body}"
        safe_alternative = template.safe_alternative

    # Step 3 — Escalation & Ledger
    if db is not None:
        _log_safety_event(db, request, result, template.template_id if not result["allowed"] else None)

        if result["requires_human_review"] or (
            result["risk_level"] == RiskLevel.HIGH.value and result["allowed"]
        ):
            _create_escalation(db, request, result)

        if not result["allowed"] and result.get("restricted_sub_class") == RestrictedSubClass.CONTROL_BYPASS.value:
            _log_security_incident(db, request, result)

    return SafetyDecision(
        allowed=result["allowed"],
        risk_level=result["risk_level"],
        restricted_sub_class=result.get("restricted_sub_class"),
        route=result["route"],
        confidence=result["confidence"],
        requires_sources=result.get("requires_sources", False),
        requires_human_review=result.get("requires_human_review", False),
        requires_citation=result.get("requires_citation", False),
        requires_professional_boundary=result.get("requires_professional_boundary", False),
        limitations=result.get("limitations", []),
        refusal_text=refusal_text,
        safe_alternative=safe_alternative,
        rules_applied=result.get("rules_applied", []),
        query_id=query_id,
    )


def validate_output(text: str, db: Optional[Session] = None, answer_id: str = "ans-sim") -> dict:
    is_safe, violations = professional_boundary.validate(text)

    violation_dicts = [{"phrase": v.phrase_matched, "category": v.category, "severity": v.severity} for v in violations]
    has_soft = any(v.severity == "soft" for v in violations)
    has_hard = any(v.severity == "hard" for v in violations)

    if is_safe and has_soft:
        cleaned = professional_boundary.append_boundary_notice(text)
        if db:
            db.add(SafetyEvent(
                event_type="professional_boundary_notice_applied",
                payload={
                    "answer_id": answer_id,
                    "boundary_type": "soft",
                    "template_id": "tpl-boundary-001",
                    "sufficient_context_conditions_met": True
                }
            ))
            db.commit()
    elif is_safe:
        cleaned = text
    else:
        cleaned = ""
        if db:
            db.add(SafetyEvent(
                event_type="unsafe_output_blocked",
                payload={
                    "answer_id": answer_id,
                    "validator_id": "prof_boundary_v1",
                    "failure_type": "hard_violation",
                    "route": Route.REFUSAL.value
                }
            ))
            db.commit()

    return {"is_safe": is_safe, "violations": violation_dicts, "cleaned_text": cleaned}


def get_escalations(db: Session, status: Optional[str] = None) -> list[EscalationCase]:
    query = db.query(EscalationCase).order_by(EscalationCase.created_at.desc())
    if status:
        query = query.filter(EscalationCase.status == status)
    return query.all()


def resolve_escalation(
    db: Session,
    case_id: str,
    action: str,
    reviewer_id: str,
    reason: str = "",
) -> Optional[EscalationCase]:
    case = db.query(EscalationCase).filter(EscalationCase.id == case_id).first()
    if not case:
        return None

    # Maker-Checker (Section 10.2): reviewer cannot be author
    # We mock query_author here. In a real app, case.author_id exists.
    mock_author_id = "user_123"
    if reviewer_id == mock_author_id:
        db.add(SafetyEvent(
            event_type="maker_checker_violation_blocked",
            payload={
                "object_type": "escalation_case",
                "object_id": case_id,
                "actor_id": reviewer_id,
                "workflow_context": "QUERY_REVIEW"
            }
        ))
        db.commit()
        raise ValueError("Maker-Checker violation: Reviewer authored this query.")

    status_map = {
        "approve": EscalationStatus.RESOLVED,
        "refuse": EscalationStatus.REFUSED,
        "escalate": EscalationStatus.ESCALATED,
        "request_info": EscalationStatus.UNDER_REVIEW,
    }

    case.status = status_map.get(action, EscalationStatus.UNDER_REVIEW)
    case.reviewer_decision = action
    case.reviewer_id = reviewer_id
    case.detail = f"{case.detail or ''}\n\n[Reviewer {reviewer_id}]: {reason}" if reason else case.detail
    case.resolved_at = _utcnow() if action in ("approve", "refuse") else None

    # Audit Ledger Event (Section 15)
    db.add(SafetyEvent(
        event_type="human_review_decision_recorded",
        query_id=case.query_id,
        payload={
            "case_id": case_id,
            "reviewer_id": reviewer_id,
            "decision": action,
            "reason": reason,
            "answer_id": "none",
        },
    ))

    db.commit()
    db.refresh(case)
    return case


def _create_escalation(db: Session, request: ClassifyRequest, result: dict) -> None:
    risk_level_str = result["risk_level"]
    sla_hours = _SLA_HOURS.get(risk_level_str, 24)
    sub_class = result.get("restricted_sub_class")

    case = EscalationCase(
        id=_new_id("ESC-"),
        query_id=result["query_id"],
        query_text=request.query,
        topic=request.query[:80],
        risk_level=RiskLevel(risk_level_str),
        restricted_sub_class=RestrictedSubClass(sub_class) if sub_class else None,
        jurisdiction=request.jurisdiction or "GLOBAL",
        reviewer_role=_REVIEWER_ROLES.get(sub_class, "SME Reviewer"),
        sla_deadline=_utcnow() + timedelta(hours=sla_hours),
        status=EscalationStatus.PENDING,
        route_reason=", ".join(result.get("rules_applied", [])),
        detail=f"Auto-escalated: {', '.join(result.get('limitations', []))}",
        evidence_refs=[],
    )
    db.add(case)
    
    # Audit Ledger Event (Section 15)
    db.add(SafetyEvent(
        event_type="human_review_case_created",
        query_id=result["query_id"],
        payload={
            "case_id": case.id,
            "tenant_id": request.tenant_id,
            "risk_level": risk_level_str,
            "restricted_sub_class": sub_class,
            "route_reason": case.route_reason,
            "reviewer_role": case.reviewer_role,
            "sla_deadline": case.sla_deadline.isoformat(),
        },
    ))
    db.commit()


def _log_safety_event(db: Session, request: ClassifyRequest, result: dict, template_id: Optional[str] = None) -> None:
    """Exact payloads from Section 15."""
    query_id = result["query_id"]
    
    if "l2-classification-uncertain" in result["rules_applied"]:
        event_type = "risk_classification_uncertain"
        payload = {
            "classifier_version": result.get("classifier_version"),
            "classifier_confidence": result["confidence"],
            "available_context_hash": "hash_placeholder",
            "conservative_path_taken": True
        }
    elif not result["allowed"] and result.get("restricted_sub_class"):
        event_type = "restricted_topic_blocked"
        payload = {
            "restricted_sub_class": result.get("restricted_sub_class"),
            "rule_id": "rtr-auto",
            "refusal_template_id": template_id,
            "clarification_permitted": result["route"] == Route.CLARIFICATION.value,
            "route": result["route"]
        }
    elif not result["allowed"]:
        event_type = "safety_refusal_returned"
        payload = {
            "refusal_template_id": template_id,
            "risk_level": result["risk_level"],
            "restricted_sub_class": result.get("restricted_sub_class"),
            "reason_code": result["rules_applied"][0],
            "safe_alternative_offered": True
        }
    else:
        event_type = "risk_classification_applied"
        payload = {
            "mode": request.mode,
            "risk_level": result["risk_level"],
            "restricted_sub_class": result.get("restricted_sub_class"),
            "classifier_version": result.get("classifier_version"),
            "classifier_confidence": result["confidence"],
            "risk_policy_id": "pol-default-v1",
            "source_bundle_id": request.pre_bundle_state
        }

    db.add(SafetyEvent(
        event_type=event_type,
        query_id=query_id,
        payload=payload,
    ))
    db.commit()


def _log_security_incident(db: Session, request: ClassifyRequest, result: dict) -> None:
    db.add(SafetyEvent(
        event_type="security_incident_created",
        query_id=result["query_id"],
        payload={
            "user_id": request.user_id,
            "tenant_id": request.tenant_id,
            "risk_level": result["risk_level"],
            "note": "Control bypass or privacy violation detected.",
        },
    ))
    db.commit()
