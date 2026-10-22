"""
Read-only views behind the AI Governance pages (AI Safety Dashboard, Risk
Policy, Professional Boundaries).

Everything here is computed from the tenant's own safety ledger and the rule
objects the classifier and boundary validator actually execute, so the pages
show what Kriton is doing rather than a copy of the spec that can drift.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.risk_safety import refusal_templates
from app.domains.risk_safety import risk_classifier
from app.domains.risk_safety.models import (
    EscalationCase,
    EscalationRule,
    EscalationStatus,
    RestrictedTopicRule,
    RiskPolicy,
    SafetyEvent,
    SafetyOverride,
)
from app.domains.risk_safety.routing_matrix import ROUTING_MATRIX, ROUTING_MATRIX_VERSION
from app.domains.risk_safety import service as safety_service

TREND_DAYS = 14
RISK_LEVEL_WINDOW_DAYS = 30


def _now() -> datetime:
    # SafetyEvent.timestamp is a naive UTC column.
    return datetime.now(timezone.utc).replace(tzinfo=None)


_CLASSIFIED = ("risk_classification_applied", "risk_classification_uncertain")
_BLOCKED = ("restricted_topic_blocked", "safety_refusal_returned", "unsafe_output_blocked")
_RESTRICTED = ("restricted_topic_blocked", "security_incident_created")


def _event_type_counts(db: Session, tenant_id: str, since_7d: datetime) -> tuple[dict, dict, datetime | None]:
    """All-time and last-7-day counts per event type, plus the latest event
    time, in one round trip (the pooler adds ~0.8s per query)."""
    rows = (
        db.query(
            SafetyEvent.event_type,
            func.count(),
            func.count().filter(SafetyEvent.timestamp >= since_7d),
            func.max(SafetyEvent.timestamp),
        )
        .filter(SafetyEvent.tenant_id == tenant_id)
        .group_by(SafetyEvent.event_type)
        .all()
    )
    all_time = {event_type: total for event_type, total, _, _ in rows}
    last_7d = {event_type: recent for event_type, _, recent, _ in rows if recent}
    latest = max((last for *_, last in rows if last is not None), default=None)
    return all_time, last_7d, latest


def _risk_level_counts(db: Session, tenant_id: str, since: datetime | None = None) -> dict[str, int]:
    level = SafetyEvent.payload["risk_level"].as_string()
    query = (
        db.query(SafetyEvent.event_type, level, func.count())
        .filter(
            SafetyEvent.tenant_id == tenant_id,
            SafetyEvent.event_type.in_(("risk_classification_applied", *_RESTRICTED)),
        )
    )
    if since is not None:
        query = query.filter(SafetyEvent.timestamp >= since)
    counts: dict[str, int] = {}
    for event_type, key, count in query.group_by(SafetyEvent.event_type, level).all():
        # Blocks are logged under their own event types, so a RESTRICTED
        # query never appears as risk_classification_applied.
        key = "RESTRICTED" if event_type in _RESTRICTED else key
        if key:
            counts[key] = counts.get(key, 0) + count
    return counts


def _daily_trend(db: Session, tenant_id: str, days: int) -> list[dict]:
    today = _now().date()
    start = today - timedelta(days=days - 1)
    day = func.date(SafetyEvent.timestamp)
    rows = (
        db.query(day, SafetyEvent.event_type, func.count())
        .filter(SafetyEvent.tenant_id == tenant_id, SafetyEvent.timestamp >= datetime.combine(start, datetime.min.time()))
        .group_by(day, SafetyEvent.event_type)
        .all()
    )
    buckets: dict[str, dict] = {}
    for offset in range(days):
        key = (start + timedelta(days=offset)).isoformat()
        buckets[key] = {"date": key, "classified": 0, "blocked": 0, "review": 0, "other": 0}
    for raw_day, event_type, count in rows:
        key = raw_day.isoformat() if hasattr(raw_day, "isoformat") else str(raw_day)[:10]
        bucket = buckets.get(key)
        if bucket is None:
            continue
        if event_type in _CLASSIFIED:
            bucket["classified"] += count
        elif event_type in (*_BLOCKED, "security_incident_created"):
            bucket["blocked"] += count
        elif event_type in ("human_review_case_created", "human_review_decision_recorded"):
            bucket["review"] += count
        else:
            bucket["other"] += count
    return list(buckets.values())


_OUTCOME_EVENTS = {
    "response_returned": "answered",
    "refusal_returned": "refused",
    "clarification_returned": "clarified",
    "composition_rejected": "rejected_by_validator",
    "human_review_created": "sent_to_review",
    "security_incident_recorded": "security_incidents",
}


def _answer_outcomes(db: Session, tenant_id: str, since_7d: datetime) -> tuple[dict[str, int], dict[str, int]]:
    """How Ask Kriton requests ended (all time, last 7 days), from the audit ledger."""
    from app.domains.audit_ledger.models import AuditEvent

    rows = (
        db.query(
            AuditEvent.event_name,
            func.count(),
            func.count().filter(AuditEvent.event_time >= since_7d.replace(tzinfo=timezone.utc)),
        )
        .filter(AuditEvent.tenant_id == tenant_id, AuditEvent.event_name.in_(tuple(_OUTCOME_EVENTS)))
        .group_by(AuditEvent.event_name)
        .all()
    )
    totals = {name: (total, recent) for name, total, recent in rows}
    all_time = {label: totals.get(name, (0, 0))[0] for name, label in _OUTCOME_EVENTS.items()}
    last_7d = {label: totals.get(name, (0, 0))[1] for name, label in _OUTCOME_EVENTS.items()}
    return all_time, last_7d


def _escalation_stats(db: Session, tenant_id: str, now: datetime) -> dict[str, int]:
    """Same numbers as service.get_escalation_stats, in one query."""
    open_statuses = (EscalationStatus.RESOLVED, EscalationStatus.REFUSED)
    rows = (
        db.query(
            EscalationCase.status,
            func.count(),
            func.count().filter(EscalationCase.sla_deadline < now, EscalationCase.status.notin_(open_statuses)),
        )
        .filter(EscalationCase.tenant_id == tenant_id)
        .group_by(EscalationCase.status)
        .all()
    )
    by_status = {(status.value if hasattr(status, "value") else str(status)): count for status, count, _ in rows}
    return {
        "total": sum(by_status.values()),
        "pending": by_status.get("PENDING", 0),
        "under_review": by_status.get("UNDER_REVIEW", 0),
        "resolved": by_status.get("RESOLVED", 0),
        "refused": by_status.get("REFUSED", 0),
        "escalated": by_status.get("ESCALATED", 0),
        "over_sla": sum(overdue for _, _, overdue in rows),
    }


def safety_summary(db: Session, *, tenant_id: str) -> dict:
    """Totals for the AI Safety Dashboard, over the tenant's whole ledger."""
    now = _now()
    since_7d = now - timedelta(days=7)
    all_time, last_7d, last_event = _event_type_counts(db, tenant_id, since_7d)
    outcomes, outcomes_7d = _answer_outcomes(db, tenant_id, since_7d)
    active_overrides = (
        db.query(func.count())
        .filter(
            SafetyOverride.tenant_id == tenant_id,
            SafetyOverride.is_active.is_(True),
            SafetyOverride.expires_at > now,
        )
        .scalar()
    )

    def total(counts: dict[str, int], *names: str) -> int:
        return sum(counts.get(name, 0) for name in names)

    return {
        "generated_at": now.isoformat() + "Z",
        "last_event_at": last_event.isoformat() + "Z" if last_event else None,
        "totals": {
            "events": sum(all_time.values()),
            "classified": total(all_time, *_CLASSIFIED),
            "uncertain": total(all_time, "risk_classification_uncertain"),
            "blocked": total(all_time, *_BLOCKED),
            # The answer pipeline records incidents in the audit ledger;
            # the safety ledger only has the ones raised by /safety/classify.
            "incidents": total(all_time, "security_incident_created") + outcomes["security_incidents"],
            "review_cases": total(all_time, "human_review_case_created"),
            "review_decisions": total(all_time, "human_review_decision_recorded"),
        },
        "last_7_days": {
            "events": sum(last_7d.values()),
            "classified": total(last_7d, *_CLASSIFIED),
            "blocked": total(last_7d, *_BLOCKED),
            "incidents": total(last_7d, "security_incident_created") + outcomes_7d["security_incidents"],
        },
        "answer_outcomes": outcomes,
        "answer_outcomes_7d": outcomes_7d,
        "by_event_type": dict(sorted(all_time.items(), key=lambda item: -item[1])),
        "risk_levels": _risk_level_counts(db, tenant_id),
        "trend": _daily_trend(db, tenant_id, TREND_DAYS),
        "escalations": _escalation_stats(db, tenant_id, now),
        "active_overrides": active_overrides or 0,
    }


def _rule_view(rule) -> dict:
    return {
        "allowed": rule.allowed,
        "route": rule.route.value,
        "requires_sources": rule.requires_sources,
        "requires_citation": rule.requires_citation,
        "requires_professional_boundary": rule.requires_professional_boundary,
        "limitation": rule.limitation,
    }


def _pattern_list(patterns) -> list[str]:
    return [pattern.pattern for pattern in patterns]


# How each RESTRICTED sub-class is routed by risk_classifier.pre_screen and the
# security-incident path in service._finalize. Route and reviewer come from
# the code below; only the one-line descriptions are written here.
_SUBCLASS_DESCRIPTIONS = {
    "RESTRICTED_ACADEMIC_INTEGRITY": "Live exam or assessment answers. Blocked; a concept explanation or study guidance is offered instead.",
    "RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT": "Advice about the user's own company or filing with no jurisdiction. Kriton asks for the missing context, then reclassifies.",
    "RESTRICTED_SOURCE_PROHIBITED": "The only eligible sources are licence-blocked. Routed to the licence path: metadata only, internal summary, or human review.",
    "RESTRICTED_CONTROL_BYPASS": "Prompt injection, jailbreak or a privacy violation. Logged as a security incident; detection details are not revealed.",
}

_SUBCLASS_ROUTES = {
    "RESTRICTED_ACADEMIC_INTEGRITY": ("REFUSAL", False, _pattern_list(risk_classifier._ACADEMIC_PATTERNS)),
    "RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT": ("CLARIFICATION", True, _pattern_list(risk_classifier._ADVICE_SIGNALS)),
    "RESTRICTED_SOURCE_PROHIBITED": ("LICENSE_PATH", False, []),
    "RESTRICTED_CONTROL_BYPASS": ("SECURITY_INCIDENT", False, _pattern_list(risk_classifier._BYPASS_PATTERNS)),
}


def policy_view(db: Session, *, tenant_id: str) -> dict:
    """The risk policy as it is enforced: policy row, routing matrix, SLAs,
    escalation rules, RESTRICTED sub-class routing and recent usage."""
    policy = db.query(RiskPolicy).order_by(RiskPolicy.effective_from.desc(), RiskPolicy.created_at.desc()).first()
    since = _now() - timedelta(days=RISK_LEVEL_WINDOW_DAYS)

    subclass = SafetyEvent.payload["restricted_sub_class"].as_string()
    subclass_counts = {
        key: count
        for key, count in db.query(subclass, func.count())
        .filter(
            SafetyEvent.tenant_id == tenant_id,
            SafetyEvent.event_type.in_(("restricted_topic_blocked", "safety_refusal_returned", "security_incident_created")),
        )
        .group_by(subclass)
        .all()
        if key
    }
    open_cases = {
        level.value if hasattr(level, "value") else str(level): count
        for level, count in db.query(EscalationCase.risk_level, func.count())
        .filter(
            EscalationCase.tenant_id == tenant_id,
            EscalationCase.status.in_((EscalationStatus.PENDING, EscalationStatus.UNDER_REVIEW)),
        )
        .group_by(EscalationCase.risk_level)
        .all()
    }
    topic_rules = {
        (row.restricted_sub_class.value if hasattr(row.restricted_sub_class, "value") else str(row.restricted_sub_class)): row
        for row in db.query(RestrictedTopicRule).all()
    }
    templates_by_subclass: dict[str, list[str]] = {}
    for template in refusal_templates.get_all_templates():
        if template.get("restricted_sub_class"):
            templates_by_subclass.setdefault(template["restricted_sub_class"], []).append(template["template_id"])

    subclasses = []
    for code, (route, clarification, patterns) in _SUBCLASS_ROUTES.items():
        stored = topic_rules.get(code)
        subclasses.append({
            "code": code,
            "description": _SUBCLASS_DESCRIPTIONS[code],
            "route": route,
            "clarification_permitted": stored.clarification_permitted if stored else clarification,
            "reviewer_role": safety_service._REVIEWER_ROLES.get(code),
            "patterns": patterns,
            "refusal_templates": templates_by_subclass.get(code, []),
            "blocked_count": subclass_counts.get(code, 0),
        })

    matrix: dict[str, dict[str, dict]] = {}
    for (level, confidence), rule in ROUTING_MATRIX.items():
        matrix.setdefault(level, {})[confidence] = _rule_view(rule)

    return {
        "policy": {
            "id": policy.id,
            "version": policy.version,
            "scope": policy.scope,
            "owner": policy.owner,
            "approver": policy.approver,
            "effective_from": policy.effective_from.isoformat() + "Z" if policy.effective_from else None,
            "rollback_target": policy.rollback_target,
            "rules": policy.rules or [],
        } if policy else None,
        "classifier_version": risk_classifier.CLASSIFIER_VERSION,
        "routing_matrix_version": ROUTING_MATRIX_VERSION,
        "routing_matrix": matrix,
        "sla_hours": dict(safety_service._SLA_HOURS),
        "escalation_rules": [
            {
                "id": rule.id,
                "trigger_condition": rule.trigger_condition,
                "reviewer_role": rule.reviewer_role,
                "sla_hours": rule.sla_hours,
                "severity": rule.severity,
                "notification_path": rule.notification_path,
            }
            for rule in db.query(EscalationRule).order_by(EscalationRule.sla_hours).all()
        ],
        "restricted_subclasses": subclasses,
        "risk_level_window_days": RISK_LEVEL_WINDOW_DAYS,
        "risk_levels": _risk_level_counts(db, tenant_id, since),
        "open_cases_by_risk": open_cases,
    }


# ─── Professional boundaries ────────────────────────────────────────────────
#
# Ask Kriton answers are checked by massarius.answer_validator (Checkpoint C)
# and certification requests are refused by orchestration.professional_boundary.
# Both write to the audit ledger (composition_rejected / refusal_returned), so
# that is where the live counts come from.

# Failure-message prefix → (category id, label). Prefixes are the exact text
# answer_validator.validate_answer_or_raise() and the claim verifier write.
_FAILURE_CATEGORIES = [
    ("Prohibited-claim detected", "prohibited_claim", "Professional-advice wording"),
    ("Authority ceiling exceeded", "authority_ceiling", "Over-authoritative wording"),
    ("Confidence support failed", "confidence_support", "Unhedged certainty"),
    ("Citation binding failed", "citation_binding", "Citation not bound to a source"),
    ("Grounding check failed", "grounding", "No sources behind the answer"),
    ("Licence exposure detected", "licence_exposure", "Restricted source exposed"),
    ("Disclaimer presence check failed", "disclaimer", "Disclaimer missing"),
    ("A factual claim lacks a valid citation", "claim_citation", "Claim without citation"),
    ("Answer contains contradicted or unsupported claims", "claim_support", "Unsupported or contradicted claim"),
    ("Claim verification unavailable", "claim_verification_unavailable", "Claim check unavailable"),
]

CERTIFICATION_REASON = "Professional tax certification requested"
PROHIBITED_REFUSAL_REASON = "Composition rejected: prohibited claim detected"


def _failure_category(failure: str) -> tuple[str, str] | None:
    for prefix, key, label in _FAILURE_CATEGORIES:
        if failure.startswith(prefix):
            return key, label
    # "Rejected: <claim>" lines list the claims behind the previous failure;
    # they are detail, not a separate check.
    return None


def boundary_rules() -> list[dict]:
    from app.domains.massarius import answer_validator as validator

    def bank(patterns, check: str, applies: str, outcome: str) -> list[dict]:
        return [
            {"check": check, "pattern": getattr(pattern, "pattern", pattern), "applies": applies, "outcome": outcome}
            for pattern in patterns
        ]

    return [
        *bank([validator._DIRECTIVE], "Directive wording", "High-risk questions about the asker's own matter",
              "Restated once as general guidance; refused if it persists"),
        *bank(validator._PROHIBITED, "Prohibited professional claim", "Every answer",
              "Refused unless the cited source itself says it"),
        *bank(validator._AUTHORITY_OVERREACH, "Authority ceiling", "Answers without a primary source",
              "Sent to human review"),
        *bank(validator._UNHEDGED_CERTAINTY, "Unhedged certainty",
              "Answers whose sources are limited, insufficient, conflicting or stale", "Sent to human review"),
    ]


def check_answer_text(text: str, *, user_specific: bool, confidence_state: str, authority_level: str) -> dict:
    """Run the live Checkpoint C validator on a draft, with no sources and no
    evidence, so only the wording checks can fire."""
    from app.domains.massarius.answer_validator import validate_answer
    from app.orchestration.professional_boundary import requests_tax_certification
    from app.orchestration.schemas import SourceBundle

    bundle = SourceBundle(
        source_bundle_id="boundary-check",
        authority_level=authority_level,
        confidence_state=confidence_state,
    )
    result = validate_answer(text, bundle, ungrounded_answer_allowed=True, user_specific=user_specific)
    failures = [failure for failure in result.failures if not failure.startswith("Citation binding failed")]
    return {
        "passed": not failures,
        "failures": failures,
        "outcome": "released" if not failures else ("refused" if any("Prohibited" in f for f in failures) else "human_review"),
        "certification_request": requests_tax_certification(text),
    }


def boundary_view(db: Session, *, tenant_id: str) -> dict:
    """The professional-boundary checks Ask Kriton runs, and how often they
    fired for this tenant."""
    from app.domains.audit_ledger.models import AuditEvent

    reason = AuditEvent.payload["reason"].as_string()
    event_counts = dict(
        db.query(AuditEvent.event_name, func.count())
        .filter(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.event_name.in_(("response_returned", "composition_rejected", "refusal_returned")),
        )
        .group_by(AuditEvent.event_name)
        .all()
    )
    refusal_reasons = dict(
        db.query(reason, func.count())
        .filter(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.event_name == "refusal_returned",
            reason.in_((CERTIFICATION_REASON, PROHIBITED_REFUSAL_REASON)),
        )
        .group_by(reason)
        .all()
    )
    rejections = (
        db.query(AuditEvent.event_time, AuditEvent.subject_id, AuditEvent.payload)
        .filter(AuditEvent.tenant_id == tenant_id, AuditEvent.event_name == "composition_rejected")
        .order_by(AuditEvent.event_time.desc())
        .all()
    )

    by_category: dict[str, dict] = {}
    recent = []
    for event_time, subject_id, payload in rejections:
        failures = [str(f) for f in (payload or {}).get("failures", [])]
        categories = []
        for failure in failures:
            category = _failure_category(failure)
            if category and category[0] not in categories:
                categories.append(category[0])
                entry = by_category.setdefault(category[0], {"key": category[0], "label": category[1], "count": 0})
                entry["count"] += 1
        if len(recent) < 15:
            recent.append({
                "query_id": subject_id,
                "time": event_time.isoformat() if event_time else None,
                "route": (payload or {}).get("degraded_route"),
                "categories": [by_category[key]["label"] for key in categories],
                "failures": failures[:3],
            })

    return {
        "validator": "Checkpoint C answer validator",
        "rules": boundary_rules(),
        "counts": {
            "answers_returned": event_counts.get("response_returned", 0),
            "answers_rejected": event_counts.get("composition_rejected", 0),
            "refusals": event_counts.get("refusal_returned", 0),
            "certification_refusals": refusal_reasons.get(CERTIFICATION_REASON, 0),
            "prohibited_claim_refusals": refusal_reasons.get(PROHIBITED_REFUSAL_REASON, 0),
        },
        "rejections_by_check": sorted(by_category.values(), key=lambda item: -item["count"]),
        "recent_rejections": recent,
    }
