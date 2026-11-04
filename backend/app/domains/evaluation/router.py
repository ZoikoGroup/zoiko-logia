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


# ── WF-01 A3: the runtime QA ledger ────────────────────────────────────────
# Observations come from the deployed API over HTTP; a case passes only by
# independent adjudication (qa_ledger.summary).

from typing import Literal  # noqa: E402

from fastapi import Body  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app.domains.admin_governance.governance_access import idempotency_key, require_governance  # noqa: E402
from app.domains.evaluation import qa_ledger  # noqa: E402
from app.domains.identity.permissions import GOVERNANCE_READ, QA_ADJUDICATE, QA_EXECUTE  # noqa: E402


@router.get("/qa/summary")
async def get_qa_summary(db: AsyncSession = Depends(get_db), user: User = Depends(require_governance(GOVERNANCE_READ))) -> dict:
    return await qa_ledger.summary(db)


@router.get("/qa/adapter")
async def get_qa_adapter(user: User = Depends(require_governance(GOVERNANCE_READ))) -> dict:
    return await qa_ledger.adapter_readiness()


@router.post("/qa/pack")
async def import_qa_pack(db: AsyncSession = Depends(get_db), user: User = Depends(require_governance(QA_EXECUTE)),
                         key: str = Depends(idempotency_key)) -> dict:
    return await qa_ledger.import_pack(db)


class QaRunBody(BaseModel):
    pinned: dict[str, str]


@router.post("/qa/runs", status_code=status.HTTP_201_CREATED)
async def create_qa_run(body: QaRunBody, db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_governance(QA_EXECUTE)), key: str = Depends(idempotency_key)) -> dict:
    return await qa_ledger.create_run(db, user, body.pinned, key, readiness=await qa_ledger.adapter_readiness())


class QaExecuteBody(BaseModel):
    case_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)


@router.post("/qa/runs/{run_id}/execute")
async def execute_qa_run(run_id: str, body: QaExecuteBody = Body(default_factory=QaExecuteBody),
                         db: AsyncSession = Depends(get_db), user: User = Depends(require_governance(QA_EXECUTE)),
                         key: str = Depends(idempotency_key)) -> dict:
    return await qa_ledger.execute(db, run_id, case_ids=body.case_ids or None, limit=body.limit)


@router.get("/qa/runs/{run_id}/observations")
async def list_qa_observations(run_id: str, db: AsyncSession = Depends(get_db),
                               user: User = Depends(require_governance(GOVERNANCE_READ))) -> list[dict]:
    return await qa_ledger.observations(db, run_id)


class QaAdjudicationBody(BaseModel):
    verdict: Literal["PASSED", "FAILED", "INCONCLUSIVE"]
    oracle_version: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/qa/observations/{observation_id}/adjudications", status_code=status.HTTP_201_CREATED)
async def adjudicate_qa_observation(observation_id: str, body: QaAdjudicationBody, db: AsyncSession = Depends(get_db),
                                    user: User = Depends(require_governance(QA_ADJUDICATE)),
                                    key: str = Depends(idempotency_key)) -> dict:
    return await qa_ledger.adjudicate(db, user, observation_id, verdict=body.verdict, oracle_version=body.oracle_version,
                                      reason=body.reason, key=key)


@router.get("/qa/runs")
async def list_qa_runs(db: AsyncSession = Depends(get_db), user: User = Depends(require_governance(GOVERNANCE_READ))) -> list[dict]:
    return await qa_ledger.list_runs(db)


@router.get("/qa/runs/{run_id}/evaluator-output")
async def get_qa_evaluator_output(run_id: str, db: AsyncSession = Depends(get_db),
                                  user: User = Depends(require_governance(GOVERNANCE_READ))) -> list[dict]:
    return await qa_ledger.evaluator_output(db, run_id)


@router.get("/qa/fixtures")
async def get_qa_fixtures(db: AsyncSession = Depends(get_db), user: User = Depends(require_governance(GOVERNANCE_READ))) -> dict:
    return await qa_ledger.fixtures_status(db)


@router.post("/qa/fixtures/provision")
async def provision_qa_fixtures(db: AsyncSession = Depends(get_db), user: User = Depends(require_governance(QA_EXECUTE)),
                                key: str = Depends(idempotency_key)) -> dict:
    return await qa_ledger.provision_fixtures(db, user)
