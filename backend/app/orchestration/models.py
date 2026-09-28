"""
Orchestration domain models — ZL-ENG-02 §11.

Persisted objects for HUMAN_REVIEW and SECURITY_INCIDENT routes.
These must be written to the database before the response is returned.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, JSON, String, Text, DateTime, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReviewCase(Base):
    """
    Persisted human review object — §11.1.
    Created whenever route == HUMAN_REVIEW; returning the label without
    a persisted object is non-compliant per §8.1.
    """
    __tablename__ = "review_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    query_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    confidence_state: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    assigned_queue: Mapped[str] = mapped_column(String, nullable=False, default="accounting_review")
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    policy_version: Mapped[str] = mapped_column(String, nullable=False, default="pm_1.0")
    classifier_version: Mapped[str] = mapped_column(String, nullable=False, default="rc_1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Reviewer-facing columns added by migration k0e1f2g3h4i5 (query_text and
    # review_note are NOT NULL there). Mapped here so every insert supplies them.
    query_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reviewer_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvidenceBundleManifest(Base):
    """Immutable replay record for one released retrieval decision."""

    __tablename__ = "evidence_bundle_manifests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    query_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    retrieval_plan: Mapped[dict] = mapped_column(JSON, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    index_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EvidenceBundleEntry(Base):
    __tablename__ = "evidence_bundle_entries"
    __table_args__ = (
        UniqueConstraint(
            "bundle_id", "source_version_id", "passage_id", "disposition",
            name="uq_evidence_bundle_entry",
        ),
        CheckConstraint(
            "disposition IN ('selected','excluded')",
            name="ck_evidence_bundle_entry_disposition",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    bundle_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_bundle_manifests.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    source_version_id: Mapped[str] = mapped_column(String, nullable=False)
    passage_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    disposition: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieval_method: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, default="")


def _prevent_bundle_mutation(_mapper, _connection, _target) -> None:
    raise ValueError("Evidence bundle manifests and entries are append-only")


for _bundle_model in (EvidenceBundleManifest, EvidenceBundleEntry):
    event.listen(_bundle_model, "before_update", _prevent_bundle_mutation)
    event.listen(_bundle_model, "before_delete", _prevent_bundle_mutation)
