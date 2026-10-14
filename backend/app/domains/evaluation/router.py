from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.evaluation.schemas import (
    EvaluationDatasetCreate,
    EvaluationDatasetOut,
    ThresholdSetCreate,
    ThresholdSetOut,
    EvaluationRunCreate,
    PromotionRequest,
    PromotionAuthorizationOut,
)
from app.domains.evaluation import service
from app.domains.identity.models import User
from app.domains.identity.permissions import EVALUATION_MANAGE, EVALUATION_READ
from app.domains.identity.rbac import require_permission

router = APIRouter()


@router.post("/datasets", response_model=EvaluationDatasetOut, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    payload: EvaluationDatasetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(EVALUATION_MANAGE))
):
    """Register a new evaluation dataset and its benchmarking cases."""
    return await service.create_dataset(db, payload, tenant_id=current_user.tenant_id)


@router.get("/datasets")
async def list_datasets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(EVALUATION_READ))
):
    """Datasets this tenant can run, with visible case counts."""
    return await service.list_datasets(db, tenant_id=current_user.tenant_id)


@router.get("/thresholds", response_model=list[ThresholdSetOut])
async def list_threshold_sets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(EVALUATION_READ))
):
    """All ratified threshold sets."""
    return await service.list_threshold_sets(db)


@router.get("/runs")
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(EVALUATION_READ))
):
    """Recent evaluation runs with result packs and promotion decisions."""
    return await service.list_runs(db, tenant_id=current_user.tenant_id, limit=limit)


@router.get("/config-hash")
async def get_config_hash(current_user: User = Depends(require_permission(EVALUATION_READ))):
    """The deployed configuration fingerprint a promotable run must use."""
    return {"config_hash": service.current_config_hash()}


@router.get("/datasets/{dataset_id}", response_model=EvaluationDatasetOut)
async def get_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(EVALUATION_READ))
):
    """Retrieve an evaluation dataset by ID."""
    return await service.get_dataset(db, dataset_id, tenant_id=current_user.tenant_id)


@router.post("/thresholds", response_model=ThresholdSetOut, status_code=status.HTTP_201_CREATED)
async def create_threshold_set(
    payload: ThresholdSetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(EVALUATION_MANAGE))
):
    """Register a coupled threshold metric set."""
    return await service.create_threshold_set(db, payload)


@router.get("/thresholds/{ts_id}", response_model=ThresholdSetOut)
async def get_threshold_set(
    ts_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(EVALUATION_READ))
):
    """Retrieve a threshold set by ID."""
    return await service.get_threshold_set(db, ts_id)


@router.post("/run", status_code=status.HTTP_201_CREATED)
async def execute_run(
    payload: EvaluationRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(EVALUATION_MANAGE))
):
    """
    Execute an evaluation test run, validate results against thresholds,
    and package the release verification evidence inside a Result Pack.
    """
    run, pack = await service.execute_evaluation_run(
        db,
        dataset_id=payload.dataset_id,
        threshold_set_id=payload.threshold_set_id,
        config_hash=payload.config_hash,
        tenant_id=current_user.tenant_id,
    )
    ts = await service.get_threshold_set(db, payload.threshold_set_id)
    return {
        "run": run,
        "result_pack": pack,
        **service.run_checks(run, pack, ts),
    }


@router.post("/promote", response_model=PromotionAuthorizationOut, status_code=status.HTTP_201_CREATED)
async def promote_release(
    payload: PromotionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(EVALUATION_MANAGE))
):
    """
    Authorizes a result pack for production release. Enforces QA gate checks.
    Allows manual overrides only with explicitly accepted residual risk.
    """
    # The approver is whoever is signed in, not a name typed into the form.
    payload = payload.model_copy(update={"approver_id": current_user.email or current_user.id})
    return await service.record_promotion_authorization(db, payload)
