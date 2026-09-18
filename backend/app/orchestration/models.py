"""
Orchestration domain models — ZL-ENG-02 §11.

Persisted objects for HUMAN_REVIEW and SECURITY_INCIDENT routes.
These must be written to the database before the response is returned.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, String, DateTime, Text
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
    # Vestigial DB column carried over from an earlier schema — same situation
    # as EscalationCase.tenant_id (see risk_safety/models.py). Databases created
    # before this model dropped the field still have review_cases.query_text as
    # NOT NULL, and create_all never alters an existing table, so every insert
    # from a model without it raised NotNullViolationError and 500'd the whole
    # request on the HUMAN_REVIEW route. Declaring it with a Python-side default
    # satisfies the constraint whatever state the DB is in, and the reviewer
    # gets the question rather than an empty cell.
    query_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    confidence_state: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    assigned_queue: Mapped[str] = mapped_column(String, nullable=False, default="accounting_review")
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    policy_version: Mapped[str] = mapped_column(String, nullable=False, default="pm_1.0")
    classifier_version: Mapped[str] = mapped_column(String, nullable=False, default="rc_1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
