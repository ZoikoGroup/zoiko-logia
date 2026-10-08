from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_sync_db
from app.domains.identity.models import User
from app.domains.identity.permissions import SUPPORT_MANAGE, SUPPORT_READ
from app.domains.identity.rbac import require_permission
from app.domains.support_incident.schemas import (
    SecurityIncidentOut,
    TicketCreateRequest,
    TicketPublic,
    TicketStatusUpdateRequest,
    IncidentActionRequest,
    IncidentCloseRequest,
    IncidentStatsOut
)
from app.domains.support_incident.service import (
    create_ticket,
    list_tickets,
    update_ticket_status,
    list_incidents,
    get_incident,
    update_incident,
    close_incident,
    get_incident_stats
)

router = APIRouter(prefix="/support", tags=["support"])


def _actor_label(user: User) -> str:
    """Who acted, from the authenticated user. The request body's actor and
    resolver fields are ignored: a client-supplied name would let anyone
    write any identity into the incident's audit timeline."""
    return f"{user.full_name or user.email} ({user.role})"


def _require_unresolved(db: Session, tenant_id: str, incident_id: str) -> None:
    # A resolved incident is final; containing it again would silently reopen it.
    incident = get_incident(db, tenant_id, incident_id)
    if incident and incident.containment_status == "RESOLVED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Incident is already resolved")


@router.get("/tickets", response_model=list[TicketPublic])
def get_tickets(
    db: Session = Depends(get_sync_db),
    actor: User = Depends(require_permission(SUPPORT_READ)),
):
    tickets = list_tickets(db, actor.tenant_id)
    return tickets


@router.post("/tickets", response_model=TicketPublic)
def post_ticket(
    payload: TicketCreateRequest,
    db: Session = Depends(get_sync_db),
    actor: User = Depends(require_permission(SUPPORT_MANAGE)),
):
    ticket = create_ticket(db, actor.tenant_id, actor.id, payload)
    return ticket


@router.patch("/tickets/{ticket_id}", response_model=TicketPublic)
def patch_ticket(
    ticket_id: str,
    payload: TicketStatusUpdateRequest,
    db: Session = Depends(get_sync_db),
    actor: User = Depends(require_permission(SUPPORT_MANAGE)),
):
    ticket = update_ticket_status(db, actor.tenant_id, ticket_id, payload.status)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


# --- Incidents ---

@router.get("/incidents", response_model=list[SecurityIncidentOut])
def get_security_incidents(
    status: Optional[str] = None,
    db: Session = Depends(get_sync_db),
    actor: User = Depends(require_permission(SUPPORT_READ)),
):
    incidents = list_incidents(db, actor.tenant_id, status=status)
    return incidents


@router.get("/incidents/stats", response_model=IncidentStatsOut)
def get_security_incident_stats(
    db: Session = Depends(get_sync_db),
    actor: User = Depends(require_permission(SUPPORT_READ)),
):
    return get_incident_stats(db, actor.tenant_id)


@router.get("/incidents/{incident_id}", response_model=SecurityIncidentOut)
def get_security_incident(
    incident_id: str,
    db: Session = Depends(get_sync_db),
    actor: User = Depends(require_permission(SUPPORT_READ)),
):
    incident = get_incident(db, actor.tenant_id, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.post("/incidents/{incident_id}/action", response_model=SecurityIncidentOut)
def post_incident_action(
    incident_id: str,
    payload: IncidentActionRequest,
    db: Session = Depends(get_sync_db),
    actor: User = Depends(require_permission(SUPPORT_MANAGE)),
):
    _require_unresolved(db, actor.tenant_id, incident_id)
    incident = update_incident(db, actor.tenant_id, incident_id, payload.action, _actor_label(actor), payload.note)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.post("/incidents/{incident_id}/close", response_model=SecurityIncidentOut)
def post_incident_close(
    incident_id: str,
    payload: IncidentCloseRequest,
    db: Session = Depends(get_sync_db),
    actor: User = Depends(require_permission(SUPPORT_MANAGE)),
):
    _require_unresolved(db, actor.tenant_id, incident_id)
    incident = close_incident(db, actor.tenant_id, incident_id, _actor_label(actor), payload.resolution_note)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident
