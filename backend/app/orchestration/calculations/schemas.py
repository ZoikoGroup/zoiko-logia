from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class CalculationInput(BaseModel):
    name: str
    value: Decimal
    display_value: str
    kind: Literal["money", "percentage", "number", "years", "units"] = "number"
    currency: str | None = None
    source_type: Literal["user"] = "user"
    source_location: str = "query"


class CalculationOutput(BaseModel):
    name: str
    value: Decimal | None = None
    display_value: str | None = None
    kind: Literal["money", "percentage", "ratio", "number", "units"] = "number"


class CalculationResult(BaseModel):
    matched: bool = False
    status: Literal["success", "undefined", "clarification_required", "not_matched"] = "not_matched"
    formula_ids: list[str] = Field(default_factory=list)
    formula_version: str = "1.0"
    inputs: list[CalculationInput] = Field(default_factory=list)
    outputs: list[CalculationOutput] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    verification_status: Literal["passed", "not_run"] = "not_run"
    error_code: str | None = None
    message: str = ""

