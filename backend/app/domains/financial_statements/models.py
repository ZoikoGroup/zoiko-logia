"""Stored trial-balance intake (Document 04 §11 data contracts).

fs_trial_balances keeps the original bytes and their SHA-256 (never
modified), the parsed lines and findings; a corrected upload is a new row
that supersedes the old one (SD-010, SD-042). Mapping decisions, journal
proposals, supporting records, approved snapshots and the event history are
separate rows, so every decision is kept with who made it and when.
Amounts are stored as exact decimal strings.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FsTrialBalance(Base):
    __tablename__ = "fs_trial_balances"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    original: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="TRIAL_BALANCE")
    units: Mapped[str] = mapped_column(String, nullable=False, default="units")
    sign_convention: Mapped[str] = mapped_column(String, nullable=False, default="DEBIT_CREDIT_COLUMNS")
    period_end: Mapped[str] = mapped_column(String, nullable=False, default="")
    sheets: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    integrity: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    lines: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("fs_trial_balances.id"), nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FsMappingDecision(Base):
    __tablename__ = "fs_mapping_decisions"
    __table_args__ = (UniqueConstraint("trial_balance_id", "account_key", name="uq_fs_mapping_account"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    trial_balance_id: Mapped[str] = mapped_column(ForeignKey("fs_trial_balances.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    account_key: Mapped[str] = mapped_column(String, nullable=False)
    account_name: Mapped[str] = mapped_column(String, nullable=False)
    balance: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    line_id: Mapped[str | None] = mapped_column(String, nullable=True)
    candidates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_required: Mapped[str] = mapped_column(Text, nullable=False, default="")
    basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    allocations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_ref: Mapped[str] = mapped_column(String, nullable=False, default="")
    source: Mapped[str] = mapped_column(String, nullable=False, default="")
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FsJournal(Base):
    __tablename__ = "fs_journals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    trial_balance_id: Mapped[str] = mapped_column(ForeignKey("fs_trial_balances.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    correction_type: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    lines: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    review_status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING_REVIEW")
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posting_status: Mapped[str] = mapped_column(String, nullable=False, default="NOT_POSTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FsSupportingRecord(Base):
    __tablename__ = "fs_supporting_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    trial_balance_id: Mapped[str] = mapped_column(ForeignKey("fs_trial_balances.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    total: Mapped[str | None] = mapped_column(String, nullable=True)
    basis: Mapped[str] = mapped_column(String, nullable=False, default="")
    finding: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FsSnapshot(Base):
    __tablename__ = "fs_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    trial_balance_id: Mapped[str] = mapped_column(ForeignKey("fs_trial_balances.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    line_totals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    preparer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    approver_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="APPROVED")
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FsEvent(Base):
    __tablename__ = "fs_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    trial_balance_id: Mapped[str] = mapped_column(ForeignKey("fs_trial_balances.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
