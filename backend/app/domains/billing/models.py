"""Billing records: the versioned plan / rate card, credits and metering
disputes, and closed statements. All tenant isolated by RLS
(migration w2p3q4r5s6t7).

Money is stored in integer cents; quantities as floats in each meter's unit.
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


class BillingPlan(Base):
    """One version of a tenant's plan and rate card. Proposed by an Admin,
    active only once a different Admin approves it; the previous active
    version is then superseded, never edited."""
    __tablename__ = "billing_plans"
    __table_args__ = (UniqueConstraint("tenant_id", "version", name="uq_billing_plan_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposed")  # proposed | active | superseded | rejected
    name: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    commitment_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    included: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)   # meter -> included quantity
    rates: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)      # meter -> cents per unit
    soft_budget_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hard_cap_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effective_from: Mapped[str] = mapped_column(String, nullable=False)          # YYYY-MM
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proposed_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    decided_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingAdjustment(Base):
    """A credit (needs a second Admin's approval to count) or a metering
    dispute (excludes that meter's charge for the period while open)."""
    __tablename__ = "billing_adjustments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM
    kind: Mapped[str] = mapped_column(String, nullable=False)    # credit | dispute
    meter: Mapped[str | None] = mapped_column(String, nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # credit: pending|approved|rejected; dispute: open|accepted|rejected
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    decided_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class BillingStatement(Base):
    """A closed month: an immutable snapshot of its usage, charges, credits
    and the plan version used. Payment is recorded, not processed."""
    __tablename__ = "billing_statements"
    __table_args__ = (UniqueConstraint("tenant_id", "period", name="uq_billing_statement_period"),
                      UniqueConstraint("tenant_id", "ref", name="uq_billing_statement_ref"))

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String, nullable=False)     # INV-2026-001
    period: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM
    currency: Mapped[str] = mapped_column(String, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    lines: Mapped[list] = mapped_column(JSON, nullable=False)
    subtotal_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="issued")  # issued | paid
    issued_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_reference: Mapped[str] = mapped_column(String, nullable=False, default="")
