from datetime import datetime

from pydantic import BaseModel, Field


class SyllabusPathwayPublic(BaseModel):
    id: str
    body: str
    qualification: str
    module: str
    topic: str
    learning_outcome: str

    model_config = {"from_attributes": True}


class TopicMapNodePublic(BaseModel):
    id: str
    topic: str
    prerequisites: str
    standards_summary: str

    model_config = {"from_attributes": True}


class CPDEntryCreateRequest(BaseModel):
    topic: str
    minutes: int = Field(..., gt=0, le=600)
    note: str = ""


class CPDEntryPublic(BaseModel):
    id: str
    topic: str
    minutes: int
    note: str
    logged_at: datetime

    model_config = {"from_attributes": True}


class CPDSummaryOut(BaseModel):
    total_minutes: int
    total_hours: float
    entries_count: int
