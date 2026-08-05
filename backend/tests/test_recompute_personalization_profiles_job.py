"""Tests for the V10 scheduled-recomputation CLI job's retry wrapper —
scripts/recompute_personalization_profiles.py. Mirrors
test_run_evidence_monitoring_job.py's (V8.5) coverage of the same contract:
retry only transient failures, a bounded number of times, and treat an
already-active run as a skip rather than a failure.
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import recompute_personalization_profiles as job  # noqa: E402
from app.orchestration import visualization_personalization as personalization  # noqa: E402


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _result(status, failure_category=None):
    return personalization.RecomputationRunResult(
        tenant_id="t1", started_at=datetime.now(timezone.utc), completed_at=None, status=status,
        processing_date="2026-08-03", profile_version="personalization-1.0",
        profiles_recomputed_count=0, event_count=0, failure_category=failure_category,
    )


@pytest.mark.asyncio
async def test_transient_failure_is_retried_up_to_the_cap(monkeypatch):
    calls = []

    async def fake_recompute(db, tenant_id, *, triggered_by):
        calls.append(1)
        return _result("failed", personalization.FailureCategory.TRANSIENT_INFRA_ERROR.value)

    monkeypatch.setattr(personalization, "recompute_tenant_profiles", fake_recompute)
    monkeypatch.setattr(job, "_RETRY_BACKOFF_SECONDS", 0)
    result = await job._run_for_tenant(_unique("tenant"))
    assert result.status == "failed"
    assert len(calls) == 1 + job._MAX_TRANSIENT_RETRIES


@pytest.mark.asyncio
async def test_validation_failure_is_never_retried(monkeypatch):
    calls = []

    async def fake_recompute(db, tenant_id, *, triggered_by):
        calls.append(1)
        return _result("failed", personalization.FailureCategory.VALIDATION_ERROR.value)

    monkeypatch.setattr(personalization, "recompute_tenant_profiles", fake_recompute)
    monkeypatch.setattr(job, "_RETRY_BACKOFF_SECONDS", 0)
    result = await job._run_for_tenant(_unique("tenant"))
    assert result.status == "failed"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_already_active_run_is_skipped_not_treated_as_a_failure(monkeypatch):
    async def fake_recompute(db, tenant_id, *, triggered_by):
        raise personalization.MonitoringRunAlreadyActiveError(tenant_id)

    monkeypatch.setattr(personalization, "recompute_tenant_profiles", fake_recompute)
    result = await job._run_for_tenant(_unique("tenant"))
    assert result is None
