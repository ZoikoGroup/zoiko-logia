# Endpoints backing the Review, Escalation & Audit pages: Escalation Queue,
# Audit Replay, Incident Response, Support Tickets and Audit Logs.
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import ServiceAccount, User
from app.domains.identity.permissions import user_has_permission
from app.domains.identity.rbac import enforce_step_up, get_current_user, require_admin
from app.domains.review_console import audit, escalations, incidents, tickets

router = APIRouter(prefix="/review", tags=["Review, Escalation & Audit"])


def _needs(*permissions: str):
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if not any(user_has_permission(user, p) for p in permissions):
            raise HTTPException(status_code=403, detail="Your role cannot use this view")
        return user
    return dependency


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 422, detail=str(exc))


audit_reader = _needs("safety.read", "support.read", "audit.correct")
escalation_reader = _needs("safety.read", "review.read")
escalation_actor = _needs("safety.manage", "review.resolve")
support_reader = _needs("support.read")
support_actor = _needs("support.manage")


@router.get("/people")
async def people(db: AsyncSession = Depends(get_db), user: User = Depends(audit_reader)) -> list[dict]:
    service = select(ServiceAccount.id).where(ServiceAccount.tenant_id == user.tenant_id)
    rows = (await db.execute(select(User).where(User.tenant_id == user.tenant_id, User.is_active.is_(True),
                                                User.id.not_in(service)).order_by(User.full_name))).scalars()
    return [{"id": u.id, "name": u.full_name or u.email, "role": u.role,
             "expert": user_has_permission(u, "safety.manage") or user_has_permission(u, "review.resolve")} for u in rows]


# ── Escalation Queue ───────────────────────────────────────────────────────

@router.get("/escalations")
async def get_escalations(db: AsyncSession = Depends(get_db), user: User = Depends(escalation_reader)) -> dict:
    return await escalations.queue(db, user.tenant_id)


class EscalationBody(BaseModel):
    topic: str = Field(min_length=3, max_length=200)
    detail: str = Field(default="", max_length=4000)
    risk_level: Literal["RESTRICTED", "HIGH", "MEDIUM", "LOW"] = "HIGH"
    jurisdiction: str = Field(default="GLOBAL", max_length=60)


@router.post("/escalations", status_code=201)
async def raise_escalation(body: EscalationBody, db: AsyncSession = Depends(get_db),
                           user: User = Depends(escalation_actor)) -> dict:
    case = await escalations.create(db, user, topic=body.topic.strip(), detail=body.detail.strip(),
                                    risk_level=body.risk_level, jurisdiction=body.jurisdiction.strip())
    return {"id": case.id}


class EscalationAction(BaseModel):
    action: Literal["assign", "start_review", "request_info", "escalate", "note", "approve", "refuse"]
    note: str = Field(default="", max_length=2000)
    assignee_id: str | None = None


@router.post("/escalations/{case_id}/actions")
async def act_on_escalation(case_id: str, body: EscalationAction, db: AsyncSession = Depends(get_db),
                            user: User = Depends(escalation_actor)) -> dict:
    if body.action in {"approve", "refuse"}:
        await enforce_step_up(db, user, "safety.manage")
    try:
        case = await escalations.act(db, user, case_id, body.action, note=body.note, assignee_id=body.assignee_id)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": case.id, "status": case.status.value if hasattr(case.status, "value") else case.status}


# ── Support Tickets ────────────────────────────────────────────────────────

@router.get("/tickets")
async def get_tickets(db: AsyncSession = Depends(get_db), user: User = Depends(support_reader)) -> dict:
    return await tickets.register(db, user.tenant_id)


class TicketBody(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=8000)
    category: str
    priority: Literal["P1", "P2", "P3", "P4"] = "P3"
    jurisdiction: str = Field(default="", max_length=60)
    query_id: str | None = Field(default=None, max_length=120)


@router.post("/tickets", status_code=201)
async def create_ticket(body: TicketBody, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    try:
        t = await tickets.create(db, user, subject=body.subject, description=body.description, category=body.category,
                                 priority_=body.priority, jurisdiction=body.jurisdiction, query_id=body.query_id)
    except ValueError as exc:
        raise _refused(exc) from exc
    return {"id": t.id}


class TicketAction(BaseModel):
    action: Literal["reply", "note", "customer_update", "assign", "status", "escalate", "raise_incident", "resolve", "reopen"]
    body: str = Field(default="", max_length=8000)
    owner_id: str | None = None
    status: Literal["open", "in_progress", "investigating", "waiting_customer"] | None = None


@router.post("/tickets/{ticket_id}/actions")
async def act_on_ticket(ticket_id: str, body: TicketAction, db: AsyncSession = Depends(get_db),
                        user: User = Depends(support_actor)) -> dict:
    try:
        await tickets.act(db, user, ticket_id, body.action, body=body.body, owner_id=body.owner_id, new_status=body.status)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return await tickets.view_one(db, user.tenant_id, ticket_id)


# ── Incident Response ──────────────────────────────────────────────────────

@router.get("/incidents")
async def get_incidents(db: AsyncSession = Depends(get_db), user: User = Depends(support_reader)) -> dict:
    return await incidents.register(db, user.tenant_id)


class IncidentBody(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    severity: Literal["Critical", "High", "Medium", "Low"] = "High"
    note: str = Field(min_length=3, max_length=4000)
    event_id: str | None = None


@router.post("/incidents", status_code=201)
async def open_incident(body: IncidentBody, db: AsyncSession = Depends(get_db), user: User = Depends(support_actor)) -> dict:
    source = "AUDIT_EVENT" if body.event_id else "MANUAL"
    try:
        i = await incidents.create(db, user, title=body.title, severity=body.severity, source=source, note=body.note,
                                   event_id=body.event_id)
    except ValueError as exc:
        raise _refused(exc) from exc
    return {"id": i.id}


class IncidentAction(BaseModel):
    action: Literal["assign", "contain", "severity", "link_event", "note", "resolve", "reopen"]
    note: str = Field(default="", max_length=4000)
    owner_id: str | None = None
    event_id: str | None = None
    severity: Literal["Critical", "High", "Medium", "Low"] | None = None


@router.post("/incidents/{incident_id}/actions")
async def act_on_incident(incident_id: str, body: IncidentAction, db: AsyncSession = Depends(get_db),
                          user: User = Depends(support_actor)) -> dict:
    try:
        await incidents.act(db, user, incident_id, body.action, note=body.note, owner_id=body.owner_id,
                            event_id=body.event_id, severity=body.severity)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return await incidents.view_one(db, user.tenant_id, incident_id)


# ── Audit Logs & Audit Replay ──────────────────────────────────────────────

@router.get("/audit/overview")
async def get_audit_overview(fresh: bool = False, db: AsyncSession = Depends(get_db),
                             user: User = Depends(audit_reader)) -> dict:
    return await audit.overview(db, user.tenant_id, fresh=fresh)


@router.get("/audit/events")
async def get_audit_events(family: str = "", risk: str = "", outcome: str = "", q: str = "", days: int = 30,
                           limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db),
                           user: User = Depends(audit_reader)) -> dict:
    return await audit.events(db, user.tenant_id, family=family, risk=risk, outcome=outcome, q=q,
                              days=max(1, min(days, 365)), limit=limit, offset=max(0, offset))


@router.get("/audit/traces")
async def get_traces(db: AsyncSession = Depends(get_db), user: User = Depends(audit_reader)) -> dict:
    return await audit.traces(db, user.tenant_id)


class ExportBody(BaseModel):
    purpose: str = Field(min_length=10, max_length=1000)
    filters: dict = Field(default_factory=dict)


@router.post("/audit/exports", status_code=201)
async def request_export(body: ExportBody, db: AsyncSession = Depends(get_db), user: User = Depends(audit_reader)) -> dict:
    try:
        x = await audit.request_export(db, user, body.purpose, body.filters)
    except ValueError as exc:
        raise _refused(exc) from exc
    return {"id": x.id, "ref": x.ref}


class ExportDecision(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=1000)


@router.post("/audit/exports/{export_id}/decision")
async def decide_export(export_id: str, body: ExportDecision, db: AsyncSession = Depends(get_db),
                        admin: User = Depends(require_admin)) -> dict:
    try:
        x = await audit.decide_export(db, admin, export_id, body.approve, body.note)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": x.id, "status": x.status}


@router.get("/audit/exports/{export_id}/download")
async def download_export(export_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(audit_reader)) -> Response:
    try:
        filename, content = await audit.export_csv(db, user, export_id)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return Response(content=content, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})
