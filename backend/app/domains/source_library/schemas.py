from datetime import date, datetime

from pydantic import BaseModel


class SourceCreateRequest(BaseModel):
    category: str
    title: str
    source_class: str
    jurisdiction_scope: str = "Global"
    framework_scope: str = ""
    note: str = ""
    file_path: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None


class SourceVersionPublic(BaseModel):
    id: str
    version_label: str
    status: str
    effective_from: date | None
    effective_to: date | None
    display_restriction: str
    note: str
    submitted_by: str
    approved_by: str | None
    created_at: datetime
    file_path: str | None = None

    model_config = {"from_attributes": True}


class SourcePublic(BaseModel):
    id: str
    category: str
    title: str
    source_class: str
    jurisdiction_scope: str
    framework_scope: str
    latest_version: SourceVersionPublic

    model_config = {"from_attributes": True}


class ExpiringSourceOut(BaseModel):
    source_id: str
    version_id: str
    title: str
    category: str
    jurisdiction_scope: str
    effective_to: date
    days_remaining: int


class JurisdictionCategoryBreakdown(BaseModel):
    category: str
    approved_count: int
    pending_count: int


class JurisdictionSummaryOut(BaseModel):
    jurisdiction_scope: str
    approved_count: int
    pending_count: int
    categories: list[JurisdictionCategoryBreakdown]
    readiness: str  # READY | PARTIAL | NOT_STARTED
