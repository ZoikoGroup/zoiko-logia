import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ModelDefinition(Base):
    __tablename__ = "model_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[str] = mapped_column(String, nullable=False, default="Staging")
    version: Mapped[str] = mapped_column(String, nullable=False, default="v0.1")
    status: Mapped[str] = mapped_column(String, nullable=False, default="Testing")
    provider: Mapped[str] = mapped_column(String, nullable=False, default="mock")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False, default="v1.0")
    status: Mapped[str] = mapped_column(String, nullable=False, default="PendingReview")
    mode: Mapped[str] = mapped_column(String, nullable=False, default="Workflow")
    submitted_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
