"""
Audit Logging & Evidence Ledger domain — ORM models.

Implements the append-only evidence ledger defined in the ZL-T0-07
"Audit Logging & Evidence Ledger" wireframe:
  • AuditEvent          — canonical, chain-hashed audit event envelope (Section 4)
  • CompensatingEvent   — governed correction; never mutates the original row (Section 5)
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _event_id() -> str:
    return f"evt-{uuid.uuid4().hex[:16]}"


def _compensating_id() -> str:
    return f"cev-{uuid.uuid4().hex[:16]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuditEvent(Base):
    """Append-only ledger entry. Corrections happen through CompensatingEvent,
    never by mutating a row here (Section 2 / Section 6)."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_event_id)
    event_name: Mapped[str] = mapped_column(String, nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(String, nullable=False, default="1.0")
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    emitting_service: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, default="GLOBAL_CONTROL", index=True)
    actor_type: Mapped[str] = mapped_column(String, nullable=False, default="user")
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    subject_type: Mapped[str] = mapped_column(String, nullable=False)
    subject_id: Mapped[str] = mapped_column(String, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    causation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    previous_chain_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    chain_hash: Mapped[str] = mapped_column(String, nullable=False)
    classification: Mapped[str] = mapped_column(String, nullable=False, default="INTERNAL")
    replay_relevance: Mapped[str] = mapped_column(String, nullable=False, default="SUPPORTING")
    validation_status: Mapped[str] = mapped_column(String, nullable=False, default="ACCEPTED")
    legal_hold_id: Mapped[str | None] = mapped_column(String, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archive_ref: Mapped[str | None] = mapped_column(String, nullable=True)


class CompensatingEvent(Base):
    """Governed correction referencing an existing AuditEvent (Section 5).
    Maker-checker: the actor who issues a correction cannot also approve it."""

    __tablename__ = "compensating_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_compensating_id)
    corrects_event_id: Mapped[str] = mapped_column(ForeignKey("audit_events.id"), nullable=False)
    correction_type: Mapped[str] = mapped_column(String, nullable=False)
    is_material: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correction_reason: Mapped[str] = mapped_column(String, nullable=False)
    corrected_fields_summary: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    issued_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    approver_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    effective_for_replay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    payload_schema_version: Mapped[str] = mapped_column(String, nullable=False, default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
