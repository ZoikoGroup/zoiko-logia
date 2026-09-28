import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.evaluation import service
from app.domains.evaluation.models import EvaluationCaseResult
from app.domains.evaluation.schemas import (
    BenchmarkCaseCreate,
    EvaluationDatasetCreate,
    PromotionRequest,
    ReviewerJudgmentCreate,
    ThresholdSetCreate,
)


def _manifest_hash(manifest: dict) -> str:
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _dataset(identifier: str = "release-v1", split: str = "release") -> EvaluationDatasetCreate:
    return EvaluationDatasetCreate(
        id=identifier, version="1.0", domain="accounting", split=split,
        cases=[
            BenchmarkCaseCreate(
                id=f"{identifier}-1", query_text="Explain IFRS revenue recognition",
                gold_answer="Reference answer", source_refs=["ifrs-15-v1"],
                risk_scope="MEDIUM", jurisdiction="UK",
                expected_claims=["Recognise revenue as obligations are satisfied"],
                reviewer_provenance="reviewer-pack-1",
            ),
            BenchmarkCaseCreate(
                id=f"{identifier}-2", query_text="What is double-entry bookkeeping?",
                gold_answer="Reference answer", risk_scope="LOW",
                jurisdiction="Global", reviewer_provenance="reviewer-pack-1",
            ),
        ],
    )


@pytest.fixture
async def evaluation_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        yield db
    await engine.dispose()


@pytest.mark.asyncio
async def test_real_outputs_are_persisted_reviewed_and_scored(evaluation_db, monkeypatch) -> None:
    db = evaluation_db
    dataset = await service.create_dataset(
        db, _dataset(), tenant_id="tenant-1", actor_id="owner",
    )
    await service.freeze_dataset(db, dataset.id, tenant_id="tenant-1")
    await service.create_threshold_set(db, ThresholdSetCreate(
        id="threshold-1", dataset_id=dataset.id, dataset_version_id="1.0",
        metrics={
            "minimum_case_count": 2, "useful_completion": 1.0,
            "critical_error_rate": 0.0, "latency_p95": 5.0,
            "source_recall": 1.0,
        },
        zero_tolerance_metrics=["critical_error_rate", "source_recall"],
        owner="owner", approver="checker",
    ), tenant_id="tenant-1", actor_id="owner")
    await service.approve_threshold_set(
        db, "threshold-1", tenant_id="tenant-1", approver_id="checker",
    )

    calls = []

    async def fake_ask(*args, request, **kwargs):
        calls.append(request.query)
        sources = ([{"version_id": "ifrs-15-v1", "source_id": "ifrs-15"}]
                   if "IFRS" in request.query else [])
        payload = {
            "query_id": f"query-{len(calls)}", "correlation_id": f"corr-{len(calls)}",
            "outcome": "answered", "route": "LLM",
            "source_bundle": {"sources": sources},
            "answer": {"summary": "candidate output"},
        }
        return SimpleNamespace(outcome="answered", model_dump=lambda **_: payload)

    monkeypatch.setattr(service, "ask_kriton", fake_ask)
    manifest = {"model": "approved-model", "prompt": "v1", "retriever": "v1"}
    run, pack = await service.execute_evaluation_run(
        db, None, dataset.id, "threshold-1", _manifest_hash(manifest), manifest,
        tenant_id="tenant-1", actor_id="runner", actor_role="Risk Admin",
    )
    assert calls == [
        "Explain IFRS revenue recognition", "What is double-entry bookkeeping?",
    ]
    assert run.status == "AWAITING_REVIEW"
    assert pack.promotion_eligible is False and pack.complete is False

    results = list((await db.execute(
        select(EvaluationCaseResult).where(EvaluationCaseResult.run_id == run.id)
    )).scalars().all())
    assert results[0].response_payload["answer"]["summary"] == "candidate output"
    assert results[0].source_recall == 1.0
    for result in results:
        await service.record_reviewer_judgment(
            db, result.id,
            ReviewerJudgmentCreate(
                verdict="ACCEPT", metric_scores={"claim_support": 1.0},
            ),
            reviewer_id=f"reviewer-{result.id}", tenant_id="tenant-1",
        )

    run, pack = await service.finalize_evaluation_run(db, run.id, tenant_id="tenant-1")
    assert run.status == "COMPLETED"
    assert run.metrics_summary["useful_completion"] == 1.0
    assert run.metrics_summary["source_recall"] == 1.0
    assert pack.complete is True
    assert pack.promotion_eligible is True

    authorization = await service.record_promotion_authorization(
        db, PromotionRequest(result_pack_id=pack.id, decision="APPROVED"),
        approver_id="release-owner", tenant_id="tenant-1",
    )
    assert authorization.approver_id == "release-owner"


@pytest.mark.asyncio
async def test_empty_dataset_never_receives_simulated_metrics(evaluation_db) -> None:
    db = evaluation_db
    payload = EvaluationDatasetCreate(
        id="empty", version="1", domain="accounting", split="development", cases=[],
    )
    await service.create_dataset(db, payload, tenant_id="tenant-1", actor_id="owner")
    with pytest.raises(HTTPException) as exc:
        await service.freeze_dataset(db, "empty", tenant_id="tenant-1")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_threshold_approval_requires_a_different_user(evaluation_db) -> None:
    db = evaluation_db
    dataset = await service.create_dataset(
        db, _dataset("approval"), tenant_id="tenant-1", actor_id="owner",
    )
    threshold = await service.create_threshold_set(
        db,
        ThresholdSetCreate(
            id="threshold-approval",
            dataset_id=dataset.id,
            dataset_version_id=dataset.version,
            metrics={"minimum_case_count": 2},
        ),
        tenant_id="tenant-1",
        actor_id="owner",
    )
    assert threshold.status == "PendingReview"
    with pytest.raises(HTTPException) as exc:
        await service.approve_threshold_set(
            db, threshold.id, tenant_id="tenant-1", approver_id="owner",
        )
    assert exc.value.status_code == 403

    approved = await service.approve_threshold_set(
        db, threshold.id, tenant_id="tenant-1", approver_id="checker",
    )
    assert approved.status == "Approved"
    assert approved.approved_by == "checker"


@pytest.mark.asyncio
async def test_ineligible_pack_cannot_be_overridden(evaluation_db) -> None:
    db = evaluation_db
    dataset = await service.create_dataset(
        db, _dataset("small"), tenant_id="tenant-1", actor_id="owner",
    )
    await service.freeze_dataset(db, dataset.id, tenant_id="tenant-1")
    await service.create_threshold_set(db, ThresholdSetCreate(
        id="threshold-small", dataset_id=dataset.id, dataset_version_id="1.0",
        metrics={"minimum_case_count": 300}, zero_tolerance_metrics=[],
        owner="owner", approver="checker",
    ), tenant_id="tenant-1", actor_id="owner")
    await service.approve_threshold_set(
        db, "threshold-small", tenant_id="tenant-1", approver_id="checker",
    )

    async def fake_ask(*args, **kwargs):
        payload = {
            "query_id": "q", "correlation_id": "c", "outcome": "answered",
            "route": "LLM", "source_bundle": {"sources": []}, "answer": {},
        }
        return SimpleNamespace(outcome="answered", model_dump=lambda **_: payload)

    from pytest import MonkeyPatch
    monkeypatch = MonkeyPatch()
    monkeypatch.setattr(service, "ask_kriton", fake_ask)
    manifest = {"candidate": "small"}
    try:
        run, pack = await service.execute_evaluation_run(
            db, None, dataset.id, "threshold-small", _manifest_hash(manifest), manifest,
            tenant_id="tenant-1", actor_id="runner", actor_role="Risk Admin",
        )
        results = await service.list_case_results(db, run.id, tenant_id="tenant-1")
        for result in results:
            await service.record_reviewer_judgment(
                db, result.id, ReviewerJudgmentCreate(verdict="ACCEPT"),
                reviewer_id=f"r-{result.id}", tenant_id="tenant-1",
            )
        _, pack = await service.finalize_evaluation_run(db, run.id, tenant_id="tenant-1")
        assert pack.promotion_eligible is False
        with pytest.raises(HTTPException) as exc:
            await service.record_promotion_authorization(
                db, PromotionRequest(
                    result_pack_id=pack.id, decision="APPROVED",
                    residual_risk_accepted=True,
                ),
                approver_id="release-owner", tenant_id="tenant-1",
            )
        assert exc.value.status_code == 409
    finally:
        monkeypatch.undo()
