"""
Orchestration domain models — ZL-ENG-02 §11.

Persisted objects for HUMAN_REVIEW and SECURITY_INCIDENT routes.
These must be written to the database before the response is returned.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, String, DateTime
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
