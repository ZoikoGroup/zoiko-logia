"""Tests for V8.4 — production evidence monitoring and review.

Same persistent-SQLite-file precedent as test_visualization_analytics.py /
test_visualization_telemetry.py: tests/conftest.py points at a real file
(./test.db) shared across separate `pytest` runs, so every id is
uuid-suffixed per test rather than a fixed string.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.orchestration import evidence_monitoring as monitoring
from app.orchestration import visualization_gaps as gaps
from app.orchestration.models import VisualizationEvidenceAlert, VisualizationGapReport


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


async def _seed(
    db, *, tenant_id, count, environment="production", conversations=None, actors=None,
    requested_chart_type="treemap", data_shape_class=gaps.DataShapeClass.PART_TO_WHOLE,
    gap_type=gaps.VisualizationGapType.UNSUPPORTED_PRODUCT_CAPABILITY,
    fallback_chart_type="donut", conversation_prefix=None, actor_prefix=None,
):
    # record_gap_event's dedup_key is a function of (tenant, actor,
    # conversation, chart_type, gap_type, shape) — with chart_type/gap_type/
    # shape held fixed here, only the (actor, conversation) PAIR makes an
    # event unique, so the two pool sizes must multiply out to at least
    # `count` distinct pairs or later events silently dedup away. Default to
    # a pool exactly `count` wide on each axis (unique pairs via i % count),
    # so every event survives dedup by default; callers force a single-actor
    # or single-conversation pool explicitly to exercise the diversity gate.
    conversations = conversations or count
    actors = actors or count
    conversation_prefix = conversation_prefix or _unique("conv")
    actor_prefix = actor_prefix or _unique("actor")
    for i in range(count):
        await gaps.record_gap_event(
            db, tenant_id=tenant_id,
            actor_id=f"{actor_prefix}-{i % actors}", conversation_id=f"{conversation_prefix}-{i % conversations}",
            analytical_intent="composition", requested_chart_type=requested_chart_type, gap_type=gap_type,
            data_shape_class=data_shape_class, fallback_chart_type=fallback_chart_type,
            fallback_output_type=gaps.FallbackOutputType.CHART, registry_candidate_count=3,
            ranking_version="1.0.0", environment=environment,
        )


# ── zero / insufficient evidence ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_zero_events_creates_no_draft_report(db):
    tenant_id = _unique("tenant")
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert result.draft_created is False
    assert result.report_id is None
    assert result.valid_event_count == 0


@pytest.mark.asyncio
async def test_insufficient_evidence_creates_no_draft_report(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=29)
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert result.draft_created is False
    assert result.report_id is None
    snapshot = await monitoring.aggregate_production_evidence(db, tenant_id)
    assert snapshot.findings[0].evidence_status == gaps.EvidenceStatus.INSUFFICIENT_EVIDENCE


# ── environment exclusion ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_development_and_test_events_never_count(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150, environment="development")
    await _seed(db, tenant_id=tenant_id, count=150, environment="test")
    snapshot = await monitoring.aggregate_production_evidence(db, tenant_id)
    assert snapshot.valid_event_count == 0
    assert snapshot.findings == []
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert result.draft_created is False


# ── duplicates ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_events_do_not_inflate_evidence(db):
    tenant_id = _unique("tenant")
    actor_id, conversation_id = _unique("actor"), _unique("conv")
    for _ in range(3):
        await gaps.record_gap_event(
            db, tenant_id=tenant_id, actor_id=actor_id, conversation_id=conversation_id,
            analytical_intent="composition", requested_chart_type="treemap",
            gap_type=gaps.VisualizationGapType.UNSUPPORTED_PRODUCT_CAPABILITY,
            data_shape_class=gaps.DataShapeClass.PART_TO_WHOLE, fallback_chart_type="donut",
            fallback_output_type=gaps.FallbackOutputType.CHART, registry_candidate_count=3,
            ranking_version="1.0.0", environment="production",
        )
    snapshot = await monitoring.aggregate_production_evidence(db, tenant_id)
    assert snapshot.valid_event_count == 1
    assert snapshot.findings[0].sample_size == 1


# ── invalid data shapes ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_data_shapes_do_not_count_as_chart_evidence(db):
    tenant_id = _unique("tenant")
    # "treemap" only supports PART_TO_WHOLE — TEMPORAL_SINGLE_SERIES cannot
    # support it, so valid_evidence is False at write time.
    await _seed(db, tenant_id=tenant_id, count=150, requested_chart_type="treemap",
                data_shape_class=gaps.DataShapeClass.TEMPORAL_SINGLE_SERIES)
    snapshot = await monitoring.aggregate_production_evidence(db, tenant_id)
    assert snapshot.valid_event_count == 0
    assert snapshot.findings == []


# ── structurally invalid requests excluded ─────────────────────────────────

@pytest.mark.asyncio
async def test_structurally_invalid_requests_are_excluded_from_evidence(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150, gap_type=gaps.VisualizationGapType.INCOMPATIBLE_REQUEST_DATA)
    snapshot = await monitoring.aggregate_production_evidence(db, tenant_id)
    assert snapshot.valid_event_count == 0
    assert snapshot.findings == []


# ── source-diversity gate ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_actor_alone_cannot_qualify_a_finding(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150, conversations=150, actors=1)
    snapshot = await monitoring.aggregate_production_evidence(db, tenant_id)
    assert snapshot.findings[0].sample_size >= 100
    assert snapshot.findings[0].evidence_status == gaps.EvidenceStatus.DIRECTIONAL_SIGNAL
    assert snapshot.eligible_findings == []
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert result.draft_created is False


@pytest.mark.asyncio
async def test_single_conversation_alone_cannot_qualify_a_finding(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150, conversations=1, actors=150)
    snapshot = await monitoring.aggregate_production_evidence(db, tenant_id)
    assert snapshot.findings[0].evidence_status == gaps.EvidenceStatus.DIRECTIONAL_SIGNAL
    assert snapshot.eligible_findings == []


# ── eligible evidence creates one draft ────────────────────────────────────

@pytest.mark.asyncio
async def test_eligible_evidence_creates_one_draft_artifact(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150)
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert result.draft_created is True
    assert result.deduplicated is False
    assert result.report_id is not None

    report = await db.get(VisualizationGapReport, result.report_id)
    assert report.status == "draft"
    assert report.created_by == monitoring.MONITORING_ACTOR
    assert report.artifact["selection_activation"] == "none"
    assert report.artifact["status"] == "draft"
    assert report.artifact["evidence_version"] == result.evidence_version
    assert len(report.artifact["findings"]) <= 3

    alerts = (await db.execute(
        select(VisualizationEvidenceAlert).where(VisualizationEvidenceAlert.tenant_id == tenant_id)
    )).scalars().all()
    assert len(alerts) == 1
    assert alerts[0].report_id == report.id


@pytest.mark.asyncio
async def test_draft_findings_are_capped_at_three(db):
    tenant_id = _unique("tenant")
    # Four independent, mutually-eligible findings via four different
    # requested chart types (each is its own aggregation group).
    for chart_type in ("treemap", "gauge", "violin", "sankey"):
        shape = {
            "treemap": gaps.DataShapeClass.PART_TO_WHOLE, "gauge": gaps.DataShapeClass.CATEGORICAL_SINGLE_MEASURE,
            "violin": gaps.DataShapeClass.DISTRIBUTION, "sankey": gaps.DataShapeClass.FLOW,
        }[chart_type]
        await _seed(db, tenant_id=tenant_id, count=150,
                    requested_chart_type=chart_type, data_shape_class=shape, fallback_chart_type=None)
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert result.eligible_finding_count == 4
    report = await db.get(VisualizationGapReport, result.report_id)
    assert len(report.artifact["findings"]) == 3


# ── evidence-version dedup ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_same_evidence_version_does_not_create_duplicate_drafts_or_alerts(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150)
    first = await monitoring.run_evidence_monitoring(db, tenant_id)
    second = await monitoring.run_evidence_monitoring(db, tenant_id)
    assert first.draft_created is True
    assert second.draft_created is False
    assert second.deduplicated is True
    assert second.report_id == first.report_id

    reports = (await db.execute(
        select(VisualizationGapReport).where(VisualizationGapReport.tenant_id == tenant_id)
    )).scalars().all()
    assert len(reports) == 1
    alerts = (await db.execute(
        select(VisualizationEvidenceAlert).where(VisualizationEvidenceAlert.tenant_id == tenant_id)
    )).scalars().all()
    assert len(alerts) == 1


# ── draft creation never touches chart selection ───────────────────────────

@pytest.mark.asyncio
async def test_draft_creation_never_changes_chart_selection(db):
    from app.orchestration.presentation_dataprofile import AnalyticalIntent, DataProfile, select_chart_type

    profile = DataProfile(dimensions=("D",), measures=("A",), category_count=5, measure_count=1)
    before = select_chart_type(AnalyticalIntent.COMPARISON, profile)

    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150)
    await monitoring.run_evidence_monitoring(db, tenant_id)

    after = select_chart_type(AnalyticalIntent.COMPARISON, profile)
    assert before == after


# ── maker-checker remains mandatory ────────────────────────────────────────

@pytest.mark.asyncio
async def test_maker_checker_approval_remains_required_for_monitoring_drafts(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150)
    result = await monitoring.run_evidence_monitoring(db, tenant_id)

    admin_id = _unique("admin")
    with pytest.raises(ValueError):
        await gaps.transition_report(db, tenant_id, result.report_id, admin_id, "approved")

    under_review = await gaps.transition_report(db, tenant_id, result.report_id, admin_id, "under_review")
    assert under_review.status == "under_review"
    approved = await gaps.transition_report(db, tenant_id, result.report_id, admin_id, "approved")
    assert approved.status == "approved"
    assert approved.approved_by == admin_id


# ── tenant isolation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evidence_monitoring_is_tenant_isolated(db):
    tenant_a, tenant_b = _unique("tenant"), _unique("tenant")
    await _seed(db, tenant_id=tenant_a, count=150)
    result_a = await monitoring.run_evidence_monitoring(db, tenant_a)
    result_b = await monitoring.run_evidence_monitoring(db, tenant_b)
    assert result_a.draft_created is True
    assert result_b.draft_created is False
    assert result_b.valid_event_count == 0

    status_b = await monitoring.get_monitoring_status(db, tenant_b)
    assert status_b.last_report is None
    assert status_b.monitoring_status == "collecting_evidence"


# ── admin status endpoint backing function ─────────────────────────────────

@pytest.mark.asyncio
async def test_status_reflects_collecting_ready_and_awaiting_states(db):
    tenant_id = _unique("tenant")
    status = await monitoring.get_monitoring_status(db, tenant_id)
    assert status.monitoring_status == "collecting_evidence"
    assert status.last_aggregation_at is None

    await _seed(db, tenant_id=tenant_id, count=150)
    result = await monitoring.run_evidence_monitoring(db, tenant_id)
    status = await monitoring.get_monitoring_status(db, tenant_id)
    assert status.monitoring_status == "ready_for_review"
    assert status.last_aggregation_at is not None
    assert status.last_report is not None
    assert status.last_report.id == result.report_id

    admin_id = _unique("admin")
    await gaps.transition_report(db, tenant_id, result.report_id, admin_id, "under_review")
    status = await monitoring.get_monitoring_status(db, tenant_id)
    assert status.monitoring_status == "awaiting_approval"


@pytest.mark.asyncio
async def test_status_never_triggers_a_new_run_or_draft(db):
    tenant_id = _unique("tenant")
    await _seed(db, tenant_id=tenant_id, count=150)
    await monitoring.get_monitoring_status(db, tenant_id)
    reports = (await db.execute(
        select(VisualizationGapReport).where(VisualizationGapReport.tenant_id == tenant_id)
    )).scalars().all()
    assert reports == []
