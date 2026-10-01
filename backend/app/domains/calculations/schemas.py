from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

CalculationOperation = Literal[
    "arithmetic", "sum", "difference", "percentage", "percentage_change",
    "variance", "straight_line_depreciation",
]


class NumericInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    value: str
    unit: str = "number"
    currency: str | None = None
    period: str | None = None
    evidence_id: str | None = None


class CalculationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    calculation_id: str
    operation: CalculationOperation
    rule_version: str
    inputs: list[NumericInput]
    output_value: str
    output_unit: str
    rounding_mode: Literal["ROUND_HALF_UP"] = "ROUND_HALF_UP"
    scale: int = Field(default=2, ge=0, le=8)


class VerifiedChartSeries(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    values: list[str]
    unit: str
    source_ids: list[str]


class VerifiedChartSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    chart_id: str
    type: Literal["bar", "line", "kpi"]
    title: str
    categories: list[str]
    series: list[VerifiedChartSeries]
    calculation_id: str
    verified: Literal[True] = True


class LiveObservation(BaseModel):
    model_config = ConfigDict(frozen=True)
    observation_id: str
    indicator: str
    value: str
    unit: str
    period: str
    provider: str
    source_url: str
    freshness: str
