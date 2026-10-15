"""Support Tickets: requests from people using the platform, worked against
a service-level clock.

The SLA clock runs from creation, pauses while the ticket waits on the
requester, and is measured against fixed targets per priority (SLA_POLICY).
A ticket that needs a professional decision is escalated into the Escalation
Queue; a suspected security problem raises an incident. Both stay linked.
Support sees the ticket and what the requester wrote, never tenant records.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User
from app.domains.review_console import escalations, incidents
from app.domains.support_incident.models import SupportTicket

# Hours to first response and to resolution, per priority.
SLA_POLICY = {"P1": (1, 8), "P2": (4, 24), "P3": (24, 72), "P4": (72, 168)}
PRIORITY_LABEL = {"P1": "Urgent", "P2": "High", "P3": "Normal", "P4": "Low"}
CATEGORIES = ("source_citation", "workflow", "access_identity", "product_guidance", "evidence", "billing",
              "notifications", "accuracy", "privacy", "security")
STATUSES = ("open", "in_progress", "investigating", "waiting_customer", "escalated", "resolved")
LEGACY_STATUS = {"Open": "open", "Closed": "resolved"}
AT_RISK_FRACTION = 0.25


class TicketError(ValueError):
    """An action the support rules refuse."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: datetime | None) -> datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=timezone.utc))


def _iso(v: datetime | None) -> str | None:
    v = _aware(v)
    return v.isoformat() if v else None


def priority(t: SupportTicket) -> str:
    return "P1" if t.severity == "P0" else (t.severity if t.severity in SLA_POLICY else "P3")


def status(t: SupportTicket) -> str:
    return LEGACY_STATUS.get(t.status, t.status if t.status in STATUSES else "open")


def sla(t: SupportTicket, now: datetime) -> dict:
    first_h, resolve_h = SLA_POLICY[priority(t)]
    created = _aware(t.created_at) or now
    paused = timedelta(seconds=t.paused_seconds or 0)
    waiting = status(t) == "waiting_customer" and t.waiting_since is not None
    if waiting:
        paused += now - _aware(t.waiting_since)
    due = created + timedelta(hours=resolve_h) + paused
    first_due = created + timedelta(hours=first_h)
    first = _aware(t.first_response_at)
    resolved = _aware(t.resolved_at)
    end = resolved or now
    remaining = (due - end).total_seconds()
    if status(t) == "resolved":
        state = "met" if remaining >= 0 else "breached"
    elif waiting:
        state = "paused"
    elif remaining < 0:
        state = "breached"
    elif remaining < resolve_h * 3600 * AT_RISK_FRACTION:
        state = "at_risk"
    else:
        state = "on_track"
    return {
        "state": state, "dueAt": due.isoformat(), "remainingSeconds": int(remaining),
        "firstResponseDueAt": first_due.isoformat(),
        "firstResponseMet": None if first is None and now < first_due else bool(first and first <= first_due),
        "targetHours": resolve_h, "firstResponseHours": first_h,
    }


def _messages(t: SupportTicket) -> list[dict]:
    return list(t.messages or [])


def _entry(kind: str, actor: User | None, body: str) -> dict:
    return {"at": _now().isoformat(), "kind": kind, "actorId": actor.id if actor else None,
            "actor": (actor.full_name or actor.email) if actor else "System", "body": body}


def _ref(t: SupportTicket, index: dict[str, int]) -> str:
    created = _aware(t.created_at) or _now()
    return f"SUP-{created.year}-{index.get(t.id, 0):04d}"


def _view(t: SupportTicket, names: dict[str, str], index: dict[str, int], now: datetime) -> dict:
    p = priority(t)
    return {
        "id": t.id, "ref": _ref(t, index), "subject": t.subject or f"{t.category.replace('_', ' ').title()} request",
        "description": t.description or "", "category": t.category, "priority": p,
        "priorityLabel": PRIORITY_LABEL[p], "status": status(t), "jurisdiction": t.jurisdiction or "",
        "requesterId": t.created_by, "requester": names.get(t.created_by, ""),
        "ownerId": t.assigned_to, "owner": names.get(t.assigned_to or ""),
        "queryId": t.query_id, "sourceId": t.source_id, "createdAt": _iso(t.created_at),
        "firstResponseAt": _iso(t.first_response_at), "resolvedAt": _iso(t.resolved_at),
        "resolutionNote": t.resolution_note or "", "escalationId": t.escalation_id, "incidentId": t.incident_id,
        "sla": sla(t, now), "messages": _messages(t),
    }


async def _names(db: AsyncSession, tenant_id: str) -> dict[str, str]:
    return {u.id: u.full_name or u.email for u in (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars()}


async def _all(db: AsyncSession, tenant_id: str) -> list[SupportTicket]:
    return list((await db.execute(select(SupportTicket).where(SupportTicket.tenant_id == tenant_id)
                                  .order_by(SupportTicket.created_at))).scalars().all())


def _index(tickets: list[SupportTicket]) -> dict[str, int]:
    return {t.id: i + 1 for i, t in enumerate(tickets)}


async def register(db: AsyncSession, tenant_id: str) -> dict:
    now = _now()
    tickets = await _all(db, tenant_id)
    names = await _names(db, tenant_id)
    index = _index(tickets)
    views = [_view(t, names, index, now) for t in reversed(tickets)]
    open_ = [v for v in views if v["status"] != "resolved"]
    month = now - timedelta(days=30)
    recent = [v for v in views if v["createdAt"] and datetime.fromisoformat(v["createdAt"]) >= month]
    responded = [v for v in recent if v["sla"]["firstResponseMet"] is not None]
    resolved_recent = [v for v in recent if v["status"] == "resolved"]
    prio = Counter(v["priority"] for v in open_)
    activity = sorted(({"ticketId": v["id"], "ref": v["ref"], **m} for v in views for m in v["messages"]),
                      key=lambda m: m["at"], reverse=True)[:8]
    return {
        "tickets": views,
        "summary": {
            "open": len(open_), "atRisk": sum(v["sla"]["state"] == "at_risk" for v in open_),
            "breaches": sum(v["sla"]["state"] == "breached" for v in open_),
            "waitingCustomer": sum(v["status"] == "waiting_customer" for v in open_),
            "escalated": sum(v["status"] == "escalated" for v in open_),
            "unassigned": sum(not v["ownerId"] for v in open_),
            "firstResponsePct": round(100 * sum(v["sla"]["firstResponseMet"] for v in responded) / len(responded)) if responded else None,
            "resolutionPct": round(100 * sum(v["sla"]["state"] == "met" for v in resolved_recent) / len(resolved_recent)) if resolved_recent else None,
            "byPriority": {k: prio.get(k, 0) for k in SLA_POLICY},
        },
        "policy": [{"priority": k, "label": PRIORITY_LABEL[k], "firstResponseHours": f, "resolutionHours": r}
                   for k, (f, r) in SLA_POLICY.items()],
        "categories": CATEGORIES,
        "activity": activity,
        "generatedAt": now.isoformat(),
    }


async def _get(db: AsyncSession, tenant_id: str, ticket_id: str) -> SupportTicket:
    t = (await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.tenant_id == tenant_id))).scalar_one_or_none()
    if t is None:
        raise LookupError("Ticket not found")
    return t


async def _audit(db: AsyncSession, actor: User, event: str, t: SupportTicket, payload: dict) -> None:
    await record_event_async(db, tenant_id=actor.tenant_id, event_name=event, emitting_service="review_console",
                             actor_id=actor.id, subject_type="support_ticket", subject_id=t.id, payload=payload)


async def create(db: AsyncSession, actor: User, *, subject: str, description: str, category: str, priority_: str,
                 jurisdiction: str = "", query_id: str | None = None) -> SupportTicket:
    if category not in CATEGORIES:
        raise TicketError("Unknown category")
    if priority_ not in SLA_POLICY:
        raise TicketError("Unknown priority")
    t = SupportTicket(tenant_id=actor.tenant_id, category=category, severity=priority_, status="open",
                      subject=subject.strip(), description=description.strip(), jurisdiction=jurisdiction.strip() or None,
                      query_id=query_id, created_by=actor.id, created_at=_now(), paused_seconds=0,
                      messages=[_entry("customer", actor, description.strip())] if description.strip() else [])
    db.add(t)
    await db.flush()
    await _audit(db, actor, "support_ticket_created", t, {"priority": priority_, "category": category})
    return t


def _leave_waiting(t: SupportTicket) -> None:
    if status(t) == "waiting_customer" and t.waiting_since is not None:
        t.paused_seconds = (t.paused_seconds or 0) + int((_now() - _aware(t.waiting_since)).total_seconds())
        t.waiting_since = None


async def act(db: AsyncSession, actor: User, ticket_id: str, action: str, *, body: str = "",
              owner_id: str | None = None, new_status: str | None = None) -> SupportTicket:
    t = await _get(db, actor.tenant_id, ticket_id)
    body = body.strip()
    current = status(t)
    if current == "resolved" and action not in {"reopen", "note"}:
        raise TicketError("This ticket is resolved; reopen it first")
    payload: dict = {}
    if action == "reply":
        if not body:
            raise TicketError("Write a response")
        t.first_response_at = t.first_response_at or _now()
        t.messages = [*_messages(t), _entry("reply", actor, body)]
        if current == "open":
            t.status = "in_progress"
    elif action == "note":
        if not body:
            raise TicketError("Write a note")
        t.messages = [*_messages(t), _entry("note", actor, body)]
    elif action == "customer_update":
        if not body:
            raise TicketError("Record what the requester provided")
        _leave_waiting(t)
        t.status = "in_progress"
        t.messages = [*_messages(t), _entry("customer", actor, body)]
    elif action == "assign":
        person = (await db.execute(select(User).where(User.id == (owner_id or ""), User.tenant_id == actor.tenant_id,
                                                      User.is_active.is_(True)))).scalar_one_or_none()
        if person is None:
            raise TicketError("Choose an active person in this workspace")
        t.assigned_to = person.id
        t.messages = [*_messages(t), _entry("system", actor, f"Assigned to {person.full_name or person.email}")]
        payload["owner"] = person.id
    elif action == "status":
        if new_status not in {"open", "in_progress", "investigating", "waiting_customer"}:
            raise TicketError("Use resolve, escalate or reopen for that status")
        if new_status == "waiting_customer":
            t.waiting_since = t.waiting_since or _now()
        else:
            _leave_waiting(t)
        t.status = new_status
        t.messages = [*_messages(t), _entry("system", actor, f"Status: {new_status.replace('_', ' ')}{' · ' + body if body else ''}")]
        payload["status"] = new_status
    elif action == "escalate":
        if t.escalation_id:
            raise TicketError("This ticket is already escalated")
        if not body:
            raise TicketError("Say what needs an expert decision")
        p = priority(t)
        esc = await escalations.create(
            db, actor, topic=t.subject or "Support escalation", detail=f"From support ticket: {body}",
            risk_level={"P1": "RESTRICTED", "P2": "HIGH", "P3": "MEDIUM", "P4": "LOW"}[p],
            jurisdiction=t.jurisdiction or "GLOBAL", query_id=t.query_id, origin="support_ticket",
            query_text=t.description or t.subject or "")
        _leave_waiting(t)
        t.escalation_id, t.status = esc.id, "escalated"
        t.messages = [*_messages(t), _entry("system", actor, f"Escalated as {esc.id}: {body}")]
        payload["escalation"] = esc.id
    elif action == "raise_incident":
        if t.incident_id:
            raise TicketError("An incident is already linked")
        if not body:
            raise TicketError("Describe the suspected security problem")
        inc = await incidents.create(db, actor, title=t.subject or "Security concern from support",
                                     severity="High" if priority(t) in {"P1", "P2"} else "Medium",
                                     source="SUPPORT_TICKET", note=body, ticket_id=t.id, query_id=t.query_id)
        t.incident_id = inc.id
        t.messages = [*_messages(t), _entry("system", actor, f"Incident {inc.id} raised: {body}")]
        payload["incident"] = inc.id
    elif action == "resolve":
        if not body:
            raise TicketError("Record the resolution")
        _leave_waiting(t)
        t.status, t.resolved_at, t.resolution_note = "resolved", _now(), body
        t.first_response_at = t.first_response_at or _now()
        t.messages = [*_messages(t), _entry("system", actor, f"Resolved: {body}")]
    elif action == "reopen":
        if current != "resolved":
            raise TicketError("Only a resolved ticket can be reopened")
        t.status, t.resolved_at = "open", None
        t.messages = [*_messages(t), _entry("system", actor, f"Reopened{': ' + body if body else ''}")]
    else:
        raise TicketError("Unknown action")
    await db.flush()
    await _audit(db, actor, f"support_ticket_{action}", t, payload)
    return t


async def view_one(db: AsyncSession, tenant_id: str, ticket_id: str) -> dict:
    tickets = await _all(db, tenant_id)
    t = next(x for x in tickets if x.id == ticket_id)
    return _view(t, await _names(db, tenant_id), _index(tickets), _now())
