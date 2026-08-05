"""Dynamic Visualization Selection v7 — ranking-experiment (A/B) contracts.

Same posture as v6's visualization_analytics_schemas.py: nothing here
accepts or returns query text, answer text, chart values, category labels,
source-document data, prompt contents, error content, or candidate score
breakdowns. Metrics reuse v6's RateMetric shape (rate + numerator +
sample_size + evidence_status) extended with a Wilson-score confidence
interval, since a two-arm comparison is meaningless without an uncertainty
measure on each side.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.orchestration.visualization_analytics_schemas import RateMetric

# Closed vocabulary — targeting_rules keys may only ever be one of these.
# Deliberately excludes anything that could carry query/user content;
# analytical_intent and chart_family are both closed, code-defined enums
# already (AnalyticalIntent, _CHART_FAMILY), never free text.
APPROVED_TARGETING_FIELDS: tuple[str, ...] = ("analytical_intent", "chart_family")

# Closed vocabulary for primary/secondary/guardrail metrics — the same set
# recommendation_quality reporting (v6) already computes, so an experiment
# can never ask for a metric this system doesn't know how to measure safely.
METRIC_ENUM: tuple[str, ...] = (
    "recommendation_retention_rate", "alternative_views_shown_rate", "alternative_switch_rate",
    "png_export_rate", "csv_export_rate", "visualization_save_rate", "render_failure_rate", "fallback_rate",
)

_ALLOCATION_TOLERANCE = 0.01


class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class ExperimentResultStatus(str, Enum):
    """Frontend requirement 7's exact closed label set — never render a
    result without one of these attached."""
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EXPERIMENT_RUNNING = "experiment_running"
    DIRECTIONAL_RESULT = "directional_result"
    ELIGIBLE_FOR_DECISION = "eligible_for_decision"
    GUARDRAIL_FAILED = "guardrail_failed"


def validate_targeting_rules(rules: dict[str, list[str]]) -> dict[str, list[str]]:
    unknown = set(rules) - set(APPROVED_TARGETING_FIELDS)
    if unknown:
        raise ValueError(f"targeting_rules may only use approved fields: unknown={sorted(unknown)}")
    for field_name, values in rules.items():
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError(f"targeting_rules[{field_name!r}] must be a list of strings")
    return rules


def validate_metric_list(metrics: list[str]) -> list[str]:
    unknown = set(metrics) - set(METRIC_ENUM)
    if unknown:
        raise ValueError(f"metrics must come from the closed enum: unknown={sorted(unknown)}")
    return metrics


class RankingExperimentCreate(BaseModel):
    """A drafted PROPOSAL only — see ranking_experiments.py. created_by is
    resolved from the authenticated caller, never trusted from the body."""
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    control_ranking_version: str = Field(min_length=1, max_length=50)
    variant_ranking_version: str = Field(min_length=1, max_length=50)
    control_allocation_percent: float = Field(ge=0.0, le=100.0)
    variant_allocation_percent: float = Field(ge=0.0, le=100.0)
    targeting_rules: dict[str, list[str]] = Field(default_factory=dict)
    primary_metrics: list[str] = Field(min_length=1)
    secondary_metrics: list[str] = Field(default_factory=list)
    guardrail_metrics: list[str] = Field(min_length=1)
    minimum_sample_size: Optional[int] = Field(default=None, gt=0)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None

    @field_validator("targeting_rules")
    @classmethod
    def _targeting_rules_are_approved(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        return validate_targeting_rules(value)

    @field_validator("primary_metrics", "secondary_metrics", "guardrail_metrics")
    @classmethod
    def _metrics_are_closed_enum(cls, value: list[str]) -> list[str]:
        return validate_metric_list(value)

    @model_validator(mode="after")
    def _allocations_total_100(self) -> "RankingExperimentCreate":
        total = self.control_allocation_percent + self.variant_allocation_percent
        if abs(total - 100.0) > _ALLOCATION_TOLERANCE:
            raise ValueError(f"control_allocation_percent + variant_allocation_percent must total 100, got {total}")
        return self

    @model_validator(mode="after")
    def _control_and_variant_versions_differ(self) -> "RankingExperimentCreate":
        if self.control_ranking_version == self.variant_ranking_version:
            raise ValueError("control_ranking_version and variant_ranking_version must differ")
        return self

    @model_validator(mode="after")
    def _end_at_after_start_at(self) -> "RankingExperimentCreate":
        if self.start_at is not None and self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class RankingExperimentPublic(BaseModel):
    id: str
    name: str
    description: str
    status: ExperimentStatus
    control_ranking_version: str
    variant_ranking_version: str
    control_allocation_percent: float
    variant_allocation_percent: float
    targeting_rules: dict[str, list[str]]
    primary_metrics: list[str]
    secondary_metrics: list[str]
    guardrail_metrics: list[str]
    minimum_sample_size: Optional[int] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    created_by: str
    approved_by: Optional[str] = None
    status_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RateMetricWithConfidenceInterval(RateMetric):
    confidence_interval_low: float = Field(ge=0.0, le=1.0)
    confidence_interval_high: float = Field(ge=0.0, le=1.0)


class ExperimentGroupMetrics(BaseModel):
    group: Literal["control", "variant"]
    ranking_version: str
    selections: int = Field(ge=0)
    recommendation_retention_rate: RateMetricWithConfidenceInterval
    alternative_views_shown_rate: RateMetricWithConfidenceInterval
    alternative_switch_rate: RateMetricWithConfidenceInterval
    png_export_rate: RateMetricWithConfidenceInterval
    csv_export_rate: RateMetricWithConfidenceInterval
    visualization_save_rate: RateMetricWithConfidenceInterval
    render_failure_rate: RateMetricWithConfidenceInterval
    fallback_rate: RateMetricWithConfidenceInterval


class ExperimentResultsResponse(BaseModel):
    experiment_id: str
    status: ExperimentStatus
    result_status: ExperimentResultStatus
    minimum_sample_size: Optional[int] = None
    control: ExperimentGroupMetrics
    variant: ExperimentGroupMetrics
    # Human-readable, closed-vocabulary findings only (e.g. "variant
    # render_failure_rate exceeds guardrail threshold") — never raw error
    # text, never query/answer content.
    guardrail_findings: list[str] = Field(default_factory=list)
