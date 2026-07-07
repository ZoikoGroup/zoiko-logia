from datetime import date, datetime

from pydantic import BaseModel


class SourceCreateRequest(BaseModel):
    category: str
    title: str
    source_class: str
    jurisdiction_scope: str = "Global"
    framework_scope: str = ""
    note: str = ""


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
