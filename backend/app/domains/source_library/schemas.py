from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SourceCreateRequest(BaseModel):
    category: str
    title: str
    publisher: str = ""
    owner: str = ""
    source_class: str
    jurisdiction_scope: str = "Global"
    framework_scope: str = ""
    note: str = ""
    file_path: str | None = None
    source_url: str | None = None
    content_hash: str = ""
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    original_language: str = "en"
    translation_of_version_id: str | None = None
    rights: dict[str, bool] = Field(default_factory=dict)
    terms_reference: str = ""
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None


    @model_validator(mode="after")
    def validate_applicability(self):
        for start, end in ((self.effective_from, self.effective_to),
                           (self.reporting_period_start, self.reporting_period_end)):
            if end and (not start or start > end):
                raise ValueError("Applicability ranges require a start on or before their end")
        if bool(self.reporting_period_start) != bool(self.reporting_period_end):
            raise ValueError("Both reporting-period bounds are required")
        return self


class SourceVersionPublic(BaseModel):
    id: str
    version_label: str
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    superseded_at: datetime | None = None
    status: str
    effective_from: date | None
    effective_to: date | None
    display_restriction: str
    note: str
    submitted_by: str
    approved_by: str | None
    created_at: datetime
    file_path: str | None = None
    source_url: str | None = None
    content_hash: str
    published_at: datetime | None
    retrieved_at: datetime
    quality_state: str
    original_language: str
    translation_of_version_id: str | None
    superseded_by_version_id: str | None
    revoked_at: datetime | None
    revocation_reason: str | None

    model_config = {"from_attributes": True}


class SourcePublic(BaseModel):
    id: str
    category: str
    title: str
    publisher: str
    owner: str
    source_class: str
    jurisdiction_scope: str
    framework_scope: str
    latest_version: SourceVersionPublic

    model_config = {"from_attributes": True}


SourceOperation = Literal[
    "ingestion", "indexing", "retrieval", "model_transmission", "display",
    "summary", "export", "retention", "training",
]


class SourceRightGrantRequest(BaseModel):
    operation: SourceOperation
    decision: Literal["allow", "deny"]
    reason_code: str
    terms_reference: str = ""
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class SourceRightPublic(SourceRightGrantRequest):
    id: str
    source_version_id: str
    rights_version: int
    granted_by: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SourcePassagePublic(BaseModel):
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    id: str
    source_version_id: str
    locator: str
    sequence: int
    content: str
    content_hash: str
    language: str
    is_translation: bool
    derived_from_passage_id: str | None

    model_config = {"from_attributes": True}


class SourceRelationshipRequest(BaseModel):
    to_version_id: str
    relationship_type: Literal["supersedes", "clarifies", "references", "complements", "conflicts", "historical_only"]


class SourceRevocationRequest(BaseModel):
    reason: str


class SourceUsagePublic(BaseModel):
    artifact_type: str
    artifact_id: str
    operation: str
    passage_id: str | None
    recorded_at: datetime

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
