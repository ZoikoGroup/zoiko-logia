from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.support_incident.models import Incident, SupportTicket
from app.domains.support_incident.schemas import TicketCreateRequest


async def list_tickets(db: AsyncSession, tenant_id: str) -> list[SupportTicket]:
    result = await db.execute(select(SupportTicket).where(SupportTicket.tenant_id == tenant_id))
    return list(result.scalars().all())


async def create_ticket(
    db: AsyncSession, tenant_id: str, created_by: str, payload: TicketCreateRequest
) -> SupportTicket:
    ticket = SupportTicket(
        tenant_id=tenant_id,
        category=payload.category,
        severity=payload.severity,
        query_id=payload.query_id,
        created_by=created_by,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def update_ticket_status(
    db: AsyncSession, tenant_id: str, ticket_id: str, status: str
) -> SupportTicket | None:
    result = await db.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.tenant_id == tenant_id)
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        return None
    ticket.status = status
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def list_incidents(db: AsyncSession, tenant_id: str) -> list[Incident]:
    result = await db.execute(select(Incident).where(Incident.tenant_id == tenant_id))
    return list(result.scalars().all())
