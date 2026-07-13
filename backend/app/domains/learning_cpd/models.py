import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SyllabusPathway(Base):
    __tablename__ = "syllabus_pathways"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    body: Mapped[str] = mapped_column(String, nullable=False)
    qualification: Mapped[str] = mapped_column(String, nullable=False)
    module: Mapped[str] = mapped_column(String, nullable=False)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    learning_outcome: Mapped[str] = mapped_column(String, nullable=False)


class TopicMapNode(Base):
    __tablename__ = "topic_map_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    prerequisites: Mapped[str] = mapped_column(String, nullable=False, default="")
    standards_summary: Mapped[str] = mapped_column(String, nullable=False, default="")


class CPDEntry(Base):
    """A logged block of eligible learning time (ZL-T2-02 §4 CPD Timer and Log).
    Claims are ZoikoLogia-recorded evidence, not a professional-body-issued
    certificate, until a body accreditation exists."""

    __tablename__ = "cpd_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    minutes: Mapped[int] = mapped_column(nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
