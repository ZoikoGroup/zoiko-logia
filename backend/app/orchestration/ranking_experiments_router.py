"""Dynamic Visualization Selection v7 — ranking-experiment (A/B) management
API. Every endpoint is admin-gated (require_admin): this is the internal
experiment-management view's backing API, and approval/activation/rollback
specifically must be authorization-controlled per v7 requirement 17.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin
from app.orchestration import ranking_experiments as experiments_service
from app.orchestration.ranking_experiments_schemas import (
    ExperimentResultsResponse,
    RankingExperimentCreate,
    RankingExperimentPublic,
)

router = APIRouter(prefix="/orchestration/experiments", tags=["Ranking Experiments"])


class PauseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class RollbackRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class CompleteRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail="Ranking experiment not found")


@router.post("", response_model=RankingExperimentPublic, status_code=201)
async def post_experiment_draft(
    payload: RankingExperimentCreate, db=Depends(get_db), admin: User = Depends(require_admin),
) -> RankingExperimentPublic:
    try:
        row = await experiments_service.create_draft(
            db, name=payload.name, description=payload.description,
            control_ranking_version=payload.control_ranking_version, variant_ranking_version=payload.variant_ranking_version,
            control_allocation_percent=payload.control_allocation_percent, variant_allocation_percent=payload.variant_allocation_percent,
            targeting_rules=payload.targeting_rules, primary_metrics=payload.primary_metrics,
            secondary_metrics=payload.secondary_metrics, guardrail_metrics=payload.guardrail_metrics,
            minimum_sample_size=payload.minimum_sample_size, start_at=payload.start_at, end_at=payload.end_at,
            created_by=admin.id,
        )
    except experiments_service.BothConfigurationsMustExistError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RankingExperimentPublic.model_validate(row)


@router.post("/{experiment_id}/approve", response_model=RankingExperimentPublic)
async def post_experiment_approval(
    experiment_id: str, db=Depends(get_db), admin: User = Depends(require_admin),
) -> RankingExperimentPublic:
    try:
        row = await experiments_service.approve_experiment(db, experiment_id=experiment_id, approver_id=admin.id)
    except experiments_service.RankingExperimentNotFoundError as exc:
        raise _not_found(exc) from exc
    except experiments_service.SelfApprovalError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (experiments_service.InvalidExperimentTransitionError, experiments_service.VariantMustBeApprovedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RankingExperimentPublic.model_validate(row)


@router.post("/{experiment_id}/activate", response_model=RankingExperimentPublic)
async def post_experiment_activation(
    experiment_id: str, db=Depends(get_db), admin: User = Depends(require_admin),
) -> RankingExperimentPublic:
    try:
        row = await experiments_service.activate_experiment(db, experiment_id=experiment_id, actor_id=admin.id)
    except experiments_service.RankingExperimentNotFoundError as exc:
        raise _not_found(exc) from exc
    except (
        experiments_service.InvalidExperimentTransitionError,
        experiments_service.MinimumSampleSizeRequiredError,
        experiments_service.AnotherExperimentAlreadyActiveError,
        experiments_service.VariantMustBeApprovedError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RankingExperimentPublic.model_validate(row)


@router.post("/{experiment_id}/pause", response_model=RankingExperimentPublic)
async def post_experiment_pause(
    experiment_id: str, payload: PauseRequest, db=Depends(get_db), admin: User = Depends(require_admin),
) -> RankingExperimentPublic:
    try:
        row = await experiments_service.pause_experiment(db, experiment_id=experiment_id, actor_id=admin.id, reason=payload.reason)
    except experiments_service.RankingExperimentNotFoundError as exc:
        raise _not_found(exc) from exc
    except experiments_service.InvalidExperimentTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RankingExperimentPublic.model_validate(row)


@router.post("/{experiment_id}/complete", response_model=RankingExperimentPublic)
async def post_experiment_completion(
    experiment_id: str, payload: CompleteRequest, db=Depends(get_db), admin: User = Depends(require_admin),
) -> RankingExperimentPublic:
    try:
        row = await experiments_service.complete_experiment(db, experiment_id=experiment_id, actor_id=admin.id, reason=payload.reason)
    except experiments_service.RankingExperimentNotFoundError as exc:
        raise _not_found(exc) from exc
    except experiments_service.InvalidExperimentTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RankingExperimentPublic.model_validate(row)


@router.post("/{experiment_id}/rollback", response_model=RankingExperimentPublic)
async def post_experiment_rollback(
    experiment_id: str, payload: RollbackRequest, db=Depends(get_db), admin: User = Depends(require_admin),
) -> RankingExperimentPublic:
    try:
        row = await experiments_service.rollback_experiment(db, experiment_id=experiment_id, actor_id=admin.id, reason=payload.reason)
    except experiments_service.RankingExperimentNotFoundError as exc:
        raise _not_found(exc) from exc
    except experiments_service.InvalidExperimentTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RankingExperimentPublic.model_validate(row)


@router.get("/active", response_model=list[RankingExperimentPublic])
async def get_active_experiments(db=Depends(get_db), admin: User = Depends(require_admin)) -> list[RankingExperimentPublic]:
    rows = await experiments_service.list_active_experiments(db)
    return [RankingExperimentPublic.model_validate(row) for row in rows]


@router.get("", response_model=list[RankingExperimentPublic])
async def get_experiments(
    status: Optional[str] = None, db=Depends(get_db), admin: User = Depends(require_admin),
) -> list[RankingExperimentPublic]:
    rows = await experiments_service.list_experiments(db, status=status)
    return [RankingExperimentPublic.model_validate(row) for row in rows]


@router.get("/{experiment_id}", response_model=RankingExperimentPublic)
async def get_experiment_details(
    experiment_id: str, db=Depends(get_db), admin: User = Depends(require_admin),
) -> RankingExperimentPublic:
    row = await experiments_service.get_experiment(db, experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ranking experiment not found")
    return RankingExperimentPublic.model_validate(row)


@router.get("/{experiment_id}/results", response_model=ExperimentResultsResponse)
async def get_experiment_results(
    experiment_id: str, db=Depends(get_db), admin: User = Depends(require_admin),
) -> ExperimentResultsResponse:
    try:
        return await experiments_service.compute_experiment_results(db, experiment_id)
    except experiments_service.RankingExperimentNotFoundError as exc:
        raise _not_found(exc) from exc
