from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


# ─── Benchmark Case Schemas ────────────────────────────────────────────────
class BenchmarkCaseBase(BaseModel):
    id: str
    query_text: str
    gold_answer: str
    source_refs: Optional[List[str]] = None
    risk_scope: str
    jurisdiction: Optional[str] = None


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


class EvaluationDatasetOut(BaseModel):
    id: str
    version: str
    status: str
    domain: str
    created_at: datetime
    cases: List[BenchmarkCaseOut]

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
    owner: str
    approver: str


class ThresholdSetOut(ThresholdSetCreate):
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── Evaluation Run Schemas ─────────────────────────────────────────────────
class EvaluationRunCreate(BaseModel):
    dataset_id: str
    threshold_set_id: str
    config_hash: str


class EvaluationRunOut(BaseModel):
    id: str
    dataset_id: str
    threshold_set_id: str
    config_hash: str
    status: str
    metrics_summary: Optional[Dict[str, Any]] = None
    created_at: datetime

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

    model_config = ConfigDict(from_attributes=True)


# ─── Promotion Request & Authorization Schemas ─────────────────────────────
class PromotionRequest(BaseModel):
    result_pack_id: str
    decision: str  # APPROVED, REJECTED
    approver_id: str
    residual_risk_accepted: Optional[bool] = False


class PromotionAuthorizationOut(BaseModel):
    id: str
    result_pack_id: str
    decision: str
    approver_id: str
    residual_risk_accepted: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
