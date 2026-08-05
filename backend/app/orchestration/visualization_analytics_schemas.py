"""Dynamic Visualization Selection v6 — recommendation-quality reporting and
ranking-configuration governance contracts.

Two independent concerns kept in one module because they share the same
privacy posture and the same "review, never auto-activate" philosophy:
  1. Aggregation response shapes (RecommendationQualitySummaryResponse,
     ReplacementMatrixResponse, ChartTypePerformanceResponse) — every rate
     travels with its own sample_size and evidence_status so a caller can
     never render a percentage without also seeing how much data backs it.
  2. RankingConfiguration governance (RankingConfigurationCreate/Public,
     WeightAdjustmentProposal) — a versioned, human-reviewed PROPOSAL for
     presentation_dataprofile._WEIGHTS. See ranking_configuration.py's
     module docstring for why nothing here can activate a configuration.

Nothing in this module accepts or returns query text, answer text, chart
values, category labels, source-document data, prompt contents, or error
content — see visualization_analytics.py's own privacy note, which this
module's field set is deliberately kept in lockstep with.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.orchestration.presentation_dataprofile import WEIGHT_BOUNDS, WEIGHT_DIMENSIONS


class EvidenceStatus(str, Enum):
    """How much weight a reader should put on a rate — never render a
    percentage without this. Thresholds live in visualization_analytics.py
    (_MINIMUM_SAMPLE_THRESHOLDS) rather than here, since classifying a
    sample size is a computation, not a contract shape."""
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DIRECTIONAL_SIGNAL = "directional_signal"
    ELIGIBLE_FOR_REVIEW = "eligible_for_review"


class RateMetric(BaseModel):
    """A single percentage that can never be interpreted without its own
    sample size — the two travel together everywhere in this API."""
    rate: float = Field(ge=0.0, le=1.0)
    numerator: int = Field(ge=0)
    sample_size: int = Field(ge=0)
    evidence_status: EvidenceStatus


class RecommendationQualityRow(BaseModel):
    group_key: dict[str, str] = Field(default_factory=dict)
    total_selections: int = Field(ge=0)
    recommendation_retention_rate: RateMetric
    alternative_views_shown_rate: RateMetric
    alternative_switch_rate: RateMetric
    png_export_rate: RateMetric
    csv_export_rate: RateMetric
    visualization_save_rate: RateMetric
    render_failure_rate: RateMetric
    fallback_rate: RateMetric


class RecommendationQualitySummaryResponse(BaseModel):
    rows: list[RecommendationQualityRow]
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    group_by: list[str] = Field(default_factory=list)


class ReplacementMatrixCell(BaseModel):
    original_chart_type: str
    active_chart_type: str
    count: int = Field(ge=0)
    # Share of THIS original_chart_type's successful switches that landed on
    # this active_chart_type — denominator is the original type's own
    # switch total, not the grand total across all original types.
    rate: float = Field(ge=0.0, le=1.0)
    sample_size: int = Field(ge=0)
    evidence_status: EvidenceStatus


class ReplacementMatrixResponse(BaseModel):
    cells: list[ReplacementMatrixCell]
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class ChartTypePerformanceRow(BaseModel):
    group_key: dict[str, str] = Field(default_factory=dict)
    chart_type: str
    total_selections: int = Field(ge=0)
    switch_rate: RateMetric
    fallback_rate: RateMetric
    render_failure_rate: RateMetric
    unusually_high_switch_rate: bool
    unusually_high_fallback_rate: bool
    unusually_high_render_failure_rate: bool


class ChartTypePerformanceResponse(BaseModel):
    rows: list[ChartTypePerformanceRow]
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    group_by: list[str] = Field(default_factory=list)


# ── Ranking configuration governance ─────────────────────────────────────

def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    missing = set(WEIGHT_DIMENSIONS) - set(weights)
    if missing:
        raise ValueError(f"missing weight dimensions: {sorted(missing)}")
    unknown = set(weights) - set(WEIGHT_DIMENSIONS)
    if unknown:
        raise ValueError(f"unknown weight dimensions: {sorted(unknown)}")
    for dimension, value in weights.items():
        low, high = WEIGHT_BOUNDS[dimension]
        if not (low <= value <= high):
            raise ValueError(f"{dimension}={value} is outside the validated bounds [{low}, {high}]")
    return weights


class RankingConfigurationCreate(BaseModel):
    """A drafted PROPOSAL only — see ranking_configuration.py. created_by is
    resolved from the authenticated caller, never trusted from the body."""
    ranking_version: str = Field(min_length=1, max_length=50)
    effective_from: datetime
    weights: dict[str, float]

    @field_validator("weights")
    @classmethod
    def _weights_within_bounds(cls, value: dict[str, float]) -> dict[str, float]:
        return validate_weights(value)


class RankingConfigurationPublic(BaseModel):
    id: str
    ranking_version: str
    effective_from: datetime
    weights: dict[str, float]
    status: Literal["draft", "approved"]
    created_by: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WeightAdjustmentProposal(BaseModel):
    """One recommendation-analysis finding — see
    visualization_analytics.propose_ranking_weight_adjustments. review_required
    is pinned to True at the type level: nothing that constructs this model
    can produce a proposal that claims to be self-activating."""
    affected_analytical_intent: Optional[str] = None
    affected_chart_family: Optional[str] = None
    current_chart_preference: str
    observed_replacement: str
    sample_size: int = Field(ge=0)
    retention_or_switch_rate: float = Field(ge=0.0, le=1.0)
    proposed_weight_adjustment: dict[str, float]
    review_required: Literal[True] = True

    @field_validator("proposed_weight_adjustment")
    @classmethod
    def _adjustment_dimensions_are_known(cls, value: dict[str, float]) -> dict[str, float]:
        unknown = set(value) - set(WEIGHT_DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown weight dimensions: {sorted(unknown)}")
        return value
