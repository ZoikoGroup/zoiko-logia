"""Command Center view model, built from records Kriton already holds.

Each panel reads one authoritative service and is shown only to a role that
may read that service on its own endpoint, so the Command Center never shows
more than the user could open directly:

  reviewQueue     <- review_cases                (review.read)
  attentionItems  <- escalation_cases            (safety.read)
                     security_incidents          (support.read)
                     source licence expiry       (source.read)
  deadlines       <- escalation SLA deadlines    (safety.read)
  activeMatters   <- engagements the user is a member of
  recentWork      <- the user's saved answers and drafts

A panel with no permission is "restricted"; a panel with permission but no
records is "current" and empty. Nothing is invented to fill a panel.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.identity.authorization import list_authorized_engagements
from app.domains.identity.models import User
from app.domains.identity.permissions import REVIEW_READ, SAFETY_READ, SOURCE_READ, SUPPORT_READ, user_has_permission
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.domains.risk_safety.models import EscalationCase, EscalationStatus
from app.domains.source_library.service import get_soonest_expiring
from app.domains.support_incident.models import SecurityIncident
from app.orchestration.models import ReviewCase

PANEL_LIMIT = 5
ATTENTION_LIMIT = 6
DEADLINE_WINDOW_DAYS = 14
LICENCE_WARNING_DAYS = 30

_OPEN_REVIEW = ("open", "needs_evidence")
_OPEN_ESCALATION = (EscalationStatus.PENDING, EscalationStatus.UNDER_REVIEW, EscalationStatus.ESCALATED)
_OPEN_INCIDENT = ("OPEN", "CONTAINED")
_LEVEL_ORDER = {"high": 0, "attention": 1, "info": 2}


def _aware(value: datetime | None) -> datetime | None:
    """Some tables store naive UTC timestamps; compare everything as aware."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


def _short(text: str | None, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _risk_value(risk) -> str:
    return str(getattr(risk, "value", risk) or "").upper()


def _level_for_risk(risk) -> str:
    return "high" if _risk_value(risk) in {"HIGH", "CRITICAL", "RESTRICTED"} else "attention"


async def _review_queue(db: AsyncSession, user: User) -> tuple[list[dict], int]:
    rows = await db.execute(
        select(ReviewCase)
        .where(ReviewCase.tenant_id == user.tenant_id, ReviewCase.status.in_(_OPEN_REVIEW))
        .order_by(ReviewCase.created_at.desc())
        .limit(PANEL_LIMIT)
    )
    total = (await db.execute(
        select(func.count()).select_from(ReviewCase)
        .where(ReviewCase.tenant_id == user.tenant_id, ReviewCase.status.in_(_OPEN_REVIEW))
    )).scalar_one()
    items = [
        {
            "id": case.id,
            "title": _short(case.query_text) or "Review case",
            "riskLevel": _risk_value(case.risk_level),
            "reason": _short(case.reason, 90),
            "source": case.source,
            "status": case.status,
            "createdAt": _iso(case.created_at),
            "href": "/review-tasks",
        }
        for case in rows.scalars()
    ]
    return items, total


async def _escalations(db: AsyncSession, user: User) -> list[EscalationCase]:
    rows = await db.execute(
        select(EscalationCase)
        .where(EscalationCase.tenant_id == user.tenant_id, EscalationCase.status.in_(_OPEN_ESCALATION))
        .order_by(EscalationCase.created_at.desc())
        .limit(50)
    )
    return list(rows.scalars())


async def _open_incidents(db: AsyncSession, user: User) -> list[SecurityIncident]:
    rows = await db.execute(
        select(SecurityIncident)
        .where(SecurityIncident.tenant_id == user.tenant_id, SecurityIncident.containment_status.in_(_OPEN_INCIDENT))
        .order_by(SecurityIncident.opened_at.desc())
        .limit(PANEL_LIMIT)
    )
    return list(rows.scalars())


async def _recent_work(db: AsyncSession, user: User) -> list[dict]:
    answers = await db.execute(
        select(SavedAnswer)
        .where(SavedAnswer.tenant_id == user.tenant_id, SavedAnswer.user_id == user.id)
        .order_by(SavedAnswer.created_at.desc())
        .limit(PANEL_LIMIT)
    )
    drafts = await db.execute(
        select(Draft)
        .where(Draft.tenant_id == user.tenant_id, Draft.user_id == user.id)
        .order_by(Draft.updated_at.desc())
        .limit(PANEL_LIMIT)
    )
    items = [
        {"id": a.id, "kind": "saved_answer", "title": _short(a.query_text, 80) or "Saved answer",
         "subtitle": "Saved Kriton answer", "at": _iso(a.created_at), "href": "/saved-answers"}
        for a in answers.scalars()
    ] + [
        {"id": d.id, "kind": "draft", "title": _short(d.title, 80) or "Untitled draft",
         "subtitle": f"Draft report · {d.status}", "at": _iso(d.updated_at or d.created_at), "href": "/drafts-reports"}
        for d in drafts.scalars()
    ]
    items.sort(key=lambda item: item["at"] or "", reverse=True)
    return items[:PANEL_LIMIT]


async def _active_matters(db: AsyncSession, user: User) -> list[dict]:
    engagements = await list_authorized_engagements(db, actor_id=user.id, tenant_id=user.tenant_id)
    return [
        {"id": e.id, "name": e.name, "status": e.status, "createdAt": _iso(e.created_at), "href": "/workpapers"}
        for e in engagements[:PANEL_LIMIT]
    ]


async def build_command_center(db: AsyncSession, user: User, now: datetime | None = None) -> dict:
    """The panels of the Command Center view model, each with its freshness."""
    now = now or datetime.now(timezone.utc)
    freshness: dict[str, dict] = {}
    restricted = {"state": "restricted", "failedReason": "Your role cannot read this service."}

    review_queue: list[dict] = []
    review_count = 0
    if user_has_permission(user, REVIEW_READ):
        review_queue, review_count = await _review_queue(db, user)
        freshness["reviewQueue"] = {"state": "current"}
    else:
        freshness["reviewQueue"] = dict(restricted)

    attention: list[dict] = []
    deadlines: list[dict] = []
    can_safety = user_has_permission(user, SAFETY_READ)
    if can_safety:
        horizon = now + timedelta(days=DEADLINE_WINDOW_DAYS)
        for case in await _escalations(db, user):
            due = _aware(case.sla_deadline)
            attention.append({
                "id": case.id, "kind": "escalation", "level": _level_for_risk(case.risk_level),
                "title": f"Escalation: {_short(case.topic, 60) or 'review required'}",
                "context": _short(case.query_text, 100), "dueAt": _iso(due),
                "action": "Open escalation", "href": "/escalation-queue",
            })
            if due and due <= horizon:
                deadlines.append({
                    "id": case.id, "title": f"Escalation SLA: {_short(case.topic, 50) or case.id}",
                    "context": case.jurisdiction or "", "dueAt": _iso(due),
                    "state": "overdue" if due < now else ("approaching" if due - now <= timedelta(days=2) else "scheduled"),
                    "href": "/escalation-queue",
                })
    if user_has_permission(user, SUPPORT_READ):
        for incident in await _open_incidents(db, user):
            attention.append({
                "id": incident.id, "kind": "incident",
                "level": "high" if (incident.severity or "").lower() in {"critical", "high"} else "attention",
                "title": f"Incident: {_short(incident.title, 70)}",
                "context": f"{incident.severity} · {incident.containment_status}", "dueAt": None,
                "action": "Open incident", "href": "/incident-response",
            })
    if user_has_permission(user, SOURCE_READ):
        expiring = await get_soonest_expiring(db, user.tenant_id)
        days = expiring["days_remaining"] if expiring else None
        if days is not None and days <= LICENCE_WARNING_DAYS:
            title = expiring["title"]
            attention.append({
                "id": f"licence:{expiring['version_id']}", "kind": "source_licence",
                "level": "high" if days <= 7 else "attention",
                "title": "Source licence expiring" if days >= 0 else "Source licence expired",
                "context": _short(title, 100), "dueAt": None,
                "daysRemaining": days, "action": "Review licence", "href": "/source-licensing",
            })
    attention.sort(key=lambda item: _LEVEL_ORDER.get(item["level"], 9))
    attention_total = len(attention)
    attention = attention[:ATTENTION_LIMIT]
    deadlines.sort(key=lambda item: item["dueAt"] or "")
    deadlines = deadlines[:PANEL_LIMIT]
    attention_sources = can_safety or user_has_permission(user, SUPPORT_READ) or user_has_permission(user, SOURCE_READ)
    freshness["attentionItems"] = {"state": "current"} if attention_sources else dict(restricted)
    freshness["deadlines"] = {"state": "current"} if can_safety else dict(restricted)

    active_matters = await _active_matters(db, user)
    freshness["activeMatters"] = {"state": "current"}
    recent_work = await _recent_work(db, user)
    freshness["recentWork"] = {"state": "current"}

    return {
        "professionalSummary": {
            "attentionCount": attention_total, "reviewCount": review_count, "deadlineCount": len(deadlines),
            "summaryGeneratedAt": now.isoformat(), "dataFreshnessState": "current",
        },
        "attentionItems": attention,
        "activeMatters": active_matters,
        "deadlines": deadlines,
        "reviewQueue": review_queue,
        "recentWork": recent_work,
        "moduleFreshness": freshness,
    }
