"""Tests for the V8.5 scheduled-monitoring CLI job's retry wrapper —
scripts/run_evidence_monitoring_job.py. Only _run_for_tenant's decision
logic is exercised here (retry transient failures a bounded number of
times, never retry permanent ones); main()'s tenant enumeration and engine
disposal are operational glue better left to a real deployment smoke test
than a unit test.
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_evidence_monitoring_job as job  # noqa: E402
from app.orchestration import evidence_monitoring as monitoring  # noqa: E402


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _result(status, failure_category=None):
    return monitoring.MonitoringRunResult(
        tenant_id="t1", started_at=datetime.now(timezone.utc),
        completed_at=None, status=status, trigger_source="scheduled", monitoring_period="2026-08-03",
        evidence_version="v1", valid_event_count=0, distinct_conversation_count=0, distinct_actor_count=0,
        eligible_finding_count=0, draft_created=False, alert_created=False, deduplicated=False,
        report_id=None, failure_category=failure_category,
    )


@pytest.mark.asyncio
async def test_transient_failure_is_retried_up_to_the_cap(monkeypatch):
    calls = []

    async def fake_run(db, tenant_id, *, trigger_source, triggered_by):
        calls.append(1)
        return _result("failed", monitoring.FailureCategory.TRANSIENT_INFRA_ERROR.value)

    monkeypatch.setattr(monitoring, "run_evidence_monitoring", fake_run)
    monkeypatch.setattr(job, "_RETRY_BACKOFF_SECONDS", 0)
    result = await job._run_for_tenant(_unique("tenant"))
    assert result.status == "failed"
    assert len(calls) == 1 + job._MAX_TRANSIENT_RETRIES


@pytest.mark.asyncio
async def test_transient_failure_that_recovers_stops_retrying(monkeypatch):
    calls = []

    async def fake_run(db, tenant_id, *, trigger_source, triggered_by):
        calls.append(1)
        if len(calls) < 2:
            return _result("failed", monitoring.FailureCategory.TRANSIENT_INFRA_ERROR.value)
        return _result("succeeded")

    monkeypatch.setattr(monitoring, "run_evidence_monitoring", fake_run)
    monkeypatch.setattr(job, "_RETRY_BACKOFF_SECONDS", 0)
    result = await job._run_for_tenant(_unique("tenant"))
    assert result.status == "succeeded"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_validation_failure_is_never_retried(monkeypatch):
    calls = []

    async def fake_run(db, tenant_id, *, trigger_source, triggered_by):
        calls.append(1)
        return _result("failed", monitoring.FailureCategory.VALIDATION_ERROR.value)

    monkeypatch.setattr(monitoring, "run_evidence_monitoring", fake_run)
    monkeypatch.setattr(job, "_RETRY_BACKOFF_SECONDS", 0)
    result = await job._run_for_tenant(_unique("tenant"))
    assert result.status == "failed"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_already_active_run_is_skipped_not_treated_as_a_failure(monkeypatch):
    async def fake_run(db, tenant_id, *, trigger_source, triggered_by):
        raise monitoring.MonitoringRunAlreadyActiveError(tenant_id)

    monkeypatch.setattr(monitoring, "run_evidence_monitoring", fake_run)
    result = await job._run_for_tenant(_unique("tenant"))
    assert result is None
