from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin
from app.domains.support_incident.schemas import (
    IncidentPublic,
    TicketCreateRequest,
    TicketPublic,
    TicketStatusUpdateRequest,
)
from app.domains.support_incident.service import (
    create_ticket,
    list_incidents,
    list_tickets,
    update_ticket_status,
)

router = APIRouter(prefix="/support", tags=["support"])


@router.get("/tickets", response_model=list[TicketPublic])
async def get_tickets(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[TicketPublic]:
    tickets = await list_tickets(db, admin.tenant_id)
    return [TicketPublic.model_validate(t) for t in tickets]


@router.post("/tickets", response_model=TicketPublic)
async def post_ticket(
    payload: TicketCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> TicketPublic:
    ticket = await create_ticket(db, admin.tenant_id, admin.id, payload)
    return TicketPublic.model_validate(ticket)


@router.patch("/tickets/{ticket_id}", response_model=TicketPublic)
async def patch_ticket(
    ticket_id: str,
    payload: TicketStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> TicketPublic:
    ticket = await update_ticket_status(db, admin.tenant_id, ticket_id, payload.status)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return TicketPublic.model_validate(ticket)


@router.get("/incidents", response_model=list[IncidentPublic])
async def get_incidents(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[IncidentPublic]:
    incidents = await list_incidents(db, admin.tenant_id)
    return [IncidentPublic.model_validate(i) for i in incidents]
