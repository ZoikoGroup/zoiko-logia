import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ModelDefinition(Base):
    __tablename__ = "model_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[str] = mapped_column(String, nullable=False, default="Staging")
    version: Mapped[str] = mapped_column(String, nullable=False, default="v0.1")
    status: Mapped[str] = mapped_column(String, nullable=False, default="Testing")
    provider: Mapped[str] = mapped_column(String, nullable=False, default="mock")
    deployment_region: Mapped[str] = mapped_column(String, nullable=False, default="")
    permitted_data_classes: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: ["PUBLIC"]
    )
    supported_task_types: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: ["general_question"]
    )
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    retention_policy: Mapped[str] = mapped_column(String, nullable=False, default="UNREVIEWED")
    training_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evaluation_manifest_id: Mapped[str | None] = mapped_column(String, nullable=True)
    policy_version: Mapped[str] = mapped_column(String, nullable=False, default="f7.1")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelRun(Base):
    """Privacy-minimised immutable record of a gateway routing decision."""

    __tablename__ = "model_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    deployment_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_definitions.id"), nullable=True
    )
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    data_classification: Mapped[str] = mapped_column(String, nullable=False)
    processing_region: Mapped[str] = mapped_column(String, nullable=False, default="")
    prompt_id: Mapped[str] = mapped_column(String, nullable=False, default="inline")
    prompt_version: Mapped[str] = mapped_column(String, nullable=False, default="inline")
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    retrieval_version: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_versions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    requested_tools: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    attempts: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False, default="v1.0")
    status: Mapped[str] = mapped_column(String, nullable=False, default="PendingReview")
    mode: Mapped[str] = mapped_column(String, nullable=False, default="Workflow")
    submitted_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
