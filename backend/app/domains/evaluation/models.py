from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, JSON, Float, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvaluationDataset(Base):
    """Represents a governed set of evaluation/benchmarking test cases."""
    __tablename__ = "evaluation_datasets"

    id = Column(String, primary_key=True, index=True)
    version = Column(String, nullable=False)
    status = Column(String, default="ACTIVE")  # PROPOSED, ACTIVE, RETIRED, QUARANTINED
    domain = Column(String, nullable=False)    # accounting, tax, safety, etc.
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    tenant_id = Column(String, nullable=False, default="GLOBAL_CONTROL", index=True)
    split = Column(String, nullable=False, default="development")
    frozen = Column(Boolean, nullable=False, default=False)
    frozen_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, nullable=True)

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
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    task_context = Column(JSON, nullable=False, default=dict)
    expected_claims = Column(JSON, nullable=False, default=list)
    expected_calculations = Column(JSON, nullable=False, default=list)
    acceptable_statuses = Column(JSON, nullable=False, default=lambda: ["answered"])
    critical_error_types = Column(JSON, nullable=False, default=list)
    document_family = Column(String, nullable=True)
    language = Column(String, nullable=False, default="en")
    reviewer_provenance = Column(String, nullable=True)
    fingerprint = Column(String, nullable=False, default="", index=True)

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
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    tenant_id = Column(String, nullable=False, default="GLOBAL_CONTROL", index=True)
    status = Column(String, nullable=False, default="PendingReview")
    submitted_by = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)


class EvaluationRun(Base):
    """Logs the execution of an evaluation suite run."""
    __tablename__ = "evaluation_runs"

    id = Column(String, primary_key=True, index=True)
    dataset_id = Column(String, nullable=False)
    threshold_set_id = Column(String, nullable=False)
    config_hash = Column(String, nullable=False)       # Hash of settings/prompts under evaluation
    status = Column(String, default="RUNNING")         # RUNNING, COMPLETED, FAILED
    metrics_summary = Column(JSON, nullable=True)      # dict: metric -> value
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    tenant_id = Column(String, nullable=False, default="GLOBAL_CONTROL", index=True)
    started_by = Column(String, nullable=True)
    candidate_manifest = Column(JSON, nullable=False, default=dict)
    case_count = Column(Integer, nullable=False, default=0)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failure_reason = Column(Text, nullable=True)

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
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    failure_reports = Column(JSON, nullable=False, default=list)
    slice_metrics = Column(JSON, nullable=False, default=dict)
    reviewed_case_count = Column(Integer, nullable=False, default=0)
    expected_case_count = Column(Integer, nullable=False, default=0)
    complete = Column(Boolean, nullable=False, default=False)

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
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    result_pack = relationship("ResultPack", back_populates="authorizations")


class EvaluationCaseResult(Base):
    """Observed output and trace for one real candidate execution."""

    __tablename__ = "evaluation_case_results"

    id = Column(String, primary_key=True, index=True)
    run_id = Column(String, ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id = Column(String, ForeignKey("benchmark_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    response_status = Column(String, nullable=False)
    response_payload = Column(JSON, nullable=False, default=dict)
    trace = Column(JSON, nullable=False, default=dict)
    latency_seconds = Column(Float, nullable=False)
    source_recall = Column(Float, nullable=True)
    citation_precision = Column(Float, nullable=True)
    numeric_correctness = Column(Float, nullable=True)
    error_code = Column(String, nullable=True)
    review_status = Column(String, nullable=False, default="PENDING")
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class ReviewerJudgment(Base):
    """Human assessment; the candidate output is never scored from gold text alone."""

    __tablename__ = "evaluation_reviewer_judgments"

    id = Column(String, primary_key=True, index=True)
    case_result_id = Column(
        String, ForeignKey("evaluation_case_results.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_id = Column(String, nullable=False)
    verdict = Column(String, nullable=False)  # ACCEPT, REJECT, ABSTENTION_ACCEPTABLE
    metric_scores = Column(JSON, nullable=False, default=dict)
    critical_errors = Column(JSON, nullable=False, default=list)
    notes = Column(Text, nullable=True)
    adjudication = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
