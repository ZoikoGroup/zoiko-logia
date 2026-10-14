"""Evaluation Gates page views: tenant-scoped cases, run checks, run history,
dataset list, and rejecting an ineligible pack. Measurement itself is
covered by test_evaluation_run_honesty.py."""
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.evaluation import service
from app.domains.evaluation.models import BenchmarkCase, EvaluationDataset, ThresholdSet


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [model.__table__ for model in (EvaluationDataset, BenchmarkCase, ThresholdSet)]
    tables += [Base.metadata.tables[name] for name in ("evaluation_runs", "result_packs", "promotion_authorizations")]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add(EvaluationDataset(id="ds", version="1", domain="tax"))
        session.add(EvaluationDataset(id="empty", version="1", domain="tax"))
        session.add(ThresholdSet(id="ts", dataset_id="ds", dataset_version_id="1", owner="qa", approver="risk",
                                 metrics={"pii_leak": 0.0, "source_recall": 0.5},
                                 zero_tolerance_metrics=["pii_leak"]))
        session.add(BenchmarkCase(id="c1", dataset_id="ds", query_text="What is VAT?", risk_scope="LOW",
                                  gold_answer="VAT is a consumption tax (HMRC-VAT-1).",
                                  source_refs=["HMRC-VAT-1", "HMRC-VAT-2"]))
        session.add(BenchmarkCase(id="c2", dataset_id="ds", tenant_id="other", query_text="Other tenant",
                                  gold_answer="private@example.com", risk_scope="LOW"))
        await session.commit()
        yield session
    await engine.dispose()


async def test_run_uses_only_this_tenants_cases_and_reports_checks(db):
    run, pack = await service.execute_evaluation_run(db, "ds", "ts", "", tenant_id="t")
    # The other tenant's case (which holds an email address) never ran.
    assert run.metrics_summary["cases_evaluated"] == 1
    assert run.metrics_summary["pii_leak"] == 0.0

    checks = service.run_checks(run, pack, await service.get_threshold_set(db, "ts"))
    assert checks["config_hash_valid"] is True
    assert checks["case_count"] == 1
    # source_recall is not measured, so it is reported as missing, not guessed.
    assert checks["unmeasured_metrics"] == ["source_recall"]
    assert [failure["metric"] for failure in checks["failures"]] == ["source_recall"]


async def test_history_and_dataset_list(db):
    await service.execute_evaluation_run(db, "ds", "ts", "", tenant_id="t")
    await service.execute_evaluation_run(db, "ds", "ts", "sha256-typed-by-hand", tenant_id="t")

    history = await service.list_runs(db, tenant_id="t")
    assert [entry["matches_current_config"] for entry in history] == [False, True]
    datasets = {d["id"]: d["case_count"] for d in await service.list_datasets(db, tenant_id="t")}
    assert datasets == {"ds": 1, "empty": 0}


async def test_an_ineligible_pack_can_be_rejected_but_not_approved(db):
    from app.domains.evaluation.schemas import PromotionRequest

    _, pack = await service.execute_evaluation_run(db, "ds", "ts", "sha256-old", tenant_id="t")
    assert pack.promotion_eligible is False
    with pytest.raises(HTTPException):
        await service.record_promotion_authorization(db, PromotionRequest(
            result_pack_id=pack.id, decision="APPROVED", approver_id="qa@example.com"))
    rejected = await service.record_promotion_authorization(db, PromotionRequest(
        result_pack_id=pack.id, decision="REJECTED", approver_id="qa@example.com"))
    assert rejected.decision == "REJECTED"
