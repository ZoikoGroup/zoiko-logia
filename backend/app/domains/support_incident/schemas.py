from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class TicketCreateRequest(BaseModel):
    category: str
    severity: str = "P3"
    query_id: Optional[str] = None
    source_id: Optional[str] = None


class TicketStatusUpdateRequest(BaseModel):
    status: str


class TicketPublic(BaseModel):
    id: str
    tenant_id: str
    category: str
    severity: str
    status: str
    query_id: Optional[str]
    source_id: Optional[str] = None
    created_by: str
    assigned_to: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class SecurityIncidentOut(BaseModel):
    id: str
    tenant_id: str
    title: str
    severity: str
    containment_status: str
    source: str
    query_id: Optional[str]
    restricted_sub_class: Optional[str]
    assigned_to: Optional[str]
    timeline: List[Dict[str, Any]]
    opened_at: datetime
    resolved_at: Optional[datetime]
    resolution_note: Optional[str]

    model_config = {"from_attributes": True}


class IncidentActionRequest(BaseModel):
    action: str  # Contain, Escalate
    actor: str
    note: str


class IncidentCloseRequest(BaseModel):
    resolver: str
    resolution_note: str


class IncidentStatsOut(BaseModel):
    total: int
    open: int
    contained: int
    resolved: int
    critical: int
    high: int
