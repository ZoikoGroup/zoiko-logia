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
    # Plain statements the result depends on: a reported figure that does not
    # agree with its own inputs, what arithmetic can settle versus what only
    # the preparer can confirm, an input carried from an earlier message.
    notes: list[str] = Field(default_factory=list)



class CalculationTaskState(BaseModel):
    task_type: list[str] = Field(default_factory=list)
    original_inputs: list[CalculationInput] = Field(default_factory=list)
    inputs: list[CalculationInput] = Field(default_factory=list)
    changed_inputs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    derived_results: list[CalculationOutput] = Field(default_factory=list)
