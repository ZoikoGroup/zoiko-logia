from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class EngagementCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MembershipCreate(BaseModel):
    user_id: str
    engagement_role: str = "member"
    operations: list[str] = Field(default_factory=lambda: ["ask", "document.read", "document.write", "model.transmit", "audit.replay", "export"])


class EngagementPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    status: str
    rights_version: str


class MembershipPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    engagement_id: str
    user_id: str
    engagement_role: str
    status: str
    revoked_at: datetime | None
