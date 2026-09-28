from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.domains.identity.models import User
from app.domains.identity.permissions import MODEL_MANAGE
from app.domains.identity.rbac import require_permission
from app.domains.evaluation.schemas import (
    EvaluationDatasetCreate,
    EvaluationDatasetOut,
    ThresholdSetCreate,
    ThresholdSetOut,
    EvaluationRunCreate,
    EvaluationRunOut,
    ResultPackOut,
    PromotionRequest,
    PromotionAuthorizationOut,
    EvaluationCaseResultOut,
    ReviewerJudgmentCreate,
    ReviewerJudgmentOut,
)
from app.domains.evaluation import service

router = APIRouter()


@router.post("/datasets", response_model=EvaluationDatasetOut, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    payload: EvaluationDatasetCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
):
    """Register a new evaluation dataset and its benchmarking cases."""
    return await service.create_dataset(
        db, payload, tenant_id=actor.tenant_id, actor_id=actor.id,
    )


@router.get("/datasets/{dataset_id}", response_model=EvaluationDatasetOut)
async def get_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
):
    """Retrieve an evaluation dataset by ID."""
    return await service.get_dataset(db, dataset_id, actor.tenant_id)


@router.post("/datasets/{dataset_id}/freeze", response_model=EvaluationDatasetOut)
async def freeze_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> EvaluationDatasetOut:
    return await service.freeze_dataset(db, dataset_id, tenant_id=actor.tenant_id)


@router.post("/thresholds", response_model=ThresholdSetOut, status_code=status.HTTP_201_CREATED)
async def create_threshold_set(
    payload: ThresholdSetCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
):
    """Register a coupled threshold metric set."""
    return await service.create_threshold_set(
        db, payload, tenant_id=actor.tenant_id, actor_id=actor.id,
    )


@router.get("/thresholds/{ts_id}", response_model=ThresholdSetOut)
async def get_threshold_set(
    ts_id: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
):
    """Retrieve a threshold set by ID."""
    return await service.get_threshold_set(db, ts_id, actor.tenant_id)


@router.post("/thresholds/{ts_id}/approve", response_model=ThresholdSetOut)
async def approve_threshold_set(
    ts_id: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> ThresholdSetOut:
    return await service.approve_threshold_set(
        db, ts_id, tenant_id=actor.tenant_id, approver_id=actor.id,
    )


@router.post("/run", status_code=status.HTTP_201_CREATED)
async def execute_run(
    payload: EvaluationRunCreate,
    db: AsyncSession = Depends(get_db),
    sync_db: Session = Depends(get_sync_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
):
    """
    Execute an evaluation test run, validate results against thresholds,
    and package the release verification evidence inside a Result Pack.
    """
    run, pack = await service.execute_evaluation_run(
        db,
        sync_db,
        dataset_id=payload.dataset_id,
        threshold_set_id=payload.threshold_set_id,
        config_hash=payload.config_hash,
        candidate_manifest=payload.candidate_manifest,
        tenant_id=actor.tenant_id,
        actor_id=actor.id,
        actor_role=actor.role,
    )
    return {
        "run": run,
        "result_pack": pack
    }


@router.get("/runs/{run_id}/cases", response_model=list[EvaluationCaseResultOut])
async def get_case_results(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> list[EvaluationCaseResultOut]:
    rows = await service.list_case_results(db, run_id, tenant_id=actor.tenant_id)
    return [EvaluationCaseResultOut.model_validate(row) for row in rows]


@router.post(
    "/case-results/{case_result_id}/judgments",
    response_model=ReviewerJudgmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_judgment(
    case_result_id: str,
    payload: ReviewerJudgmentCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> ReviewerJudgmentOut:
    row = await service.record_reviewer_judgment(
        db, case_result_id, payload,
        reviewer_id=actor.id, tenant_id=actor.tenant_id,
    )
    return ReviewerJudgmentOut.model_validate(row)


@router.post("/runs/{run_id}/finalize")
async def finalize_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
):
    run, pack = await service.finalize_evaluation_run(
        db, run_id, tenant_id=actor.tenant_id,
    )
    return {"run": run, "result_pack": pack}


@router.post("/promote", response_model=PromotionAuthorizationOut, status_code=status.HTTP_201_CREATED)
async def promote_release(
    payload: PromotionRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
):
    """
    Authorizes a result pack for production release. Enforces QA gate checks.
    Mandatory gates cannot be overridden by residual-risk acceptance.
    """
    return await service.record_promotion_authorization(
        db, payload, approver_id=actor.id, tenant_id=actor.tenant_id,
    )
