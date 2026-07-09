from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


class EvaluationDataset(Base):
    """Represents a governed set of evaluation/benchmarking test cases."""
    __tablename__ = "evaluation_datasets"

    id = Column(String, primary_key=True, index=True)
    version = Column(String, nullable=False)
    status = Column(String, default="ACTIVE")  # PROPOSED, ACTIVE, RETIRED, QUARANTINED
    domain = Column(String, nullable=False)    # accounting, tax, safety, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    cases = relationship("BenchmarkCase", back_populates="dataset", cascade="all, delete-orphan")


class BenchmarkCase(Base):
    """An individual test case (prompt + reference gold answer)."""
    __tablename__ = "benchmark_cases"

    id = Column(String, primary_key=True, index=True)
    dataset_id = Column(String, ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), nullable=False)
    query_text = Column(String, nullable=False)
    gold_answer = Column(String, nullable=False)
    source_refs = Column(JSON, nullable=True)     # list of expected source_version_ids
    risk_scope = Column(String, nullable=False)    # LOW, MEDIUM, HIGH, RESTRICTED
    jurisdiction = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    dataset = relationship("EvaluationDataset", back_populates="cases")


class ThresholdSet(Base):
    """Ratified pass/fail thresholds coupled to specific dataset versions."""
    __tablename__ = "threshold_sets"

    id = Column(String, primary_key=True, index=True)
    dataset_id = Column(String, nullable=False)
    dataset_version_id = Column(String, nullable=False)
    metrics = Column(JSON, nullable=False)             # dict: metric_name -> threshold_value
    zero_tolerance_metrics = Column(JSON, nullable=True)# list: metrics requiring 100% pass (e.g. pii_leak)
    owner = Column(String, nullable=False)
    approver = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class EvaluationRun(Base):
    """Logs the execution of an evaluation suite run."""
    __tablename__ = "evaluation_runs"

    id = Column(String, primary_key=True, index=True)
    dataset_id = Column(String, nullable=False)
    threshold_set_id = Column(String, nullable=False)
    config_hash = Column(String, nullable=False)       # Hash of settings/prompts under evaluation
    status = Column(String, default="RUNNING")         # RUNNING, COMPLETED, FAILED
    metrics_summary = Column(JSON, nullable=True)      # dict: metric -> value
    created_at = Column(DateTime, default=datetime.utcnow)

    result_pack = relationship("ResultPack", back_populates="run", uselist=False, cascade="all, delete-orphan")


class ResultPack(Base):
    """The canonical packaging of evaluation execution evidence."""
    __tablename__ = "result_packs"

    id = Column(String, primary_key=True, index=True)
    run_id = Column(String, ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False)
    exact_config_hash = Column(String, nullable=False)
    contamination_scan_status = Column(String, default="PASSED") # PASSED, FAILED
    zero_tolerance_passed = Column(Boolean, default=True)
    promotion_eligible = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("EvaluationRun", back_populates="result_pack")
    authorizations = relationship("PromotionAuthorization", back_populates="result_pack", cascade="all, delete-orphan")


class PromotionAuthorization(Base):
    """Audited sign-off of a validated ResultPack for production release."""
    __tablename__ = "promotion_authorizations"

    id = Column(String, primary_key=True, index=True)
    result_pack_id = Column(String, ForeignKey("result_packs.id", ondelete="CASCADE"), nullable=False)
    decision = Column(String, nullable=False)          # APPROVED, REJECTED
    approver_id = Column(String, nullable=False)
    residual_risk_accepted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    result_pack = relationship("ResultPack", back_populates="authorizations")
