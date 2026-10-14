"""Workpapers: a client job file that gathers the answers, drafts and
documents behind a piece of work, with a maker-checker sign-off.

Created by migration s8l9m0n1o2p3_workpapers; both tables are tenant
isolated by RLS like every other tenant table.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

WORKPAPER_STATUSES = ("open", "in_review", "signed_off")
ITEM_KINDS = ("saved_answer", "draft", "document")


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Workpaper(Base):
    __tablename__ = "workpapers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    engagement_id: Mapped[str | None] = mapped_column(ForeignKey("engagements.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    signed_off_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class WorkpaperItem(Base):
    __tablename__ = "workpaper_items"
    __table_args__ = (UniqueConstraint("workpaper_id", "kind", "item_id", name="uq_workpaper_item"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    workpaper_id: Mapped[str] = mapped_column(ForeignKey("workpapers.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    added_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
