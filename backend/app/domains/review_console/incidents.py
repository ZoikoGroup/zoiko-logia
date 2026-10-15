"""Incident Response: security incidents from detection to resolution.

Incidents are opened by the platform's own detections (prompt injection, data
exfiltration, control bypass), raised from a support ticket, or opened from an
audit event. Every action is credited to the signed-in user and recorded in
the incident timeline and the audit ledger. Resolving a Critical incident
needs someone other than its owner.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import User
from app.domains.support_incident.models import SecurityIncident

SEVERITIES = ("Critical", "High", "Medium", "Low")


class IncidentError(ValueError):
    """An action the incident rules refuse."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: datetime | None) -> datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=timezone.utc))


def _iso(v: datetime | None) -> str | None:
    v = _aware(v)
    return v.isoformat() if v else None


def _entry(action: str, actor: User | None, note: str) -> dict:
    return {"timestamp": _now().isoformat(), "actor": (actor.full_name or actor.email) if actor else "system",
            "actorId": actor.id if actor else None, "action": action, "note": note}


def _view(i: SecurityIncident, names: dict[str, str]) -> dict:
    opened, resolved = _aware(i.opened_at), _aware(i.resolved_at)
    return {
        "id": i.id, "title": i.title, "severity": i.severity, "status": i.containment_status, "source": i.source,
        "sourceLabel": i.source.replace("_", " ").title(), "queryId": i.query_id, "subClass": i.restricted_sub_class,
        "ownerId": i.assigned_to, "owner": names.get(i.assigned_to or "", i.assigned_to),
        "openedAt": _iso(opened), "resolvedAt": _iso(resolved), "resolutionNote": i.resolution_note or "",
        "hoursOpen": round(((resolved or _now()) - opened).total_seconds() / 3600, 1) if opened else None,
        "linkedEventIds": list(i.linked_event_ids or []), "ticketId": i.ticket_id, "timeline": list(i.timeline or []),
    }


async def _names(db: AsyncSession, tenant_id: str) -> dict[str, str]:
    return {u.id: u.full_name or u.email for u in (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars()}


async def register(db: AsyncSession, tenant_id: str) -> dict:
    now = _now()
    rows = (await db.execute(select(SecurityIncident).where(SecurityIncident.tenant_id == tenant_id)
                             .order_by(SecurityIncident.opened_at.desc()))).scalars().all()
    names = await _names(db, tenant_id)
    views = [_view(i, names) for i in rows]
    open_ = [v for v in views if v["status"] != "RESOLVED"]
    month = now - timedelta(days=30)
    resolved_recent = [v for v in views if v["resolvedAt"] and datetime.fromisoformat(v["resolvedAt"]) >= month]
    sev = Counter(v["severity"] for v in open_)
    sources = Counter(v["sourceLabel"] for v in views if v["openedAt"] and datetime.fromisoformat(v["openedAt"]) >= month)
    return {
        "incidents": views,
        "summary": {
            "open": sum(v["status"] == "OPEN" for v in views), "contained": sum(v["status"] == "CONTAINED" for v in views),
            "critical": sev.get("Critical", 0), "high": sev.get("High", 0), "unowned": sum(not v["ownerId"] for v in open_),
            "resolved30d": len(resolved_recent),
            "mttrHours": round(sum(v["hoursOpen"] for v in resolved_recent) / len(resolved_recent), 1) if resolved_recent else None,
            "bySeverity": {k: sev.get(k, 0) for k in SEVERITIES},
        },
        "sources30d": [{"source": k, "count": c} for k, c in sources.most_common(6)],
        "generatedAt": now.isoformat(),
    }


async def _get(db: AsyncSession, tenant_id: str, incident_id: str) -> SecurityIncident:
    i = (await db.execute(select(SecurityIncident).where(
        SecurityIncident.id == incident_id, SecurityIncident.tenant_id == tenant_id))).scalar_one_or_none()
    if i is None:
        raise LookupError("Incident not found")
    return i


async def _audit(db: AsyncSession, actor: User, event: str, i: SecurityIncident, payload: dict) -> None:
    await record_event_async(db, tenant_id=actor.tenant_id, event_name=event, emitting_service="review_console",
                             actor_id=actor.id, subject_type="security_incident", subject_id=i.id,
                             correlation_id=i.query_id, payload=payload)


async def create(db: AsyncSession, actor: User, *, title: str, severity: str, source: str, note: str,
                 ticket_id: str | None = None, query_id: str | None = None, event_id: str | None = None) -> SecurityIncident:
    if severity not in SEVERITIES:
        raise IncidentError("Unknown severity")
    i = SecurityIncident(tenant_id=actor.tenant_id, title=title.strip(), severity=severity, containment_status="OPEN",
                         source=source, query_id=query_id, ticket_id=ticket_id, opened_at=_now(),
                         linked_event_ids=[event_id] if event_id else [], timeline=[_entry("opened", actor, note.strip())])
    db.add(i)
    await db.flush()
    await _audit(db, actor, "security_incident_opened", i, {"severity": severity, "source": source})
    return i


async def act(db: AsyncSession, actor: User, incident_id: str, action: str, *, note: str = "",
              owner_id: str | None = None, event_id: str | None = None, severity: str | None = None) -> SecurityIncident:
    i = await _get(db, actor.tenant_id, incident_id)
    note = note.strip()
    if i.containment_status == "RESOLVED" and action not in {"note", "reopen"}:
        raise IncidentError("This incident is resolved")
    payload: dict = {}
    if action == "assign":
        person = (await db.execute(select(User).where(User.id == (owner_id or ""), User.tenant_id == actor.tenant_id,
                                                      User.is_active.is_(True)))).scalar_one_or_none()
        if person is None:
            raise IncidentError("Choose an active person in this workspace")
        i.assigned_to = person.id
        note = note or f"Owner: {person.full_name or person.email}"
        payload["owner"] = person.id
    elif action == "contain":
        if i.containment_status != "OPEN":
            raise IncidentError("Only an open incident can be contained")
        if not note:
            raise IncidentError("Describe the containment")
        i.containment_status = "CONTAINED"
    elif action == "severity":
        if severity not in SEVERITIES:
            raise IncidentError("Unknown severity")
        note = note or f"Severity {i.severity} → {severity}"
        payload["severity"] = severity
        i.severity = severity
    elif action == "link_event":
        event = (await db.execute(select(AuditEvent).where(
            AuditEvent.id == (event_id or ""), AuditEvent.tenant_id == actor.tenant_id))).scalar_one_or_none()
        if event is None:
            raise IncidentError("Audit event not found in this workspace")
        if event.id in (i.linked_event_ids or []):
            raise IncidentError("Already linked")
        i.linked_event_ids = [*(i.linked_event_ids or []), event.id]
        note = note or f"Linked audit event {event.event_name}"
        payload["event"] = event.id
    elif action == "note":
        if not note:
            raise IncidentError("Write a note")
    elif action == "resolve":
        if not note:
            raise IncidentError("Record the resolution")
        if i.severity == "Critical" and i.assigned_to == actor.id:
            raise IncidentError("A Critical incident is closed by someone other than its owner")
        i.containment_status, i.resolved_at, i.resolution_note = "RESOLVED", _now(), note
    elif action == "reopen":
        if i.containment_status != "RESOLVED":
            raise IncidentError("Only a resolved incident can be reopened")
        i.containment_status, i.resolved_at = "OPEN", None
    else:
        raise IncidentError("Unknown action")
    i.timeline = [*(i.timeline or []), _entry(action, actor, note)]
    await db.flush()
    await _audit(db, actor, f"security_incident_{action}", i, payload)
    return i


async def view_one(db: AsyncSession, tenant_id: str, incident_id: str) -> dict:
    return _view(await _get(db, tenant_id, incident_id), await _names(db, tenant_id))
