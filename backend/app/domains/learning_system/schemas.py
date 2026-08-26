from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedbackCreate(BaseModel):
    query_id: str
    correlation_id: str | None = None
    query_text: str = ""
    feedback_type: Literal["HELPFUL", "NOT_HELPFUL"]
    reason_code: str
    correction: str = ""
    remember_correction: bool = False


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str; query_id: str; feedback_type: str; reason_code: str; correction: str; created_at: datetime
    learning_candidate_id: str | None = None
    memory_id: str | None = None


class MemoryCreate(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=4000)
    confirmed: bool = False


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str; key: str; value: str; scope: str; confirmed: bool; created_at: datetime; updated_at: datetime


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str; feedback_id: str; query_text: str; expected_answer: str; reason_code: str; status: str
    reviewer_id: str | None; review_note: str; benchmark_case_id: str | None; created_at: datetime; reviewed_at: datetime | None


class CandidateReview(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    note: str = ""
    promote_to_benchmark: bool = True


class WorkflowCreate(BaseModel):
    name: str; version: int = 1; description: str = ""; match_terms: list[str]
    plan: list[str]; allowed_formats: list[str] = ["xlsx"]; risk_level: str = "LOW"; active: bool = False


class WorkflowOut(WorkflowCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str; tenant_id: str; approved_by: str | None; created_at: datetime


class SourceUpdateCreate(BaseModel):
    source_id: str; proposed_version_id: str; detected_by: str = "MANUAL"
    content_hash: str | None = None; change_summary: str = ""


class SourceUpdateReviewIn(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    note: str = ""


class SourceUpdateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str; source_id: str; proposed_version_id: str; detected_by: str; content_hash: str | None
    change_summary: str; status: str; submitted_by: str; reviewer_id: str | None
    review_note: str; created_at: datetime; reviewed_at: datetime | None
