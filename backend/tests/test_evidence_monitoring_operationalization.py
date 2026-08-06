"""Tests for V8.5 — production operationalization of evidence monitoring:
run-level idempotency/retry-safety, safe failure classification, the
scheduled/manual run-history split on the admin status panel, and the
service-role auth boundary for the scheduled-monitoring trigger.

Same persistent-SQLite-file precedent as test_evidence_monitoring.py.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.domains.identity.rbac import require_service_role
from app.orchestration import evidence_monitoring as monitoring
from app.orchestration import visualization_gaps as gaps
from app.orchestration.models import VisualizationEvidenceAggregationRun


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


async def _seed(db, *, tenant_id, count, environment="production", conversations=None, actors=None,
                 requested_chart_type="treemap", data_shape_class=gaps.DataShapeClass.PART_TO_WHOLE,
                 gap_type=gaps.VisualizationGapType.UNSUPPORTED_PRODUCT_CAPABILITY, fallback_chart_type="donut"):
    conversations = conversations or count
    actors = actors or count
    conversation_prefix, actor_prefix = _unique("conv"), _unique("actor")
    for i in range(count):
        await gaps.record_gap_event(
            db, tenant_id=tenant_id, actor_id=f"{actor_prefix}-{i % actors}", conversation_id=f"{conversation_prefix}-{i % conversations}",
            analytical_intent="composition", requested_chart_type=requested_chart_type, gap_type=gap_type,
            data_shape_class=data_shape_class, fallback_chart_type=fallback_chart_type,
            fallback_output_type=gaps.FallbackOutputType.CHART, registry_candidate_count=3,
            ranking_version="1.0.0", environment=environment,
        )


async def _insert_run_row(db, *, tenant_id, status, trigger_source="manual", monitoring_period=None, started_at=None) -> VisualizationEvidenceAggregationRun:
    row = VisualizationEvidenceAggregationRun(
        tenant_id=tenant_id, started_at=started_at or datetime.now(timezone.utc),
        monitoring_period=monitoring_period or datetime.now(timezone.utc).date().isoformat(),
        trigger_source=trigger_source, status=status, evidence_version="", valid_event_count=0,
        distinct_conversation_count=0, distinct_actor_count=0, eligible_finding_count=0,
        created_report_id=None, draft_created=False, alert_created=False, failure_category=None,
        triggered_by=trigger_source,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ── run-level idempotency (tenant_id, monitoring_period) ──────────────────

@pytest.mark.asyncio
async def test_second_same_day_run_short_circuits_without_reaggregating(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150)
    first = await monitoring.run_evidence_monitoring(db, tenant_id)
    second = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert first.draft_created is True
    assert second.deduplicated is True
    assert second.draft_created is False  # call-scoped: this call created nothing new
    assert second.evidence_version == first.evidence_version
    assert second.report_id == first.report_id

    rows = (await db.execute(
        select(VisualizationEvidenceAggregationRun).where(VisualizationEvidenceAggregationRun.tenant_id == tenant_id)
    )).scalars().all()
    assert len(rows) == 1  # no second row written for the short-circuited call


@pytest.mark.asyncio
async def test_concurrent_run_is_rejected_not_raced(db):
    tenant_id = _unique("tenant")
    await _insert_run_row(db, tenant_id=tenant_id, status="running")
    with pytest.raises(monitoring.MonitoringRunAlreadyActiveError):
        await monitoring.run_evidence_monitoring(db, tenant_id)


@pytest.mark.asyncio
async def test_failed_run_can_be_retried_the_same_day(db):
    tenant_id = _unique("tenant")
    await _insert_run_row(db, tenant_id=tenant_id, status="failed")
    await _seed(db, tenant_id=tenant_id, count=150)
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert result.status == "succeeded"
    assert result.draft_created is True

    rows = (await db.execute(
        select(VisualizationEvidenceAggregationRun).where(VisualizationEvidenceAggregationRun.tenant_id == tenant_id)
    )).scalars().all()
    assert len(rows) == 2  # the original failed attempt, plus this fresh one


# ── safe failure classification ────────────────────────────────────────────

def test_transient_infra_errors_are_retryable():
    from sqlalchemy.exc import OperationalError
    category = monitoring._classify_failure(OperationalError("stmt", {}, Exception("connection reset")))
    assert category == monitoring.FailureCategory.TRANSIENT_INFRA_ERROR.value
    assert monitoring.is_transient_failure_category(category) is True


@pytest.mark.parametrize("exc,expected", [
    (ValueError("bad input"), monitoring.FailureCategory.VALIDATION_ERROR.value),
    (PermissionError("nope"), monitoring.FailureCategory.AUTHORIZATION_ERROR.value),
    (RuntimeError("mystery"), monitoring.FailureCategory.UNKNOWN_ERROR.value),
])
def test_non_transient_failures_are_never_retryable(exc, expected):
    category = monitoring._classify_failure(exc)
    assert category == expected
    assert monitoring.is_transient_failure_category(category) is False


@pytest.mark.asyncio
async def test_failure_records_only_a_safe_category_never_the_raw_message(db, monkeypatch):
    tenant_id = _unique("tenant")
    secret_message = "SELECT * FROM secret_customer_table WHERE ssn = '123-45-6789'"

    async def _boom(*args, **kwargs):
        raise ValueError(secret_message)

    monkeypatch.setattr(monitoring, "aggregate_production_evidence", _boom)
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert result.status == "failed"
    assert result.failure_category == monitoring.FailureCategory.VALIDATION_ERROR.value

    row = await db.scalar(select(VisualizationEvidenceAggregationRun).where(VisualizationEvidenceAggregationRun.tenant_id == tenant_id))
    assert row.failure_category == monitoring.FailureCategory.VALIDATION_ERROR.value
    assert secret_message not in (row.failure_category or "")
    # Structural — the column simply cannot hold the message even if a
    # caller tried: it's a plain enum-valued String, not free text.
    assert VisualizationEvidenceAggregationRun.__table__.columns["failure_category"].type.python_type is str


@pytest.mark.asyncio
async def test_a_failed_run_never_creates_a_draft_or_alert(db, monkeypatch):
    tenant_id = _unique("tenant")

    async def _boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(monitoring, "aggregate_production_evidence", _boom)
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert result.draft_created is False
    assert result.alert_created is False
    assert result.report_id is None


# ── scheduled vs manual run history on the status panel ───────────────────

@pytest.mark.asyncio
async def test_status_tracks_last_scheduled_and_last_manual_runs_separately(db):
    tenant_id = _unique("tenant")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1))
    await _insert_run_row(db, tenant_id=tenant_id, status="succeeded", trigger_source="scheduled",
                           monitoring_period=yesterday.date().isoformat(), started_at=yesterday)
    today = datetime.now(timezone.utc)
    await _insert_run_row(db, tenant_id=tenant_id, status="succeeded", trigger_source="manual",
                           monitoring_period=today.date().isoformat(), started_at=today)

    status = await monitoring.get_monitoring_status(db, tenant_id)
    assert status.last_scheduled_run is not None
    assert status.last_scheduled_run.trigger_source == "scheduled"
    assert status.last_manual_run is not None
    assert status.last_manual_run.trigger_source == "manual"


@pytest.mark.asyncio
async def test_status_shows_current_run_while_active_and_excludes_it_from_history(db):
    tenant_id = _unique("tenant")
    await _insert_run_row(db, tenant_id=tenant_id, status="running", trigger_source="scheduled")
    status = await monitoring.get_monitoring_status(db, tenant_id)
    assert status.current_run is not None
    assert status.current_run.status == "running"
    assert status.last_scheduled_run is None  # the only row is still running, not a completed history entry


@pytest.mark.asyncio
async def test_status_distinguishes_directional_signal_from_collecting_evidence(db):
    tenant_id = _unique("tenant")
    status = await monitoring.get_monitoring_status(db, tenant_id)
    assert status.monitoring_status == "collecting_evidence"

    await _seed(db, tenant_id=tenant_id, count=40)  # 30-99 -> directional_signal
    status = await monitoring.get_monitoring_status(db, tenant_id)
    assert status.monitoring_status == "directional_signal"


@pytest.mark.asyncio
async def test_status_shows_approved_findings_available_after_maker_checker_approval(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150)
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    admin_id = _unique("admin")
    await gaps.transition_report(db, tenant_id, result.report_id, admin_id, "under_review")
    await gaps.transition_report(db, tenant_id, result.report_id, admin_id, "approved")

    status = await monitoring.get_monitoring_status(db, tenant_id)
    assert status.monitoring_status == "approved_findings_available"


def test_next_scheduled_run_is_always_strictly_in_the_future():
    settings = get_settings()
    for hour, minute in [(0, 0), (6, 0), (23, 59)]:
        settings.EVIDENCE_MONITORING_SCHEDULE_HOUR_UTC = hour
        settings.EVIDENCE_MONITORING_SCHEDULE_MINUTE_UTC = minute
        now = datetime(2026, 8, 3, 12, 30, tzinfo=timezone.utc)
        next_run = monitoring._next_scheduled_run_at(now)
        assert next_run > now
        assert next_run.hour == hour and next_run.minute == minute
    settings.EVIDENCE_MONITORING_SCHEDULE_HOUR_UTC = 6
    settings.EVIDENCE_MONITORING_SCHEDULE_MINUTE_UTC = 0


# ── selection/answer-pipeline isolation ─────────────────────────────────────

@pytest.mark.asyncio
async def test_maker_checker_approval_of_a_scheduled_draft_never_touches_chart_selection(db):
    from app.orchestration.presentation_dataprofile import AnalyticalIntent, DataProfile, select_chart_type

    profile = DataProfile(dimensions=("D",), measures=("A",), category_count=5, measure_count=1)
    before = select_chart_type(AnalyticalIntent.COMPARISON, profile)

    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150)
    result = await monitoring.run_evidence_monitoring(db, tenant_id, trigger_source="scheduled", triggered_by="scheduled:railway-cron")
    admin_id = _unique("admin")
    await gaps.transition_report(db, tenant_id, result.report_id, admin_id, "under_review")
    approved = await gaps.transition_report(db, tenant_id, result.report_id, admin_id, "approved")

    after = select_chart_type(AnalyticalIntent.COMPARISON, profile)
    assert before == after
    assert approved.artifact["selection_activation"] == "none"


def test_evidence_monitoring_module_has_no_dependency_on_the_answer_pipeline():
    """A scheduler/rollback failure in this module must be structurally
    incapable of affecting Ask Kriton answers — enforced here at the import
    level rather than only behaviorally: this module never imports
    orchestration.service (the answer-generation entrypoint)."""
    import app.orchestration.evidence_monitoring as mod
    source = open(mod.__file__).read()
    assert "orchestration.service" not in source
    assert "orchestration import service" not in source


# ── service-role auth boundary ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_require_service_role_fails_closed_when_unconfigured():
    settings = get_settings()
    original = settings.EVIDENCE_MONITORING_SERVICE_TOKEN
    settings.EVIDENCE_MONITORING_SERVICE_TOKEN = ""
    try:
        with pytest.raises(HTTPException) as exc_info:
            await require_service_role(x_service_token="anything")
        assert exc_info.value.status_code == 401
    finally:
        settings.EVIDENCE_MONITORING_SERVICE_TOKEN = original


@pytest.mark.asyncio
async def test_require_service_role_rejects_missing_or_wrong_token():
    settings = get_settings()
    original = settings.EVIDENCE_MONITORING_SERVICE_TOKEN
    settings.EVIDENCE_MONITORING_SERVICE_TOKEN = "correct-secret"
    try:
        with pytest.raises(HTTPException) as exc_info:
            await require_service_role(x_service_token=None)
        assert exc_info.value.status_code == 401
        with pytest.raises(HTTPException):
            await require_service_role(x_service_token="wrong-secret")
    finally:
        settings.EVIDENCE_MONITORING_SERVICE_TOKEN = original


@pytest.mark.asyncio
async def test_require_service_role_accepts_the_configured_token():
    settings = get_settings()
    original = settings.EVIDENCE_MONITORING_SERVICE_TOKEN
    settings.EVIDENCE_MONITORING_SERVICE_TOKEN = "correct-secret"
    try:
        assert await require_service_role(x_service_token="correct-secret") is None
    finally:
        settings.EVIDENCE_MONITORING_SERVICE_TOKEN = original


# ── router wiring: no report-approval capability on the scheduled path ────

def test_scheduled_run_router_never_exposes_report_transition():
    """The scheduled-monitoring endpoint only ever calls
    run_evidence_monitoring, which never transitions a report past "draft"
    — approval requires the separate, human-admin-only
    /reports/{id}/{status} endpoint. Locks in requirement 2 ("no report
    approval capability") at the router-wiring level."""
    import inspect

    from app.orchestration import visualization_gaps_router as router_module

    source = inspect.getsource(router_module.post_evidence_monitoring_scheduled_run)
    assert "transition_report" not in source
    assert "approve" not in source.lower()
