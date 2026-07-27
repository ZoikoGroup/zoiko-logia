from datetime import datetime

from pydantic import BaseModel


class ChatMessagePublic(BaseModel):
    id: str
    role: str
    content: str
    route: str | None
    risk_level: str | None
    citations: list[dict] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationSummary(BaseModel):
    """Sidebar list entry — no message bodies, kept light for a list call."""
    id: str
    title: str
    jurisdiction: str
    mode: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetail(ConversationSummary):
    messages: list[ChatMessagePublic]


class ConversationRenameRequest(BaseModel):
    title: str
