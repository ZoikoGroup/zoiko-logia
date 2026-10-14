import uuid
import time
import re
from pathlib import Path
from fastapi import HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import List

from app.domains.evaluation.models import (
    EvaluationDataset,
    BenchmarkCase,
    ThresholdSet,
    EvaluationRun,
    ResultPack,
    PromotionAuthorization,
)
from app.domains.evaluation.schemas import (
    EvaluationDatasetCreate,
    ThresholdSetCreate,
    PromotionRequest,
)
from app.domains.evaluation.gold_set_contamination import runtime_config_hash, scan_contamination
from app.domains.evaluation.threshold_register import validate_metrics
from app.domains.evaluation.release_gates import check_promotion_eligibility
from app.domains.risk_safety import service as safety_service
from app.domains.risk_safety.schemas import ClassifyRequest

# backend/app — the runtime code scanned for gold-set leakage and fingerprinted
# for the run's configuration hash.
APP_ROOT = Path(__file__).resolve().parents[2]


# PII / Secrets detection helpers
PII_RE = re.compile(r"\b(\d{3}-\d{2}-\d{4}|\d{4}-\d{4}-\d{4}-\d{4}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
SECRET_RE = re.compile(r"\b(api[-_]?key|secret[-_]?key|private[-_]?key)\b", re.IGNORECASE)


async def create_dataset(db: AsyncSession, payload: EvaluationDatasetCreate, *, tenant_id: str | None = None) -> EvaluationDataset:
    res = await db.execute(select(EvaluationDataset).where(EvaluationDataset.id == payload.id))
    existing = res.scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dataset with ID {payload.id} already exists."
        )

    dataset = EvaluationDataset(
        id=payload.id,
        version=payload.version,
        status=payload.status or "ACTIVE",
        domain=payload.domain,
        tenant_id=tenant_id,
    )
    db.add(dataset)
    await db.flush()

    for case_data in payload.cases:
        case = BenchmarkCase(
            id=case_data.id,
            dataset_id=dataset.id,
            tenant_id=tenant_id,
            query_text=case_data.query_text,
            gold_answer=case_data.gold_answer,
            source_refs=case_data.source_refs,
            risk_scope=case_data.risk_scope,
            jurisdiction=case_data.jurisdiction,
        )
        db.add(case)

    await db.commit()
    return await get_dataset(db, dataset.id, tenant_id=tenant_id)


async def get_dataset(db: AsyncSession, dataset_id: str, *, tenant_id: str | None = None) -> EvaluationDataset:
    res = await db.execute(select(EvaluationDataset).options(selectinload(EvaluationDataset.cases)).where(EvaluationDataset.id == dataset_id, or_(EvaluationDataset.tenant_id.is_(None), EvaluationDataset.tenant_id == tenant_id)))
    dataset = res.scalars().first()
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found."
        )
    return dataset


async def create_threshold_set(db: AsyncSession, payload: ThresholdSetCreate) -> ThresholdSet:
    res = await db.execute(select(ThresholdSet).where(ThresholdSet.id == payload.id))
    existing = res.scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ThresholdSet with ID {payload.id} already exists."
        )

    threshold_set = ThresholdSet(
        id=payload.id,
        dataset_id=payload.dataset_id,
        dataset_version_id=payload.dataset_version_id,
        metrics=payload.metrics,
        zero_tolerance_metrics=payload.zero_tolerance_metrics,
        owner=payload.owner,
        approver=payload.approver,
    )
    db.add(threshold_set)
    await db.commit()
    await db.refresh(threshold_set)
    return threshold_set


async def get_threshold_set(db: AsyncSession, ts_id: str) -> ThresholdSet:
    res = await db.execute(select(ThresholdSet).where(ThresholdSet.id == ts_id))
    ts = res.scalars().first()
    if not ts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Threshold set {ts_id} not found."
        )
    return ts


async def execute_evaluation_run(
    db: AsyncSession,
    dataset_id: str,
    threshold_set_id: str,
    config_hash: str,
    tenant_id: str | None = None,
) -> tuple[EvaluationRun, ResultPack]:
    # 1. Fetch dependencies
    await get_dataset(db, dataset_id, tenant_id=tenant_id)  # 404s on an unknown dataset
    ts = await get_threshold_set(db, threshold_set_id)

    # 2. Query actual cases from the database
    # Shared cases plus this tenant's own — never another tenant's learned answers.
    res = await db.execute(select(BenchmarkCase).where(
        BenchmarkCase.dataset_id == dataset_id,
        or_(BenchmarkCase.tenant_id.is_(None), BenchmarkCase.tenant_id == tenant_id),
    ))
    cases = res.scalars().all()

    # Nothing to measure means nothing to report: an empty dataset used to
    # produce a full set of invented "healthy" metrics here.
    if not cases:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Dataset {dataset_id} has no benchmark cases, so there is nothing to evaluate.",
        )

    # 3. Dynamic Evaluation Logic (Invoking other safety/boundary components).
    # Every metric below is measured from the dataset's cases — the safety
    # classifier's decision on each question and the boundary validator /
    # PII / secret / citation checks on each gold answer. Metrics this run
    # does not measure (source recall, tool accuracy, cross-tenant leakage)
    # are left out rather than given a value, so a threshold set that
    # requires them fails as "metric missing" instead of passing on a guess.
    if len(cases) > 0:
        latencies: List[float] = []
        restricted_blocked = 0
        total_restricted = 0
        safe_blocked = 0
        total_safe = 0
        boundary_violations = 0
        pii_leaks = 0
        secrets_leaks = 0
        citation_matches = 0

        for case in cases:
            start_time = time.time()
            
            # A. Evaluate Safety Classification (Risk Classification Engine)
            classify_req = ClassifyRequest(
                query=case.query_text,
                jurisdiction=case.jurisdiction or "",
                mode="Workflow"
            )
            decision = safety_service.evaluate(classify_req, db=None)
            
            # B. Validate Professional Boundary on output
            validation = safety_service.validate_output(case.gold_answer, db=None)
            has_violations = len(validation.get("violations", [])) > 0
            
            elapsed = time.time() - start_time
            latencies.append(elapsed)

            # C. Safety metrics mapping
            if case.risk_scope == "RESTRICTED":
                total_restricted += 1
                if not decision.allowed:
                    restricted_blocked += 1
            else:
                total_safe += 1
                if not decision.allowed:
                    safe_blocked += 1

            # D. Boundary violations mapping
            if has_violations:
                boundary_violations += 1

            # E. PII / Secrets scanning
            if PII_RE.search(case.query_text) or PII_RE.search(case.gold_answer):
                pii_leaks += 1
            if SECRET_RE.search(case.query_text) or SECRET_RE.search(case.gold_answer):
                secrets_leaks += 1

            # F. Citation matching
            if case.source_refs and any(ref in case.gold_answer for ref in case.source_refs):
                citation_matches += 1

        # Calculate final metrics from executions
        latencies.sort()
        p95_idx = int(len(latencies) * 0.95)
        p95_latency = latencies[min(p95_idx, len(latencies) - 1)]

        restricted_block_rate = (restricted_blocked / total_restricted) if total_restricted > 0 else 1.0
        over_refusal_rate = (safe_blocked / total_safe) if total_safe > 0 else 0.0
        boundary_pass_rate = 1.0 - (boundary_violations / len(cases))
        pii_leak_rate = pii_leaks / len(cases)
        secrets_leak_rate = secrets_leaks / len(cases)
        citation_precision = citation_matches / len(cases)

        run_metrics = {
            "citation_precision": round(citation_precision, 2),
            "latency_p95": round(p95_latency, 3),
            "over_refusal_rate": round(over_refusal_rate, 2),
            "pii_leak": round(pii_leak_rate, 2),
            "secrets_leak": round(secrets_leak_rate, 2),
            "restricted_block_rate": round(restricted_block_rate, 2),
            "boundary_pass_rate": round(boundary_pass_rate, 2),
            "cases_evaluated": len(cases),
        }

    # Contamination and configuration evidence are measured, never assumed:
    # the exact-text scan checks whether any gold question/answer leaked into
    # the runtime code, and the config hash fingerprints the code and model
    # settings actually running. A caller-supplied hash that differs from the
    # running configuration cannot be promoted — the run did not test it.
    leaked = scan_contamination(
        [{"id": c.id, "question": c.query_text, "gold_answer": c.gold_answer} for c in cases], APP_ROOT,
    )
    contamination_status = "FAILED" if leaked else "PASSED"
    run_metrics["contaminated_cases"] = len(leaked)
    running_hash = runtime_config_hash(APP_ROOT)
    config_hash = config_hash or running_hash
    config_hash_valid = config_hash == running_hash

    # 4. Validate metrics against coupled threshold set
    zero_tolerance_passed, failure_reports = validate_metrics(
        metrics_run=run_metrics,
        threshold_metrics=ts.metrics,
        zero_tolerance_keys=ts.zero_tolerance_metrics or []
    )

    # Count high/blocker severity bugs from failure report
    blockers_count = sum(
        1 for f in failure_reports if f.get("severity") in ("BLOCKER", "HIGH")
    )

    # 5. Create Evaluation Run
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    run = EvaluationRun(
        id=run_id,
        dataset_id=dataset_id,
        threshold_set_id=threshold_set_id,
        config_hash=config_hash,
        status="COMPLETED",
        metrics_summary=run_metrics,
    )
    db.add(run)
    await db.flush()

    # 6. Enforce Release Gates
    promotion_eligible = check_promotion_eligibility(
        contamination_scan_status=contamination_status,
        zero_tolerance_passed=zero_tolerance_passed,
        config_hash_valid=config_hash_valid,
        blockers_count=blockers_count
    )

    # 7. Create Result Pack — exact_config_hash is what was actually tested.
    pack_id = f"pack-{uuid.uuid4().hex[:8]}"
    pack = ResultPack(
        id=pack_id,
        run_id=run.id,
        exact_config_hash=running_hash,
        contamination_scan_status=contamination_status,
        zero_tolerance_passed=zero_tolerance_passed,
        promotion_eligible=promotion_eligible,
    )
    db.add(pack)
    await db.commit()

    await db.refresh(run)
    await db.refresh(pack)
    return run, pack


async def record_promotion_authorization(
    db: AsyncSession,
    payload: PromotionRequest
) -> PromotionAuthorization:
    res = await db.execute(select(ResultPack).where(ResultPack.id == payload.result_pack_id))
    pack = res.scalars().first()
    if not pack:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Result pack {payload.result_pack_id} not found."
        )

    # Check if eligible for release, or if override was explicitly authorized
    # Approving an ineligible pack needs explicitly accepted residual risk;
    # rejecting one is always allowed.
    if payload.decision == "APPROVED" and not pack.promotion_eligible and not payload.residual_risk_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Promotion denied. Result pack is ineligible and residual risk was not accepted."
        )

    auth_id = f"auth-{uuid.uuid4().hex[:8]}"
    auth = PromotionAuthorization(
        id=auth_id,
        result_pack_id=payload.result_pack_id,
        decision=payload.decision,
        approver_id=payload.approver_id,
        residual_risk_accepted=payload.residual_risk_accepted,
    )
    db.add(auth)
    await db.commit()
    await db.refresh(auth)
    return auth


# ─── Read views for the Evaluation Gates page ────────────────────────────────

def current_config_hash() -> str:
    """The running code + model configuration fingerprint (same value as
    GET /health/version); only a run made against it can be promoted."""
    return runtime_config_hash(APP_ROOT)


def run_checks(run: EvaluationRun, pack: ResultPack | None, ts: ThresholdSet | None) -> dict:
    """What the page shows beside a run: threshold failures, whether the run
    tested the running configuration, and which gated metrics it could not
    measure (they are left out of the run, so they fail as missing)."""
    metrics = run.metrics_summary or {}
    failures = validate_metrics(metrics, ts.metrics, ts.zero_tolerance_metrics or [])[1] if ts else []
    return {
        "failures": failures,
        "config_hash_valid": bool(pack) and run.config_hash == pack.exact_config_hash,
        "unmeasured_metrics": [key for key in (ts.metrics if ts else {}) if key not in metrics],
        "case_count": metrics.get("cases_evaluated"),
    }


def _visible_to(tenant_id: str | None):
    return or_(EvaluationDataset.tenant_id.is_(None), EvaluationDataset.tenant_id == tenant_id)


async def list_datasets(db: AsyncSession, *, tenant_id: str | None) -> list[dict]:
    """Datasets this tenant can run, with how many of their cases it can see."""
    from sqlalchemy import func

    case_count = (
        select(BenchmarkCase.dataset_id, func.count().label("n"))
        .where(or_(BenchmarkCase.tenant_id.is_(None), BenchmarkCase.tenant_id == tenant_id))
        .group_by(BenchmarkCase.dataset_id)
        .subquery()
    )
    rows = await db.execute(
        select(EvaluationDataset, func.coalesce(case_count.c.n, 0))
        .outerjoin(case_count, case_count.c.dataset_id == EvaluationDataset.id)
        .where(_visible_to(tenant_id))
        .order_by(EvaluationDataset.created_at.desc())
    )
    return [
        {
            "id": dataset.id,
            "version": dataset.version,
            "status": dataset.status,
            "domain": dataset.domain,
            "created_at": dataset.created_at,
            "case_count": count,
        }
        for dataset, count in rows.all()
    ]


async def list_threshold_sets(db: AsyncSession) -> list[ThresholdSet]:
    res = await db.execute(select(ThresholdSet).order_by(ThresholdSet.created_at.desc()))
    return list(res.scalars().all())


async def list_runs(db: AsyncSession, *, tenant_id: str | None, limit: int = 20) -> list[dict]:
    """Recent runs on datasets this tenant can see, with the result pack,
    the latest promotion decision and the threshold failures."""
    res = await db.execute(
        select(EvaluationRun)
        .join(EvaluationDataset, EvaluationDataset.id == EvaluationRun.dataset_id)
        .where(_visible_to(tenant_id))
        .options(selectinload(EvaluationRun.result_pack).selectinload(ResultPack.authorizations))
        .order_by(EvaluationRun.created_at.desc())
        .limit(limit)
    )
    runs = list(res.scalars().all())
    thresholds = {ts.id: ts for ts in await list_threshold_sets(db)} if runs else {}
    current_hash = current_config_hash() if runs else ""
    out = []
    for run in runs:
        pack = run.result_pack
        latest = max(pack.authorizations, key=lambda a: a.created_at) if pack and pack.authorizations else None
        checks = run_checks(run, pack, thresholds.get(run.threshold_set_id))
        out.append({
            "id": run.id,
            "dataset_id": run.dataset_id,
            "threshold_set_id": run.threshold_set_id,
            "config_hash": run.config_hash,
            # The run tested the configuration that is running now.
            "matches_current_config": bool(pack) and pack.exact_config_hash == current_hash and checks["config_hash_valid"],
            "status": run.status,
            "metrics_summary": run.metrics_summary,
            "created_at": run.created_at,
            "failures": checks["failures"],
            "unmeasured_metrics": checks["unmeasured_metrics"],
            "result_pack": {
                "id": pack.id,
                "contamination_scan_status": pack.contamination_scan_status,
                "zero_tolerance_passed": pack.zero_tolerance_passed,
                "promotion_eligible": pack.promotion_eligible,
            } if pack else None,
            "promotion": {
                "decision": latest.decision,
                "approver_id": latest.approver_id,
                "residual_risk_accepted": latest.residual_risk_accepted,
                "created_at": latest.created_at,
            } if latest else None,
        })
    return out
