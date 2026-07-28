"""
Calculation widget recompute API — governed calculation architecture,
interactive rendering (2026-07-23, docs/calculation_architecture.md).

POST /api/v1/calculations/recompute

Called by the frontend on every slider change in a rendered
CalculationWidget. Deliberately thin: it re-runs execute_formula() (the
exact same governed formula registry every other calculation path uses)
rather than trusting a client-computed number — one verified source of
truth for the math, never duplicated into JavaScript. No idempotency-key
requirement (unlike /orchestration/ask): this never creates an audit-worthy
"answer to a query," it's live UI feedback for a calculation whose original
triggering query was already audited when the widget was first rendered.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.rate_limit import limiter
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.calculation.formula_registry import execute_formula
from app.domains.calculation.widget import build_widget
from app.orchestration.schemas import CalculationWidget

router = APIRouter(prefix="/calculations", tags=["Calculation Widgets"])


class RecomputeRequest(BaseModel):
    formula_id: str = Field(min_length=1, max_length=200)
    inputs: dict = Field(default_factory=dict)


@router.post("/recompute", response_model=CalculationWidget)
@limiter.limit("120/minute")
async def post_recompute(
    request: Request,
    payload: RecomputeRequest,
    current_user: User = Depends(get_current_user),
) -> CalculationWidget:
    result = execute_formula(payload.formula_id, payload.inputs)
    if result.status != "verified":
        raise HTTPException(status_code=422, detail={"status": result.status, "errors": result.errors})
    widget = build_widget(result, payload.inputs)
    if widget is None:
        raise HTTPException(
            status_code=422,
            detail={"status": "no_widget", "errors": [f"No interactive widget is available for {payload.formula_id!r}."]},
        )
    return widget
