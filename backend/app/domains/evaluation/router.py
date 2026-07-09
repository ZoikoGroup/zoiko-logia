from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.core.database import get_db
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
)
from app.domains.evaluation import service

router = APIRouter()


@router.post("/datasets", response_model=EvaluationDatasetOut, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    payload: EvaluationDatasetCreate,
    db: AsyncSession = Depends(get_db)
):
    """Register a new evaluation dataset and its benchmarking cases."""
    return await service.create_dataset(db, payload)


@router.get("/datasets/{dataset_id}", response_model=EvaluationDatasetOut)
async def get_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve an evaluation dataset by ID."""
    return await service.get_dataset(db, dataset_id)


@router.post("/thresholds", response_model=ThresholdSetOut, status_code=status.HTTP_201_CREATED)
async def create_threshold_set(
    payload: ThresholdSetCreate,
    db: AsyncSession = Depends(get_db)
):
    """Register a coupled threshold metric set."""
    return await service.create_threshold_set(db, payload)


@router.get("/thresholds/{ts_id}", response_model=ThresholdSetOut)
async def get_threshold_set(
    ts_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve a threshold set by ID."""
    return await service.get_threshold_set(db, ts_id)


@router.post("/run", status_code=status.HTTP_201_CREATED)
async def execute_run(
    payload: EvaluationRunCreate,
    db: AsyncSession = Depends(get_db)
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
    )
    return {
        "run": run,
        "result_pack": pack
    }


@router.post("/promote", response_model=PromotionAuthorizationOut, status_code=status.HTTP_201_CREATED)
async def promote_release(
    payload: PromotionRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Authorizes a result pack for production release. Enforces QA gate checks.
    Allows manual overrides only with explicitly accepted residual risk.
    """
    return await service.record_promotion_authorization(db, payload)
