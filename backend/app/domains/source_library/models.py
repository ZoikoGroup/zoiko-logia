import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, default="GLOBAL_CONTROL", index=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source_class: Mapped[str] = mapped_column(String, nullable=False)
    jurisdiction_scope: Mapped[str] = mapped_column(String, nullable=False, default="Global")
    framework_scope: Mapped[str] = mapped_column(String, nullable=False, default="")


class SourceVersion(Base):
    __tablename__ = "source_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, default="GLOBAL_CONTROL", index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    version_label: Mapped[str] = mapped_column(String, nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String, nullable=False, default="PROPOSED")
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    display_restriction: Mapped[str] = mapped_column(String, nullable=False, default="FULL")
    note: Mapped[str] = mapped_column(String, nullable=False, default="")
    submitted_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
