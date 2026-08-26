from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AgentRunCreate(BaseModel):
    goal: str = Field(min_length=3, max_length=4000)
    document_ids: list[str] = Field(min_length=1, max_length=10)
    conversation_id: str | None = None
    output_format: Literal["xlsx"] = "xlsx"


class AgentStepPublic(BaseModel):
    id: str
    sequence: int
    decision_type: str
    tool_name: str
    status: str
    result_reference: str | None = None
    result_summary: dict = Field(default_factory=dict)
    error_code: str | None = None
    started_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class AgentArtifactPublic(BaseModel):
    id: str
    filename: str
    mime_type: str
    download_url: str


class AgentRunPublic(BaseModel):
    id: str
    goal: str
    task_type: str
    status: str
    risk_level: str
    current_step: int
    maximum_steps: int
    plan: list[str]
    error_code: str | None = None
    final_response: dict | None = None
    steps: list[AgentStepPublic] = Field(default_factory=list)
    artifacts: list[AgentArtifactPublic] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class AgentRunCancel(BaseModel):
    reason: str = Field(default="Cancelled by user", max_length=500)
