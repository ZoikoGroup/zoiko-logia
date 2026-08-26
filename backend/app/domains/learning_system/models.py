import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryItem(Base):
    __tablename__ = "kriton_memory_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("mem"))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False, default="USER")
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_feedback_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "key", name="uq_kriton_memory_owner_key"),)


class FeedbackItem(Base):
    __tablename__ = "kriton_feedback_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("fb"))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    query_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    feedback_type: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    correction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LearningCandidate(Base):
    __tablename__ = "kriton_learning_candidates"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("learn"))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    feedback_id: Mapped[str] = mapped_column(ForeignKey("kriton_feedback_items.id"), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING", index=True)
    reviewer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    benchmark_case_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowDefinition(Base):
    __tablename__ = "kriton_workflow_definitions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("wf"))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, default="GLOBAL_CONTROL", index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    match_terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    plan: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    allowed_formats: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    risk_level: Mapped[str] = mapped_column(String, nullable=False, default="LOW")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("tenant_id", "name", "version", name="uq_kriton_workflow_version"),)


class SourceUpdateReview(Base):
    __tablename__ = "kriton_source_update_reviews"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("srcupd"))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    proposed_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), nullable=False)
    detected_by: Mapped[str] = mapped_column(String, nullable=False, default="MANUAL")
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING", index=True)
    submitted_by: Mapped[str] = mapped_column(String, nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
