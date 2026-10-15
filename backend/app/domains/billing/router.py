# Billing & Usage endpoints. Financial records: Admin only.
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.billing import service
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin

router = APIRouter(prefix="/billing", tags=["Billing & Usage"])


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 422, detail=str(exc))


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await service.overview(db, admin.tenant_id)


class PlanBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    commitment_cents: int = Field(default=0, ge=0)
    included: dict[str, float] = Field(default_factory=dict)
    rates: dict[str, float] = Field(default_factory=dict)
    soft_budget_cents: int = Field(default=0, ge=0)
    hard_cap_cents: int = Field(default=0, ge=0)
    effective_from: str
    note: str = Field(default="", max_length=1000)


class Decision(BaseModel):
    approve: bool = True
    decision: str | None = None
    note: str = Field(default="", max_length=1000)


@router.post("/plans", status_code=201)
async def propose_plan(body: PlanBody, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    try:
        plan = await service.propose_plan(db, admin, body.model_dump())
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": plan.id, "version": plan.version}


@router.post("/plans/{plan_id}/decision")
async def decide_plan(plan_id: str, body: Decision, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    try:
        plan = await service.decide_plan(db, admin, plan_id, body.approve, body.note)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": plan.id, "status": plan.status}


class AdjustmentBody(BaseModel):
    kind: str
    period: str
    reason: str = Field(min_length=3, max_length=1000)
    amount_cents: int = Field(default=0, ge=0)
    meter: str | None = None


@router.post("/adjustments", status_code=201)
async def add_adjustment(body: AdjustmentBody, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    try:
        adj = await service.add_adjustment(db, admin, kind=body.kind, period=body.period, reason=body.reason,
                                           amount_cents=body.amount_cents, meter=body.meter)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": adj.id, "status": adj.status}


@router.post("/adjustments/{adj_id}/decision")
async def decide_adjustment(adj_id: str, body: Decision, db: AsyncSession = Depends(get_db),
                            admin: User = Depends(require_admin)) -> dict:
    try:
        adj = await service.decide_adjustment(db, admin, adj_id, body.decision or "", body.note)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": adj.id, "status": adj.status}


class CloseBody(BaseModel):
    period: str


@router.post("/statements", status_code=201)
async def close_period(body: CloseBody, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    try:
        s = await service.close_period(db, admin, body.period)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": s.id, "ref": s.ref}


class PaidBody(BaseModel):
    reference: str = Field(min_length=1, max_length=120)


@router.post("/statements/{statement_id}/paid")
async def mark_paid(statement_id: str, body: PaidBody, db: AsyncSession = Depends(get_db),
                    admin: User = Depends(require_admin)) -> dict:
    try:
        s = await service.mark_paid(db, admin, statement_id, body.reference)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": s.id, "status": s.status}


@router.get("/report")
async def report(period: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> Response:
    try:
        content = await service.report_csv(db, admin.tenant_id, period)
    except ValueError as exc:
        raise _refused(exc) from exc
    return Response(content=content, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="billing-{period}.csv"', "Cache-Control": "no-store"})
