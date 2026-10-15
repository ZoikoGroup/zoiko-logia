"""Review, Escalation & Audit console records.

audit_export_requests is tenant isolated by RLS (migration u0n1o2p3q4r5).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditExportRequest(Base):
    """A request to export audit events. Nothing leaves the platform until a
    different Admin approves it, and an approved export expires."""
    __tablename__ = "audit_export_requests"
    __table_args__ = (UniqueConstraint("tenant_id", "ref", name="uq_audit_export_ref"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String, nullable=False)  # EXP-001
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending | approved | rejected
    requested_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    decided_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
