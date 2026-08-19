from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class StatisticalOperation(StrEnum):
    CORRELATION = "correlation"
    COMPARISON = "comparison"
    TREND = "trend"
    LARGEST_CHANGE = "largest_change"
    AVERAGE = "average"


@dataclass(frozen=True)
class MetricRequest:
    code: str
    label: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class StatisticalQueryPlan:
    operation: StatisticalOperation
    metrics: tuple[MetricRequest, ...]
    geography_code: str | None
    geography_label: str | None
    frequency: str = "annual"
    last_n_periods: int | None = None
    start_year: int | None = None


@dataclass(frozen=True)
class Observation:
    period: str
    value: float


@dataclass(frozen=True)
class SeriesProvenance:
    provider: str
    dataset_code: str
    series_code: str
    title: str
    url: str


@dataclass(frozen=True)
class DataSeries:
    metric_code: str
    metric_label: str
    geography_code: str | None
    geography_label: str | None
    frequency: str
    unit: str | None
    observations: tuple[Observation, ...]
    provenance: SeriesProvenance


@dataclass(frozen=True)
class StatisticalAnalysisResult:
    plan: StatisticalQueryPlan
    series: tuple[DataSeries, ...]
    periods: tuple[str, ...]
    aligned_values: tuple[tuple[float, ...], ...]
    scalar_result: float | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StatisticalAnalysisAttempt:
    handled: bool
    result: StatisticalAnalysisResult | None = None
    failure_reason: str | None = None
