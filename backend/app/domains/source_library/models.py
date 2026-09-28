import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, inspect, select, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, default="GLOBAL_CONTROL", index=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    publisher: Mapped[str] = mapped_column(String, nullable=False, default="")
    owner: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_class: Mapped[str] = mapped_column(String, nullable=False)
    jurisdiction_scope: Mapped[str] = mapped_column(String, nullable=False, default="Global")
    framework_scope: Mapped[str] = mapped_column(String, nullable=False, default="")
    # ZL-ENG-03 §5.6 Checkpoint A/B inputs — added so license_gate.py has real
    # per-source eligibility data to check, instead of only the jurisdiction/
    # status fields that already existed.
    licence_state: Mapped[str] = mapped_column(String, nullable=False, default="permitted")   # permitted | restricted | unknown
    authority_level: Mapped[str] = mapped_column(String, nullable=False, default="secondary")  # primary | secondary | internal
    is_tenant_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SourceVersion(Base):
    __tablename__ = "source_versions"
    __table_args__ = (
        Index(
            "uq_source_version_tenant_content_hash",
            "tenant_id", "content_hash",
            unique=True,
            postgresql_where=text("content_hash <> ''"),
            sqlite_where=text("content_hash <> ''"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, default="GLOBAL_CONTROL", index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    version_label: Mapped[str] = mapped_column(String, nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String, nullable=False, default="PROPOSED")
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    display_restriction: Mapped[str] = mapped_column(String, nullable=False, default="FULL")
    note: Mapped[str] = mapped_column(String, nullable=False, default="")
    submitted_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, default="", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    quality_state: Mapped[str] = mapped_column(String, nullable=False, default="UNREVIEWED")
    original_language: Mapped[str] = mapped_column(String, nullable=False, default="en")
    translation_of_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_versions.id"), nullable=True
    )
    superseded_by_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_versions.id"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class SourceRight(Base):
    """One versioned decision for one operation on an exact source version."""

    __tablename__ = "source_rights"
    __table_args__ = (
        UniqueConstraint(
            "source_version_id", "operation", "rights_version",
            name="uq_source_right_operation_version",
        ),
        CheckConstraint("decision IN ('allow', 'deny')", name="ck_source_right_decision"),
        CheckConstraint("rights_version > 0", name="ck_source_right_version_positive"),
        CheckConstraint(
            "operation IN ('ingestion','indexing','retrieval','model_transmission','display','summary','export','retention','training')",
            name="ck_source_right_operation",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String, nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String, nullable=False, default="deny")
    rights_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reason_code: Mapped[str] = mapped_column(String, nullable=False, default="RIGHT_NOT_GRANTED")
    terms_reference: Mapped[str] = mapped_column(String, nullable=False, default="")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SourcePassage(Base):
    """Stable, hash-addressed passage extracted from an immutable version."""

    __tablename__ = "source_passages"
    __table_args__ = (
        UniqueConstraint("source_version_id", "locator", name="uq_source_passage_locator"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), nullable=False, index=True)
    locator: Mapped[str] = mapped_column(String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    language: Mapped[str] = mapped_column(String, nullable=False, default="en")
    is_translation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    derived_from_passage_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_passages.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SourceRelationship(Base):
    __tablename__ = "source_relationships"
    __table_args__ = (
        UniqueConstraint(
            "from_version_id", "to_version_id", "relationship_type",
            name="uq_source_version_relationship",
        ),
        CheckConstraint(
            "relationship_type IN ('supersedes','clarifies','references','complements','conflicts','historical_only')",
            name="ck_source_relationship_type",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    from_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), nullable=False, index=True)
    to_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SourceUsage(Base):
    """Reverse index used to identify bundles/answers affected by revocation."""

    __tablename__ = "source_usages"
    __table_args__ = (
        UniqueConstraint(
            "source_version_id", "artifact_type", "artifact_id", "operation",
            name="uq_source_usage_artifact",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), nullable=False, index=True)
    passage_id: Mapped[str | None] = mapped_column(ForeignKey("source_passages.id"), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String, nullable=False)
    artifact_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


_IMMUTABLE_VERSION_FIELDS = (
    "source_id", "version_label", "content_hash", "file_path", "source_url",
    "original_language", "translation_of_version_id",
)


@event.listens_for(SourceVersion, "before_update")
def _protect_approved_version_content(_mapper, _connection, target: SourceVersion) -> None:
    """Enforce approved-content immutability on PostgreSQL and test databases."""
    state = inspect(target)
    status_history = state.attrs.status.history
    prior_status = status_history.deleted[0] if status_history.deleted else target.status
    if prior_status not in {"APPROVED", "ACTIVE"}:
        return
    changed = [field for field in _IMMUTABLE_VERSION_FIELDS if state.attrs[field].history.has_changes()]
    if changed:
        raise ValueError(f"Approved source version content is immutable: {', '.join(changed)}")


def _protect_approved_passage(_mapper, connection, target: SourcePassage) -> None:
    version_status = connection.execute(
        select(SourceVersion.status).where(SourceVersion.id == target.source_version_id)
    ).scalar_one_or_none()
    if version_status in {"APPROVED", "ACTIVE"}:
        raise ValueError("Approved source passages are immutable")


event.listen(SourcePassage, "before_update", _protect_approved_passage)
event.listen(SourcePassage, "before_delete", _protect_approved_passage)


def _protect_append_only_record(_mapper, _connection, _target) -> None:
    raise ValueError("Source rights and usage records are append-only")


event.listen(SourceRight, "before_update", _protect_append_only_record)
event.listen(SourceRight, "before_delete", _protect_append_only_record)
event.listen(SourceUsage, "before_update", _protect_append_only_record)
event.listen(SourceUsage, "before_delete", _protect_append_only_record)
