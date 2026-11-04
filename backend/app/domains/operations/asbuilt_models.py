"""WF-01 A2: the requirement-to-as-built ledger (Status & Health 29).

A manifest records what the running code is: commit, whether the tree was
clean, schema head, flag names (never values), environment, the routes the
application serves and the requirement each one implements, with the tests
that cover it. Generation is engineering evidence; verification is a separate
record by a different person holding release.verify. Both are append-only
(migration g2a3b4c5d6e7). An uncommitted tree or an unpinned environment can
be recorded but never verified.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AsBuiltManifest(Base):
    __tablename__ = "asbuilt_manifests"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_asbuilt_manifest_idempotency"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    tree_clean: Mapped[bool] = mapped_column(Boolean, nullable=False)
    branch: Mapped[str] = mapped_column(String, nullable=False, default="")
    schema_head: Mapped[str] = mapped_column(String, nullable=False, default="")
    environment: Mapped[str] = mapped_column(String, nullable=False)
    flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)       # names + value hashes
    routes_total: Mapped[int] = mapped_column(nullable=False, default=0)
    content_sha256: Mapped[str] = mapped_column(String, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class AsBuiltMapping(Base):
    """One requirement mapped to the service, route and tests that implement it
    in a manifest. status: MAPPED (route and tests found), UNMAPPED (the route
    or its tests are missing). VERIFIED is never stored here."""
    __tablename__ = "asbuilt_mappings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    manifest_id: Mapped[str] = mapped_column(String, ForeignKey("asbuilt_manifests.id"), nullable=False, index=True)
    requirement_id: Mapped[str] = mapped_column(String, nullable=False)
    service: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    permission: Mapped[str] = mapped_column(String, nullable=False, default="")
    flag: Mapped[str] = mapped_column(String, nullable=False, default="")
    test_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AsBuiltVerification(Base):
    """A separate person's review of a manifest. Refused for an uncommitted
    tree, for the person who recorded it, and without release.verify."""
    __tablename__ = "asbuilt_verifications"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_asbuilt_verification_idempotency"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    manifest_id: Mapped[str] = mapped_column(String, ForeignKey("asbuilt_manifests.id"), nullable=False, index=True)
    verifier_id: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)                  # VERIFIED / REJECTED
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    manifest_sha256: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
