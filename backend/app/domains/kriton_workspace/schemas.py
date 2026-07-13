from datetime import datetime

from pydantic import BaseModel


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
