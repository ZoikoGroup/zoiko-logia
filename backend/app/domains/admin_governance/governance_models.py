"""WF-01 platform release-governance records (ZL-WF-GAP-01): document
authority (A1), and server-derived release verdicts.

Platform-scoped, not tenant-scoped (decision D3, docs/wf01-decision-action-
plan-2026-11-03.md): these records hold metadata and hashes only, never tenant
financial content. Decisions and evidence are append-only and hash-bound;
the database refuses UPDATE/DELETE on them (migration g2a3b4c5d6e7). Every
write carries an idempotency key, and records that change state carry a
revision for compare-and-swap.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthorityDocument(Base):
    """A controlled document as the register records it. canonical_id is set
    only for a single, unshared declared identifier, or by a ratified change
    request; otherwise it is null and `state` says why (COLLISION_UNRESOLVED,
    MULTIPLE_DECLARED_IDS, ID_NOT_FOUND, EVIDENCE_UNAVAILABLE_IN_REPO)."""
    __tablename__ = "authority_documents"
    __table_args__ = (UniqueConstraint("canonical_id", name="uq_authority_canonical_id"),
                      UniqueConstraint("record_key", name="uq_authority_record_key"))

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    record_key: Mapped[str] = mapped_column(String, nullable=False)          # path, or "ref:<id>" for an unavailable one
    canonical_id: Mapped[str | None] = mapped_column(String, nullable=True)
    family: Mapped[str] = mapped_column(String, nullable=False, default="")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    declared_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String, nullable=False, default="register")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    register_version: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class AuthorityAlias(Base):
    """A legacy identifier and what it points to in one family. An alias with
    more than one referent stays ambiguous: resolve() refuses to pick one."""
    __tablename__ = "authority_aliases"
    __table_args__ = (UniqueConstraint("alias", "family", "record_key", name="uq_authority_alias"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    alias: Mapped[str] = mapped_column(String, nullable=False, index=True)
    family: Mapped[str] = mapped_column(String, nullable=False, default="")
    record_key: Mapped[str | None] = mapped_column(String, nullable=True)    # null: referent text not available
    described_as: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(String, nullable=False)                # DECLARED / COLLISION_UNRESOLVED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class AuthorityChangeRequest(Base):
    """Append-only. A Document Control proposal (authority.propose) and, as a
    separate later row, its ratification by a different person
    (authority.ratify). Applying a resolution needs both."""
    __tablename__ = "authority_change_requests"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_authority_change_idempotency"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String, nullable=False)                 # PROPOSAL / RATIFICATION / REJECTION
    proposal_id: Mapped[str | None] = mapped_column(String, nullable=True)    # for RATIFICATION / REJECTION
    legacy_id: Mapped[str] = mapped_column(String, nullable=False)
    mapping: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # {record_key: new canonical id}
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_role: Mapped[str] = mapped_column(String, nullable=False)
    expected_revisions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_sha256: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class GapOwnershipDecision(Base):
    """Append-only. Which wireframe is the primary owner of each gap, as
    adopted (decision D1) and, separately, as ratified. Adoption by the
    product owner is not ratification by Document Control/Chief Architect."""
    __tablename__ = "gap_ownership_decisions"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_gap_ownership_idempotency"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(String, nullable=False)               # ADOPTED_PENDING_RATIFICATION / RATIFIED
    allocation: Mapped[dict] = mapped_column(JSON, nullable=False)            # {"G01": "WF-01", ...}
    basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ReleaseVerdict(Base):
    """Append-only. A verdict the server derived from the evidence at the time:
    each gate's state and the hashes it was computed from. GO only when every
    gate is SATISFIED; the UI and API cannot set it."""
    __tablename__ = "release_verdicts"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_release_verdict_idempotency"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)              # GO / NO_GO
    gates: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String, nullable=False)
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
