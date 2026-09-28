from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


# ─── Benchmark Case Schemas ────────────────────────────────────────────────
class BenchmarkCaseBase(BaseModel):
    id: str
    query_text: str
    gold_answer: str
    source_refs: Optional[List[str]] = None
    risk_scope: str
    jurisdiction: Optional[str] = None
    task_context: Dict[str, Any] = Field(default_factory=dict)
    expected_claims: List[str] = Field(default_factory=list)
    expected_calculations: List[Dict[str, Any]] = Field(default_factory=list)
    acceptable_statuses: List[str] = Field(default_factory=lambda: ["answered"])
    critical_error_types: List[str] = Field(default_factory=list)
    document_family: Optional[str] = None
    language: str = "en"
    reviewer_provenance: Optional[str] = None


class BenchmarkCaseCreate(BenchmarkCaseBase):
    pass


class BenchmarkCaseOut(BenchmarkCaseBase):
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── Evaluation Dataset Schemas ─────────────────────────────────────────────
class EvaluationDatasetCreate(BaseModel):
    id: str
    version: str
    status: Optional[str] = "ACTIVE"
    domain: str
    cases: List[BenchmarkCaseCreate]
    split: str = "development"
    frozen: bool = False


class EvaluationDatasetOut(BaseModel):
    id: str
    version: str
    status: str
    domain: str
    created_at: datetime
    cases: List[BenchmarkCaseOut]
    split: str = "development"
    frozen: bool = False

    model_config = ConfigDict(from_attributes=True)


# ─── Threshold Set Schemas ──────────────────────────────────────────────────
class ThresholdSetCreate(BaseModel):
    id: str
    dataset_id: str
    dataset_version_id: str
    metrics: Dict[str, Any] = Field(
        ...,
        description="Dictionary of target metrics, e.g., {'latency_p95': 2.5, 'citation_precision': 0.95}"
    )
    zero_tolerance_metrics: Optional[List[str]] = Field(
        None,
        description="List of metrics where any failure blocks release (e.g., ['pii_leak', 'restricted_block_rate'])"
    )
    # Deprecated compatibility fields. Ownership and approval are derived
    # from authenticated identities by the API.
    owner: str = ""
    approver: str = ""


class ThresholdSetOut(ThresholdSetCreate):
    created_at: datetime
    status: str = "PendingReview"
    submitted_by: Optional[str] = None
    approved_by: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ─── Evaluation Run Schemas ─────────────────────────────────────────────────
class EvaluationRunCreate(BaseModel):
    dataset_id: str
    threshold_set_id: str
    config_hash: str
    candidate_manifest: Dict[str, Any]


class EvaluationRunOut(BaseModel):
    id: str
    dataset_id: str
    threshold_set_id: str
    config_hash: str
    status: str
    metrics_summary: Optional[Dict[str, Any]] = None
    created_at: datetime
    case_count: int = 0
    failure_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ─── Result Pack Schemas ────────────────────────────────────────────────────
class ResultPackOut(BaseModel):
    id: str
    run_id: str
    exact_config_hash: str
    contamination_scan_status: str
    zero_tolerance_passed: bool
    promotion_eligible: bool
    created_at: datetime
    failure_reports: List[Dict[str, Any]] = Field(default_factory=list)
    slice_metrics: Dict[str, Any] = Field(default_factory=dict)
    reviewed_case_count: int = 0
    expected_case_count: int = 0
    complete: bool = False

    model_config = ConfigDict(from_attributes=True)


# ─── Promotion Request & Authorization Schemas ─────────────────────────────
class PromotionRequest(BaseModel):
    result_pack_id: str
    decision: str  # APPROVED, REJECTED
    # Deprecated compatibility field. The API always derives the approver from
    # the authenticated identity and ignores client-supplied values.
    approver_id: Optional[str] = None
    residual_risk_accepted: Optional[bool] = False


class PromotionAuthorizationOut(BaseModel):
    id: str
    result_pack_id: str
    decision: str
    approver_id: str
    residual_risk_accepted: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewerJudgmentCreate(BaseModel):
    verdict: Literal["ACCEPT", "REJECT", "ABSTENTION_ACCEPTABLE"]
    metric_scores: Dict[str, float] = Field(default_factory=dict)
    critical_errors: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    adjudication: bool = False


class ReviewerJudgmentOut(ReviewerJudgmentCreate):
    id: str
    case_result_id: str
    reviewer_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvaluationCaseResultOut(BaseModel):
    id: str
    run_id: str
    case_id: str
    response_status: str
    response_payload: Dict[str, Any]
    trace: Dict[str, Any]
    latency_seconds: float
    source_recall: Optional[float]
    citation_precision: Optional[float]
    numeric_correctness: Optional[float]
    error_code: Optional[str]
    review_status: str

    model_config = ConfigDict(from_attributes=True)
