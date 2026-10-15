"""Operations records: measured health history, operational alerts and the
provider / integration registers.

service_health_samples is platform telemetry (no tenant data) and is shared;
every other table is tenant isolated by RLS (migration s8l9m0n1o2p3).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ServiceHealthSample(Base):
    """One measured check of one dependency (or the API's own latency)."""
    __tablename__ = "service_health_samples"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    service_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    state: Mapped[str] = mapped_column(String, nullable=False)  # operational | down | not_configured
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    # API samples only: p50 of the window, request and server-error counts.
    p50_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    errors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(String, nullable=False, default="")


class ServiceOwner(Base):
    """The accountable owner a tenant's Admin assigned to a monitored service."""
    __tablename__ = "service_owners"
    __table_args__ = (UniqueConstraint("tenant_id", "service_key", name="uq_service_owner"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    service_key: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class OperationsAlert(Base):
    """An operational alert: raised automatically from a live condition (a
    governance exception, a service that is down) or by hand, then worked
    through acknowledge → investigate → contain → resolve."""
    __tablename__ = "operations_alerts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ref", name="uq_operations_alert_ref"),
        UniqueConstraint("tenant_id", "source_key", name="uq_operations_alert_source"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String, nullable=False)  # ALT-2026-0001
    # Stable key of the condition ("gov:esc-overdue", "health:searxng") or
    # "manual:<id>"; one alert row per condition, reopened if it recurs.
    source_key: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False)  # governance | health | manual
    category: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)  # Critical | High | Medium | Low
    title: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    href: Mapped[str] = mapped_column(String, nullable=False, default="")
    service_key: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="unacknowledged")
    owner_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class ProviderRecord(Base):
    """Provider Due Diligence Register entry (ZL-T0-12): an external AI,
    cloud, content or service provider and its assurance gates."""
    __tablename__ = "provider_records"
    __table_args__ = (UniqueConstraint("tenant_id", "ref", name="uq_provider_record_ref"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String, nullable=False)  # PRV-001
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)  # ai_model | cloud_security | content | other
    service: Mapped[str] = mapped_column(String, nullable=False, default="")
    # Links the record to a provider this deployment is configured for.
    config_key: Mapped[str | None] = mapped_column(String, nullable=True)
    decision: Mapped[str] = mapped_column(String, nullable=False, default="under_review")
    criticality: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    region: Mapped[str] = mapped_column(String, nullable=False, default="")
    approved_use: Mapped[str] = mapped_column(String, nullable=False, default="")
    data_classification: Mapped[str] = mapped_column(String, nullable=False, default="")
    contract_state: Mapped[str] = mapped_column(String, nullable=False, default="none")
    owner_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gates: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    decided_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class IntegrationRecord(Base):
    """A governed connection: what it may access, in which direction, under
    whose authorization, and whether it is healthy."""
    __tablename__ = "integration_records"
    __table_args__ = (UniqueConstraint("tenant_id", "ref", name="uq_integration_record_ref"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String, nullable=False)  # INT-001
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)  # accounting | ai_tools | evidence | source_feeds | infrastructure
    provider_id: Mapped[str | None] = mapped_column(String, ForeignKey("provider_records.id"), nullable=True)
    # A live health check this connection is tied to (operations/service.py keys).
    health_key: Mapped[str | None] = mapped_column(String, nullable=True)
    authorization: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    data_flow: Mapped[str] = mapped_column(String, nullable=False, default="inbound")
    region: Mapped[str] = mapped_column(String, nullable=False, default="")
    risk_tier: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    auth_method: Mapped[str] = mapped_column(String, nullable=False, default="")
    scopes_requested: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scopes_approved: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    owner_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    gates: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    decided_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
