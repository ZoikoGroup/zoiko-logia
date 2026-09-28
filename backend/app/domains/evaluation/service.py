import uuid
import time
import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from sqlalchemy.orm import Session, selectinload

from app.domains.evaluation.models import (
    EvaluationDataset,
    BenchmarkCase,
    ThresholdSet,
    EvaluationRun,
    ResultPack,
    PromotionAuthorization,
    EvaluationCaseResult,
    ReviewerJudgment,
)
from app.domains.evaluation.schemas import (
    EvaluationDatasetCreate,
    ThresholdSetCreate,
    PromotionRequest,
    ReviewerJudgmentCreate,
)
from app.domains.evaluation.threshold_register import validate_metrics
from app.domains.evaluation.release_gates import check_promotion_eligibility
from app.domains.evaluation.gold_set_contamination import case_fingerprint, scan_cases
from app.orchestration.schemas import AskKritonRequest, TaskContextSelection
from app.orchestration.service import ask_kriton


async def create_dataset(
    db: AsyncSession, payload: EvaluationDatasetCreate, *,
    tenant_id: str = "GLOBAL_CONTROL", actor_id: str | None = None,
) -> EvaluationDataset:
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
        split=payload.split,
        frozen=payload.frozen,
        frozen_at=datetime.now(timezone.utc) if payload.frozen else None,
        created_by=actor_id,
    )
    db.add(dataset)
    await db.flush()

    for case_data in payload.cases:
        context_values = dict(case_data.task_context)
        document_ids = context_values.pop("document_ids", [])
        if not isinstance(document_ids, list) or not all(
            isinstance(document_id, str) for document_id in document_ids
        ):
            raise HTTPException(
                status_code=422,
                detail=f"Case {case_data.id} document_ids must be a list of strings",
            )
        try:
            TaskContextSelection(**context_values)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Case {case_data.id} has invalid task_context: {exc}",
            ) from exc
        case = BenchmarkCase(
            id=case_data.id,
            dataset_id=dataset.id,
            query_text=case_data.query_text,
            gold_answer=case_data.gold_answer,
            source_refs=case_data.source_refs,
            risk_scope=case_data.risk_scope,
            jurisdiction=case_data.jurisdiction,
            task_context=case_data.task_context,
            expected_claims=case_data.expected_claims,
            expected_calculations=case_data.expected_calculations,
            acceptable_statuses=case_data.acceptable_statuses,
            critical_error_types=case_data.critical_error_types,
            document_family=case_data.document_family,
            language=case_data.language,
            reviewer_provenance=case_data.reviewer_provenance,
            fingerprint=case_fingerprint(
                query_text=case_data.query_text,
                document_family=case_data.document_family,
                source_refs=case_data.source_refs,
            ),
        )
        db.add(case)

    await db.commit()
    return await get_dataset(db, dataset.id, tenant_id)


async def get_dataset(
    db: AsyncSession, dataset_id: str, tenant_id: str | None = None,
) -> EvaluationDataset:
    statement = (
        select(EvaluationDataset)
        .options(selectinload(EvaluationDataset.cases))
        .where(EvaluationDataset.id == dataset_id)
    )
    if tenant_id is not None:
        statement = statement.where(EvaluationDataset.tenant_id == tenant_id)
    res = await db.execute(statement)
    dataset = res.scalars().first()
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found."
        )
    return dataset


async def freeze_dataset(
    db: AsyncSession, dataset_id: str, *, tenant_id: str,
) -> EvaluationDataset:
    dataset = await get_dataset(db, dataset_id, tenant_id)
    cases = list((await db.execute(select(BenchmarkCase).where(
        BenchmarkCase.dataset_id == dataset.id,
    ))).scalars().all())
    if not cases:
        raise HTTPException(status_code=409, detail="An empty dataset cannot be frozen")
    fingerprints = [case.fingerprint for case in cases]
    if len(fingerprints) != len(set(fingerprints)):
        raise HTTPException(status_code=409, detail="Dataset contains duplicate case fingerprints")
    dataset.frozen = True
    dataset.frozen_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(dataset)
    return dataset


async def create_threshold_set(
    db: AsyncSession, payload: ThresholdSetCreate, *, tenant_id: str = "GLOBAL_CONTROL",
    actor_id: str | None = None,
) -> ThresholdSet:
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
        owner=actor_id or payload.owner,
        approver="",
        tenant_id=tenant_id,
        status="PendingReview",
        submitted_by=actor_id,
    )
    db.add(threshold_set)
    await db.commit()
    await db.refresh(threshold_set)
    return threshold_set


async def approve_threshold_set(
    db: AsyncSession, threshold_id: str, *, tenant_id: str, approver_id: str,
) -> ThresholdSet:
    row = await get_threshold_set(db, threshold_id, tenant_id)
    if row.submitted_by == approver_id:
        raise HTTPException(status_code=403, detail="Threshold submitter cannot approve their own set")
    row.status = "Approved"
    row.approver = approver_id
    row.approved_by = approver_id
    row.approved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


async def get_threshold_set(
    db: AsyncSession, ts_id: str, tenant_id: str | None = None,
) -> ThresholdSet:
    statement = select(ThresholdSet).where(ThresholdSet.id == ts_id)
    if tenant_id is not None:
        statement = statement.where(ThresholdSet.tenant_id == tenant_id)
    res = await db.execute(statement)
    ts = res.scalars().first()
    if not ts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Threshold set {ts_id} not found."
        )
    return ts


async def execute_evaluation_run(
    db: AsyncSession,
    sync_db: Session,
    dataset_id: str,
    threshold_set_id: str,
    config_hash: str,
    candidate_manifest: dict[str, Any],
    *,
    tenant_id: str,
    actor_id: str,
    actor_role: str,
) -> tuple[EvaluationRun, ResultPack]:
    """Execute the real orchestration path for every frozen evaluation case."""
    dataset = await get_dataset(db, dataset_id, tenant_id)
    ts = await get_threshold_set(db, threshold_set_id, tenant_id)
    if ts.status != "Approved":
        raise HTTPException(status_code=409, detail="Threshold set must be independently approved")
    if ts.dataset_id != dataset.id or ts.dataset_version_id != dataset.version:
        raise HTTPException(status_code=409, detail="Threshold set is not coupled to this dataset version")
    if not dataset.frozen:
        raise HTTPException(status_code=409, detail="Evaluation dataset must be frozen before execution")

    manifest_hash = hashlib.sha256(
        json.dumps(candidate_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if config_hash != manifest_hash:
        raise HTTPException(status_code=409, detail="Candidate manifest hash does not match config_hash")

    cases = list((await db.execute(
        select(BenchmarkCase).where(BenchmarkCase.dataset_id == dataset_id).order_by(BenchmarkCase.id)
    )).scalars().all())
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    run = EvaluationRun(
        id=run_id,
        dataset_id=dataset_id,
        threshold_set_id=threshold_set_id,
        config_hash=config_hash,
        status="RUNNING" if cases else "NOT_EVALUATED",
        metrics_summary={},
        tenant_id=tenant_id,
        started_by=actor_id,
        candidate_manifest=candidate_manifest,
        case_count=len(cases),
        failure_reason=None if cases else "EMPTY_DATASET",
    )
    db.add(run)
    await db.flush()

    comparison_cases = list((await db.execute(
        select(BenchmarkCase)
        .join(EvaluationDataset, EvaluationDataset.id == BenchmarkCase.dataset_id)
        .where(
            EvaluationDataset.tenant_id == tenant_id,
            EvaluationDataset.id != dataset.id,
            EvaluationDataset.split != dataset.split,
        )
    )).scalars().all())
    contamination = scan_cases(cases, comparison_cases)

    latencies: list[float] = []
    for case in cases:
        started = time.monotonic()
        error_code = None
        try:
            context_values = dict(case.task_context or {})
            document_ids = list(context_values.pop("document_ids", []))
            context_values.setdefault("jurisdiction", case.jurisdiction)
            context_values.setdefault("language", case.language)
            request = AskKritonRequest(
                query=case.query_text,
                jurisdiction=case.jurisdiction or "",
                document_ids=document_ids,
                task_context=TaskContextSelection(**context_values),
            )
            response = await ask_kriton(
                db, sync_db, actor_id=actor_id, tenant_id=tenant_id,
                role=actor_role, request=request,
            )
            payload = response.model_dump(mode="json")
            response_status = response.outcome
        except Exception as exc:
            payload = {"error_type": type(exc).__name__}
            response_status = "operational_failure"
            error_code = type(exc).__name__
        latency = time.monotonic() - started
        latencies.append(latency)

        bundle = payload.get("source_bundle") or {}
        cited_ids = {
            item.get("version_id") or item.get("source_id") or item.get("id")
            for item in bundle.get("sources", []) if isinstance(item, dict)
        }
        cited_ids.discard(None)
        expected = set(case.source_refs or [])
        recall = len(cited_ids & expected) / len(expected) if expected else None
        precision = len(cited_ids & expected) / len(cited_ids) if cited_ids else (1.0 if not expected else 0.0)
        result = EvaluationCaseResult(
            id=f"case-result-{uuid.uuid4().hex[:12]}", run_id=run.id, case_id=case.id,
            response_status=response_status, response_payload=payload,
            trace={
                "query_id": payload.get("query_id"),
                "correlation_id": payload.get("correlation_id"),
                "route": payload.get("route"),
                "expected_statuses": case.acceptable_statuses,
            },
            latency_seconds=latency, source_recall=recall,
            citation_precision=precision, numeric_correctness=None,
            error_code=error_code, review_status="PENDING",
        )
        db.add(result)

    run.status = "AWAITING_REVIEW" if cases else "NOT_EVALUATED"
    run.completed_at = datetime.now(timezone.utc)
    if cases:
        ordered = sorted(latencies)
        run.metrics_summary = {
            "executed_case_count": len(cases),
            "reviewed_case_count": 0,
            "latency_p95": round(ordered[min(int(len(ordered) * .95), len(ordered) - 1)], 4),
        }
    pack_id = f"pack-{uuid.uuid4().hex[:8]}"
    pack = ResultPack(
        id=pack_id,
        run_id=run.id,
        exact_config_hash=config_hash,
        contamination_scan_status=contamination.status,
        zero_tolerance_passed=False,
        promotion_eligible=False,
        failure_reports=[{"type": "CONTAMINATION", **item} for item in contamination.collisions],
        slice_metrics={}, reviewed_case_count=0,
        expected_case_count=len(cases), complete=False,
    )
    db.add(pack)
    await db.commit()

    await db.refresh(run)
    await db.refresh(pack)
    return run, pack


async def record_reviewer_judgment(
    db: AsyncSession, case_result_id: str, payload: ReviewerJudgmentCreate,
    *, reviewer_id: str, tenant_id: str,
) -> ReviewerJudgment:
    row = (await db.execute(
        select(EvaluationCaseResult, EvaluationRun)
        .join(EvaluationRun, EvaluationRun.id == EvaluationCaseResult.run_id)
        .where(EvaluationCaseResult.id == case_result_id, EvaluationRun.tenant_id == tenant_id)
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Evaluation case result not found")
    result, run = row
    if run.started_by == reviewer_id:
        raise HTTPException(status_code=403, detail="Candidate runner cannot review their own result")
    existing = (await db.execute(select(ReviewerJudgment).where(
        ReviewerJudgment.case_result_id == case_result_id,
        ReviewerJudgment.reviewer_id == reviewer_id,
    ))).scalar_one_or_none()
    if existing and not payload.adjudication:
        raise HTTPException(status_code=409, detail="Reviewer has already judged this result")
    judgment = ReviewerJudgment(
        id=f"judgment-{uuid.uuid4().hex[:12]}", case_result_id=case_result_id,
        reviewer_id=reviewer_id, **payload.model_dump(),
    )
    db.add(judgment)
    result.review_status = "ADJUDICATED" if payload.adjudication else "REVIEWED"
    await db.commit()
    await db.refresh(judgment)
    return judgment


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


async def finalize_evaluation_run(
    db: AsyncSession, run_id: str, *, tenant_id: str,
) -> tuple[EvaluationRun, ResultPack]:
    run = (await db.execute(select(EvaluationRun).where(
        EvaluationRun.id == run_id, EvaluationRun.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    if run.status == "COMPLETED":
        raise HTTPException(status_code=409, detail="Evaluation run has already been finalized")
    pack = (await db.execute(select(ResultPack).where(ResultPack.run_id == run.id))).scalar_one()
    results = list((await db.execute(select(EvaluationCaseResult).where(
        EvaluationCaseResult.run_id == run.id,
    ))).scalars().all())
    if not results:
        run.status = "NOT_EVALUATED"
        run.failure_reason = "EMPTY_DATASET"
        await db.commit()
        return run, pack

    judgments = list((await db.execute(
        select(ReviewerJudgment)
        .join(EvaluationCaseResult, EvaluationCaseResult.id == ReviewerJudgment.case_result_id)
        .where(EvaluationCaseResult.run_id == run.id)
    )).scalars().all())
    latest: dict[str, ReviewerJudgment] = {}
    for judgment in judgments:
        current = latest.get(judgment.case_result_id)
        if current is None or judgment.adjudication or judgment.created_at > current.created_at:
            latest[judgment.case_result_id] = judgment
    if len(latest) != len(results):
        raise HTTPException(status_code=409, detail="Every executed case requires reviewer judgment")

    accepted = sum(1 for value in latest.values() if value.verdict in {"ACCEPT", "ABSTENTION_ACCEPTABLE"})
    critical_errors = [error for value in latest.values() for error in (value.critical_errors or [])]
    metric_names = {name for value in latest.values() for name in (value.metric_scores or {})}
    metrics: dict[str, Any] = {
        "minimum_case_count": len(results),
        "useful_completion": round(accepted / len(results), 4),
        "critical_error_rate": round(len(critical_errors) / len(results), 4),
        "latency_p95": round(sorted(r.latency_seconds for r in results)[min(int(len(results) * .95), len(results) - 1)], 4),
    }
    recalls = [r.source_recall for r in results if r.source_recall is not None]
    precisions = [r.citation_precision for r in results if r.citation_precision is not None]
    if recalls:
        metrics["source_recall"] = _average(recalls)
    if precisions:
        metrics["citation_precision"] = _average(precisions)
    for name in metric_names:
        values = [float(j.metric_scores[name]) for j in latest.values() if name in j.metric_scores]
        metrics[name] = _average(values)

    cases = {case.id: case for case in (await db.execute(select(BenchmarkCase).where(
        BenchmarkCase.dataset_id == run.dataset_id,
    ))).scalars().all()}
    slices: dict[str, dict[str, int]] = {}
    for result in results:
        case = cases[result.case_id]
        for dimension, value in (
            ("jurisdiction", case.jurisdiction or "unspecified"),
            ("risk", case.risk_scope), ("language", case.language),
        ):
            key = f"{dimension}:{value}"
            bucket = slices.setdefault(key, {"cases": 0, "accepted": 0})
            bucket["cases"] += 1
            if latest[result.id].verdict in {"ACCEPT", "ABSTENTION_ACCEPTABLE"}:
                bucket["accepted"] += 1
    slice_metrics = {
        key: {**value, "useful_completion": round(value["accepted"] / value["cases"], 4)}
        for key, value in slices.items()
    }

    ts = await get_threshold_set(db, run.threshold_set_id, tenant_id)
    zero_passed, failures = validate_metrics(metrics, ts.metrics, ts.zero_tolerance_metrics or [])
    if critical_errors:
        zero_passed = False
        failures.append({
            "metric": "critical_errors", "run_value": critical_errors,
            "target": [], "severity": "BLOCKER", "reason": "Observed critical evaluation errors.",
        })
    complete = len(results) == run.case_count == len(latest)
    minimum_cases = int(ts.metrics.get("minimum_case_count", 300))
    if len(results) < minimum_cases:
        failures.append({
            "metric": "minimum_case_count", "run_value": len(results),
            "target": minimum_cases, "severity": "BLOCKER",
            "reason": "Release corpus is smaller than the approved minimum.",
        })
    blockers = sum(1 for item in failures if item.get("severity") == "BLOCKER")
    pack.complete = complete
    pack.reviewed_case_count = len(latest)
    pack.zero_tolerance_passed = zero_passed
    pack.failure_reports = list(pack.failure_reports or []) + failures
    pack.slice_metrics = slice_metrics
    pack.promotion_eligible = check_promotion_eligibility(
        contamination_scan_status=pack.contamination_scan_status,
        zero_tolerance_passed=zero_passed,
        config_hash_valid=True, blockers_count=blockers,
        run_complete=complete, reviewed_case_count=len(latest), expected_case_count=run.case_count,
    )
    run.metrics_summary = metrics
    run.status = "COMPLETED"
    await db.commit()
    await db.refresh(run)
    await db.refresh(pack)
    return run, pack


async def list_case_results(
    db: AsyncSession, run_id: str, *, tenant_id: str,
) -> list[EvaluationCaseResult]:
    run = (await db.execute(select(EvaluationRun.id).where(
        EvaluationRun.id == run_id, EvaluationRun.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return list((await db.execute(
        select(EvaluationCaseResult)
        .where(EvaluationCaseResult.run_id == run_id)
        .order_by(EvaluationCaseResult.case_id)
    )).scalars().all())


async def record_promotion_authorization(
    db: AsyncSession,
    payload: PromotionRequest,
    *,
    approver_id: str,
    tenant_id: str,
) -> PromotionAuthorization:
    res = await db.execute(
        select(ResultPack, EvaluationRun)
        .join(EvaluationRun, EvaluationRun.id == ResultPack.run_id)
        .where(ResultPack.id == payload.result_pack_id, EvaluationRun.tenant_id == tenant_id)
    )
    row = res.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Result pack {payload.result_pack_id} not found."
        )
    pack, run = row
    if run.started_by == approver_id:
        raise HTTPException(status_code=403, detail="Candidate runner cannot authorize promotion")

    decision = payload.decision.upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=422, detail="Decision must be APPROVED or REJECTED")
    # Critical, incomplete, contaminated, or otherwise ineligible runs cannot
    # be promoted via a residual-risk checkbox. Residual risk is metadata for
    # an otherwise eligible release, never an override of a release gate.
    if decision == "APPROVED" and (not pack.complete or not pack.promotion_eligible):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Promotion denied: result pack is incomplete or failed a mandatory release gate.",
        )

    auth_id = f"auth-{uuid.uuid4().hex[:8]}"
    auth = PromotionAuthorization(
        id=auth_id,
        result_pack_id=payload.result_pack_id,
        decision=decision,
        approver_id=approver_id,
        residual_risk_accepted=payload.residual_risk_accepted,
    )
    db.add(auth)
    await db.commit()
    await db.refresh(auth)
    return auth
