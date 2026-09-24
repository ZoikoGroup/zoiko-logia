import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Integer, JSON, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CalculationRun(Base):
    __tablename__ = "calculation_runs"
    __table_args__ = (
        CheckConstraint("status IN ('completed','failed')", name="ck_calculation_run_status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    query_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    rule_version: Mapped[str] = mapped_column(String, nullable=False)
    inputs: Mapped[list] = mapped_column(JSON, nullable=False)
    output_value: Mapped[str] = mapped_column(String, nullable=False)
    output_unit: Mapped[str] = mapped_column(String, nullable=False)
    rounding_mode: Mapped[str] = mapped_column(String, nullable=False)
    scale: Mapped[int] = mapped_column(Integer, nullable=False)
    chart_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def _immutable(_mapper, _connection, _target) -> None:
    raise ValueError("Completed calculation runs are immutable")


event.listen(CalculationRun, "before_update", _immutable)
event.listen(CalculationRun, "before_delete", _immutable)
