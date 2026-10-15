"""Escalation Queue: exceptions that need an accountable expert decision.

One question can open two cases: the safety classifier's escalation (this
queue, with its SLA) and the answer's review case (Review Tasks). They are
the same work, so they are linked by query: the answer is decided once, in
Review Tasks, and that decision closes the escalation here. An escalation with
an open review case cannot be approved or refused on its own, so the two can
never disagree. Escalations with no review case (manual ones, support-ticket
escalations, allowed high-risk answers) are decided here.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User
from app.domains.identity.permissions import permissions_for_role
from app.domains.risk_safety.models import EscalationCase, EscalationStatus, RiskLevel, SafetyEvent, SafetyOverride
from app.orchestration.models import ReviewCase

OPEN_REVIEW = ("open", "triaged", "needs_evidence")
CLOSED = (EscalationStatus.RESOLVED, EscalationStatus.REFUSED)
SLA_HOURS = {"RESTRICTED": 2, "HIGH": 4, "MEDIUM": 24, "LOW": 72}
SEVERITY = {"RESTRICTED": "Critical", "HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}
STATUS = {"PENDING": "open", "UNDER_REVIEW": "expert_review", "ESCALATED": "escalated",
          "RESOLVED": "resolved", "REFUSED": "refused"}


class EscalationError(ValueError):
    """An action the escalation rules refuse."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _naive_now() -> datetime:
    """escalation_cases and safety_events store naive UTC (DateTime without
    time zone); the async driver refuses an aware value for those columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _aware(v: datetime | None) -> datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=timezone.utc))


def _iso(v: datetime | None) -> str | None:
    v = _aware(v)
    return v.isoformat() if v else None


def _val(e) -> str:
    return e.value if hasattr(e, "value") else str(e)


def sla_state(case: EscalationCase, now: datetime) -> str:
    if case.status in CLOSED:
        return "closed"
    due = _aware(case.sla_deadline)
    if due is None:
        return "none"
    if due < now:
        return "overdue"
    if due.date() == now.date():
        return "due_today"
    if due.date() == (now + timedelta(days=1)).date():
        return "due_tomorrow"
    return "within"


async def _linked_reviews(db: AsyncSession, tenant_id: str, query_ids: set[str]) -> dict[str, ReviewCase]:
    if not query_ids:
        return {}
    rows = (await db.execute(select(ReviewCase).where(
        ReviewCase.tenant_id == tenant_id, ReviewCase.query_id.in_(query_ids)).order_by(ReviewCase.created_at))).scalars().all()
    return {r.query_id: r for r in rows}


def _history(case: EscalationCase) -> list[dict]:
    return list(case.history or [])


def _entry(action: str, actor: User | None, note: str = "") -> dict:
    return {"at": _now().isoformat(), "action": action, "actorId": actor.id if actor else None,
            "actor": (actor.full_name or actor.email) if actor else "System", "note": note}


def _view(c: EscalationCase, review: ReviewCase | None, names: dict[str, str], now: datetime) -> dict:
    risk = _val(c.risk_level)
    review_open = bool(review and review.status in OPEN_REVIEW)
    closed = c.status in CLOSED
    critical = risk == "RESTRICTED"
    steps = []
    if not closed:
        if not c.assigned_to:
            steps.append("Assign expert")
        steps.append("Confirm evidence")
        steps.append("Decide answer in Review Tasks" if review_open else "Independent decision")
        steps.append("Audit closure")
    return {
        "id": c.id, "queryId": c.query_id, "question": c.query_text, "topic": c.topic,
        "severity": SEVERITY.get(risk, risk.title()), "riskLevel": risk,
        "subClass": _val(c.restricted_sub_class) if c.restricted_sub_class else None,
        "trigger": (_val(c.restricted_sub_class).replace("_", " ").title() if c.restricted_sub_class
                    else "Manual escalation" if (c.origin or "auto") != "auto" else "Risk classification"),
        "jurisdiction": c.jurisdiction, "status": STATUS.get(_val(c.status), _val(c.status).lower()),
        "rawStatus": _val(c.status), "origin": c.origin or "auto",
        "requesterId": c.owner, "requester": names.get(c.owner or "", None),
        "assigneeId": c.assigned_to, "assignee": names.get(c.assigned_to or ""),
        "reviewerRole": c.reviewer_role, "decidedBy": names.get(c.reviewer_id or "", c.reviewer_id),
        "decision": c.reviewer_decision, "slaDeadline": _iso(c.sla_deadline), "sla": sla_state(c, now),
        "createdAt": _iso(c.created_at), "resolvedAt": _iso(c.resolved_at), "detail": c.detail or "",
        "routeReason": c.route_reason or "", "evidenceRefs": c.evidence_refs or [],
        "reviewCase": ({"id": review.id, "status": review.status, "decision": review.reviewer_decision,
                        "source": review.source} if review else None),
        "closureRestricted": not closed and (review_open or critical),
        "closureReason": ("The answer is decided in Review Tasks; this escalation closes with that decision" if review_open
                          else "Critical: a reviewer independent of the assigned expert signs off" if critical and not closed
                          else ""),
        "nextSteps": steps, "history": _history(c),
    }


async def _names(db: AsyncSession, tenant_id: str) -> dict[str, str]:
    return {u.id: u.full_name or u.email for u in (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars()}


async def queue(db: AsyncSession, tenant_id: str, *, limit: int = 300) -> dict:
    now = _now()
    cases = (await db.execute(select(EscalationCase).where(EscalationCase.tenant_id == tenant_id)
                              .order_by(EscalationCase.created_at.desc()).limit(limit))).scalars().all()
    reviews = await _linked_reviews(db, tenant_id, {c.query_id for c in cases})
    names = await _names(db, tenant_id)
    views = [_view(c, reviews.get(c.query_id), names, now) for c in cases]
    open_ = [v for v in views if v["status"] not in ("resolved", "refused")]
    overrides = (await db.execute(select(SafetyOverride).where(
        SafetyOverride.tenant_id == tenant_id, SafetyOverride.is_active.is_(True),
        SafetyOverride.expires_at > now.replace(tzinfo=None)))).scalars().all()
    severities = Counter(v["severity"] for v in open_)
    return {
        "escalations": views,
        "summary": {
            "open": len(open_), "critical": severities.get("Critical", 0),
            "overdue": sum(v["sla"] == "overdue" for v in open_),
            "expertReview": sum(v["status"] == "expert_review" for v in open_),
            "closureRestricted": sum(v["closureRestricted"] for v in open_),
            "unassigned": sum(not v["assigneeId"] for v in open_),
            "linkedToReview": sum(bool(v["reviewCase"]) for v in open_),
            "bySeverity": {k: severities.get(k, 0) for k in ("Critical", "High", "Medium", "Low")},
        },
        "overrides": [{"id": o.id, "scope": o.scope, "reason": o.reason, "originalRoute": o.original_route,
                       "newRoute": o.new_route, "actor": names.get(o.actor_id, o.actor_id), "role": o.authority_role,
                       "expiresAt": _iso(o.expires_at)} for o in overrides],
        "generatedAt": now.isoformat(),
    }


async def _get(db: AsyncSession, tenant_id: str, case_id: str) -> EscalationCase:
    case = (await db.execute(select(EscalationCase).where(
        EscalationCase.id == case_id, EscalationCase.tenant_id == tenant_id))).scalar_one_or_none()
    if case is None:
        raise LookupError("Escalation not found")
    return case


async def _audit(db: AsyncSession, actor: User, event: str, case: EscalationCase, payload: dict) -> None:
    await record_event_async(db, tenant_id=actor.tenant_id, event_name=event, emitting_service="review_console",
                             actor_id=actor.id, subject_type="escalation_case", subject_id=case.id,
                             correlation_id=case.query_id, payload=payload)


def _is_expert(user: User) -> bool:
    perms = permissions_for_role(user.role)
    return bool(perms & {"safety.manage", "review.resolve"})


async def act(db: AsyncSession, actor: User, case_id: str, action: str, *, note: str = "",
              assignee_id: str | None = None) -> EscalationCase:
    case = await _get(db, actor.tenant_id, case_id)
    note = note.strip()
    if case.status in CLOSED and action not in {"note"}:
        raise EscalationError("This escalation is closed")
    review = (await _linked_reviews(db, actor.tenant_id, {case.query_id})).get(case.query_id)
    payload: dict = {"note": note}

    if action == "assign":
        person = (await db.execute(select(User).where(
            User.id == (assignee_id or ""), User.tenant_id == actor.tenant_id, User.is_active.is_(True)))).scalar_one_or_none()
        if person is None:
            raise EscalationError("Choose an active person in this workspace")
        if not _is_expert(person):
            raise EscalationError(f"{person.full_name or person.email} ({person.role}) cannot decide escalations")
        case.assigned_to = person.id
        payload["assignee"] = person.id
    elif action == "start_review":
        case.status = EscalationStatus.UNDER_REVIEW
        case.assigned_to = case.assigned_to or actor.id
    elif action == "request_info":
        if not note:
            raise EscalationError("Say what information is needed")
        case.status = EscalationStatus.UNDER_REVIEW
    elif action == "escalate":
        if not note:
            raise EscalationError("Record why it is escalated")
        case.status = EscalationStatus.ESCALATED
    elif action == "note":
        if not note:
            raise EscalationError("Write a note")
    elif action in {"approve", "refuse"}:
        if review is not None and review.status in OPEN_REVIEW:
            raise EscalationError("Decide the answer in Review Tasks; that decision closes this escalation")
        if case.owner and case.owner == actor.id:
            raise EscalationError("You raised this escalation; someone else must decide it")
        if _val(case.risk_level) == RiskLevel.RESTRICTED.value and case.assigned_to == actor.id:
            raise EscalationError("Critical escalations need sign-off independent of the assigned expert")
        if action == "refuse" and not note:
            raise EscalationError("Record the reason for refusing")
        case.status = EscalationStatus.RESOLVED if action == "approve" else EscalationStatus.REFUSED
        case.reviewer_decision, case.reviewer_id, case.resolved_at = action, actor.id, _naive_now()
        db.add(SafetyEvent(tenant_id=actor.tenant_id, event_type="human_review_decision_recorded", query_id=case.query_id,
                           timestamp=_naive_now(),
                           payload={"case_id": case.id, "reviewer_id": actor.id, "decision": action, "reason": note,
                                    "answer_id": "none"}))
    else:
        raise EscalationError("Unknown action")
    case.history = [*_history(case), _entry(action, actor, note)]
    await db.flush()
    await _audit(db, actor, f"escalation_{action}", case, payload)
    return case


async def create(db: AsyncSession, actor: User, *, topic: str, detail: str, risk_level: str, jurisdiction: str,
                 query_id: str | None = None, origin: str = "manual", query_text: str = "") -> EscalationCase:
    if risk_level not in SEVERITY:
        raise EscalationError("Unknown severity")
    count = (await db.execute(select(func.count()).select_from(EscalationCase)
                              .where(EscalationCase.tenant_id == actor.tenant_id))).scalar_one()
    case_id = f"ESC-{_now().year}-{count + 1:04d}"
    while (await db.get(EscalationCase, case_id)) is not None:
        count += 1
        case_id = f"ESC-{_now().year}-{count + 1:04d}"
    case = EscalationCase(
        id=case_id, tenant_id=actor.tenant_id, query_id=query_id or f"manual:{case_id}", query_text=query_text or topic,
        topic=topic[:200], risk_level=RiskLevel(risk_level), jurisdiction=jurisdiction or "GLOBAL", owner=actor.id,
        reviewer_role="SME Reviewer", sla_deadline=_naive_now() + timedelta(hours=SLA_HOURS[risk_level]), created_at=_naive_now(),
        status=EscalationStatus.PENDING, route_reason=origin, detail=detail, evidence_refs=[],
        origin=origin, created_by=actor.id, history=[_entry("raised", actor, detail)],
    )
    db.add(case)
    await db.flush()
    await _audit(db, actor, "escalation_raised", case, {"severity": risk_level, "origin": origin})
    return case


async def sync_from_review(db: AsyncSession, case: ReviewCase) -> int:
    """Close (or move) the escalations of the same question when its review
    case is decided in Review Tasks. Returns how many were updated."""
    rows = (await db.execute(select(EscalationCase).where(
        EscalationCase.tenant_id == case.tenant_id, EscalationCase.query_id == case.query_id,
        EscalationCase.status.notin_(CLOSED)))).scalars().all()
    if not rows:
        return 0
    decision = case.reviewer_decision or ""
    for esc in rows:
        if decision == "needs_evidence":
            esc.status = EscalationStatus.UNDER_REVIEW
        else:
            esc.status = EscalationStatus.REFUSED if decision == "rejected" else EscalationStatus.RESOLVED
            esc.resolved_at = _naive_now()
        esc.reviewer_decision = f"review:{decision}"
        esc.reviewer_id = case.reviewer_id
        esc.history = [*_history(esc), {"at": _now().isoformat(), "action": f"review_{decision}", "actorId": case.reviewer_id,
                                        "actor": "Review Tasks", "note": f"Answer {decision} in review case {case.id[:8]}"}]
    await db.commit()
    return len(rows)
