from datetime import datetime

from pydantic import BaseModel, field_validator


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


class DocumentPublic(BaseModel):
    id: str
    filename: str
    mime_type: str
    status: str
    processing_error: str | None
    chunk_count: int = 0
    created_at: datetime
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_validator("processing_error")
    @classmethod
    def _plain_message(cls, value: str | None) -> str | None:
        # The stored error keeps its OCR code; the user sees the plain message.
        from app.domains.kriton_workspace.ocr import public_error
        return public_error(value)[1]
