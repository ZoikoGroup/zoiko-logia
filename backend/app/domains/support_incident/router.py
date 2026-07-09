from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_sync_db
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin
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


@router.get("/tickets", response_model=list[TicketPublic])
def get_tickets(
    db: Session = Depends(get_sync_db),
    admin: User = Depends(require_admin),
):
    tickets = list_tickets(db, admin.tenant_id)
    return tickets


@router.post("/tickets", response_model=TicketPublic)
def post_ticket(
    payload: TicketCreateRequest,
    db: Session = Depends(get_sync_db),
    admin: User = Depends(require_admin),
):
    ticket = create_ticket(db, admin.tenant_id, admin.id, payload)
    return ticket


@router.patch("/tickets/{ticket_id}", response_model=TicketPublic)
def patch_ticket(
    ticket_id: str,
    payload: TicketStatusUpdateRequest,
    db: Session = Depends(get_sync_db),
    admin: User = Depends(require_admin),
):
    ticket = update_ticket_status(db, admin.tenant_id, ticket_id, payload.status)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


# --- Incidents ---

@router.get("/incidents", response_model=list[SecurityIncidentOut])
def get_security_incidents(
    status: Optional[str] = None,
    db: Session = Depends(get_sync_db),
    admin: User = Depends(require_admin),
):
    incidents = list_incidents(db, admin.tenant_id, status=status)
    return incidents


@router.get("/incidents/stats", response_model=IncidentStatsOut)
def get_security_incident_stats(
    db: Session = Depends(get_sync_db),
    admin: User = Depends(require_admin),
):
    return get_incident_stats(db, admin.tenant_id)


@router.get("/incidents/{incident_id}", response_model=SecurityIncidentOut)
def get_security_incident(
    incident_id: str,
    db: Session = Depends(get_sync_db),
    admin: User = Depends(require_admin),
):
    incident = get_incident(db, admin.tenant_id, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.post("/incidents/{incident_id}/action", response_model=SecurityIncidentOut)
def post_incident_action(
    incident_id: str,
    payload: IncidentActionRequest,
    db: Session = Depends(get_sync_db),
    admin: User = Depends(require_admin),
):
    incident = update_incident(db, admin.tenant_id, incident_id, payload.action, payload.actor, payload.note)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.post("/incidents/{incident_id}/close", response_model=SecurityIncidentOut)
def post_incident_close(
    incident_id: str,
    payload: IncidentCloseRequest,
    db: Session = Depends(get_sync_db),
    admin: User = Depends(require_admin),
):
    incident = close_incident(db, admin.tenant_id, incident_id, payload.resolver, payload.resolution_note)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident
