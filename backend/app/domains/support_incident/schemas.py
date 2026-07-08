from datetime import datetime

from pydantic import BaseModel


class TicketCreateRequest(BaseModel):
    category: str
    severity: str = "P3"
    query_id: str | None = None


class TicketStatusUpdateRequest(BaseModel):
    status: str


class TicketPublic(BaseModel):
    id: str
    category: str
    severity: str
    status: str
    query_id: str | None
    created_by: str
    assigned_to: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class IncidentPublic(BaseModel):
    id: str
    title: str
    severity: str
    status: str
    commander: str | None
    opened_at: datetime

    model_config = {"from_attributes": True}
