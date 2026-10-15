"""Administration records: teams, access reviews, tenant policy (with its
staged change requests) and release candidates.

Every table is tenant isolated by RLS (migration t9m0n1o2p3q4).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Team(Base):
    """A named group of people with an accountable owner. Membership never
    grants permissions by itself; roles and engagement grants do."""
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_team_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    owner_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    added_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class AccessReview(Base):
    """One recertification of one person's role (Privacy & Security §5:
    quarterly, monthly for privileged roles). Never by the person reviewed."""
    __tablename__ = "access_reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)  # certified | role_changed | deactivated
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reviewer_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class TenantPolicy(Base):
    """A tenant's applied value for a setting it may tighten (never loosen)
    below the deployment's own value."""
    __tablename__ = "tenant_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_tenant_policy_key"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)  # {"v": <bool|int>}
    change_request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class SettingChangeRequest(Base):
    """A staged change to a tenant setting; it takes effect only when a second
    Admin approves it."""
    __tablename__ = "setting_change_requests"
    __table_args__ = (UniqueConstraint("tenant_id", "ref", name="uq_setting_change_ref"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String, nullable=False)  # CHG-001
    key: Mapped[str] = mapped_column(String, nullable=False)
    current_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    proposed_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending | applied | rejected | withdrawn
    requested_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    decided_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ReleaseCandidate(Base):
    """A change on its way to production and the evidence for each mandatory
    gate. Some gates are measured live; the rest are recorded with evidence."""
    __tablename__ = "release_candidates"
    __table_args__ = (UniqueConstraint("tenant_id", "ref", name="uq_release_candidate_ref"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String, nullable=False)  # REL-001
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    component: Mapped[str] = mapped_column(String, nullable=False)
    change_ref: Mapped[str] = mapped_column(String, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    owner_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="validating")
    gates: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    approved_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
