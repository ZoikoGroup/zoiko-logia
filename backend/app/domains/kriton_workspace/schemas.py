from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SavedAnswerCreateRequest(BaseModel):
    query_id: str
    query_text: str
    answer_text: str
    risk_level: str
    tags: list[str] = []


class SavedAnswerPublic(BaseModel):
    id: str
    query_id: str
    query_text: str
    answer_text: str
    risk_level: str
    tags: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class SavedVisualizationCreateRequest(BaseModel):
    query_id: str = Field(max_length=200)
    visualization_type: Literal["chart", "graph", "diagram", "presentation_chart"]
    schema_version: str = Field(default="1.0", max_length=20)
    title: str = Field(max_length=200)
    summary: str = Field(default="", max_length=2000)
    # Opaque here — the service layer round-trips it through the matching
    # renderer schema (CalculationWidget/PresentationGraph/PresentationGuide/
    # PresentationChart, picked by visualization_type) so only fields those
    # schemas actually define ever reach storage, and applies the same
    # node/edge/point count limits the live renderers enforce (a client
    # posting directly to this endpoint isn't bound by whatever the original
    # answer actually contained, so those limits have to be re-checked here
    # too).
    payload: dict
    source_references: list[str] = Field(default_factory=list, max_length=50)


class SavedVisualizationPublic(BaseModel):
    id: str
    query_id: str
    visualization_type: str
    schema_version: str
    title: str
    summary: str
    payload: dict
    source_references: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DraftCreateRequest(BaseModel):
    title: str
    content: str = ""
    saved_answer_id: str | None = None


class DraftUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    status: str | None = None


class DraftPublic(BaseModel):
    id: str
    title: str
    content: str
    status: str
    saved_answer_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
