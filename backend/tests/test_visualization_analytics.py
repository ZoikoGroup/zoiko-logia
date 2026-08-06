"""Tests for Dynamic Visualization Selection v6 — recommendation-quality
aggregation, minimum-sample evidence classification, replacement matrices,
and the ranking-configuration governance pipeline.

Same persistent-SQLite-file precedent as test_visualization_telemetry.py:
IDs are uuid-suffixed per test, never fixed strings, since tests/conftest.py
points at a real file (./test.db) shared across separate `pytest` runs.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin
from app.orchestration import ranking_configuration as ranking_configuration_service
from app.orchestration import visualization_analytics as analytics
from app.orchestration.models import VisualizationTelemetryEvent
from app.orchestration.presentation_dataprofile import (
    WEIGHT_BOUNDS,
    WEIGHT_DIMENSIONS,
    AnalyticalIntent,
    DataProfile,
    current_weights,
    select_chart_type,
    select_chart_with_alternatives,
)
from app.orchestration.presentation_dataprofile import generate_candidates
from app.orchestration.visualization_analytics_schemas import (
    EvidenceStatus,
    RankingConfigurationCreate,
    WeightAdjustmentProposal,
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


def _event(
    *, event_name, tenant_id, query_id, created_at,
    original_chart_type=None, active_chart_type=None, analytical_intent=None,
    chart_family=None, renderer=None, selection_source=None, ranking_version=None,
    actor_id=None, conversation_id=None,
) -> VisualizationTelemetryEvent:
    return VisualizationTelemetryEvent(
        event_name=event_name, tenant_id=tenant_id, actor_id=actor_id or _unique("user"),
        conversation_id=conversation_id, query_id=query_id,
        analytical_intent=analytical_intent, original_chart_type=original_chart_type,
        active_chart_type=active_chart_type, alternative_count=1, selection_source=selection_source,
        renderer=renderer, schema_version="1.0", chart_family=chart_family, ranking_version=ranking_version,
        created_at=created_at,
    )


async def _add_all(db, events: list[VisualizationTelemetryEvent]) -> None:
    for event in events:
        db.add(event)
    await db.commit()


# ── AnalyticsFilters / validation ────────────────────────────────────────

def test_tenant_id_is_required_for_every_aggregation_query():
    with pytest.raises(ValueError):
        analytics.AnalyticsFilters(tenant_id="")


def test_invalid_date_range_is_rejected():
    with pytest.raises(analytics.InvalidDateRangeError):
        analytics.AnalyticsFilters(tenant_id="t1", date_from=date(2026, 6, 1), date_to=date(2026, 5, 1))


def test_valid_date_range_is_accepted():
    filters = analytics.AnalyticsFilters(tenant_id="t1", date_from=date(2026, 5, 1), date_to=date(2026, 6, 1))
    assert filters.date_from == date(2026, 5, 1)


def test_group_by_rejects_unknown_dimension():
    with pytest.raises(analytics.InvalidGroupByError):
        analytics.validate_group_by(["query_text"])


def test_group_by_accepts_every_documented_dimension():
    assert analytics.validate_group_by(list(analytics.ALLOWED_GROUP_BY)) == analytics.ALLOWED_GROUP_BY


# ── evidence status thresholds ────────────────────────────────────────────

@pytest.mark.parametrize("sample_size,expected", [
    (0, EvidenceStatus.INSUFFICIENT_EVIDENCE),
    (9, EvidenceStatus.INSUFFICIENT_EVIDENCE),
    (10, EvidenceStatus.DIRECTIONAL_SIGNAL),
    (49, EvidenceStatus.DIRECTIONAL_SIGNAL),
    (50, EvidenceStatus.ELIGIBLE_FOR_REVIEW),
    (500, EvidenceStatus.ELIGIBLE_FOR_REVIEW),
])
def test_evidence_status_thresholds(sample_size, expected):
    assert analytics.evidence_status(sample_size) == expected


# ── tenant isolation ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aggregations_are_tenant_scoped(db):
    tenant_a, tenant_b = _unique("tenant"), _unique("tenant")
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_a, query_id=_unique("q"),
               created_at=datetime.now(timezone.utc), original_chart_type="bar", active_chart_type="bar"),
        _event(event_name="visualization_selected", tenant_id=tenant_b, query_id=_unique("q"),
               created_at=datetime.now(timezone.utc), original_chart_type="donut", active_chart_type="donut"),
    ])
    events_a = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_a))
    assert len(events_a) == 1
    assert events_a[0].tenant_id == tenant_a
    summary_a = analytics.compute_recommendation_quality_summary(events_a)
    assert summary_a.rows[0].total_selections == 1


# ── date filtering ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_date_filtering_excludes_events_outside_the_range(db):
    tenant_id = _unique("tenant")
    in_range = datetime(2026, 6, 15, tzinfo=timezone.utc)
    out_of_range = datetime(2026, 7, 15, tzinfo=timezone.utc)
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=_unique("q"),
               created_at=in_range, original_chart_type="bar", active_chart_type="bar"),
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=_unique("q"),
               created_at=out_of_range, original_chart_type="bar", active_chart_type="bar"),
    ])
    filters = analytics.AnalyticsFilters(tenant_id=tenant_id, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
    events = await analytics.fetch_events(db, filters)
    assert len(events) == 1
    assert events[0].created_at.date() == date(2026, 6, 15)


@pytest.mark.asyncio
async def test_date_to_is_inclusive_of_the_whole_day(db):
    tenant_id = _unique("tenant")
    late_on_last_day = datetime(2026, 6, 30, 23, 59, tzinfo=timezone.utc)
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=_unique("q"),
               created_at=late_on_last_day, original_chart_type="bar", active_chart_type="bar"),
    ])
    filters = analytics.AnalyticsFilters(tenant_id=tenant_id, date_from=date(2026, 6, 30), date_to=date(2026, 6, 30))
    events = await analytics.fetch_events(db, filters)
    assert len(events) == 1


# ── duplicate telemetry does not inflate metrics ─────────────────────────

@pytest.mark.asyncio
async def test_duplicate_export_events_for_the_same_query_count_once(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    now = datetime.now(timezone.utc)
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id, created_at=now,
               original_chart_type="bar", active_chart_type="bar"),
        _event(event_name="visualization_exported_png", tenant_id=tenant_id, query_id=query_id, created_at=now),
        _event(event_name="visualization_exported_png", tenant_id=tenant_id, query_id=query_id, created_at=now),
        _event(event_name="visualization_exported_png", tenant_id=tenant_id, query_id=query_id, created_at=now),
    ])
    events = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    summary = analytics.compute_recommendation_quality_summary(events)
    row = summary.rows[0]
    assert row.total_selections == 1
    assert row.png_export_rate.numerator == 1
    assert row.png_export_rate.rate == 1.0


# ── retention: original vs (final) active chart type ─────────────────────

@pytest.mark.asyncio
async def test_retention_true_when_no_switch_occurred(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=datetime.now(timezone.utc), original_chart_type="area", active_chart_type="area"),
    ])
    events = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    row = analytics.compute_recommendation_quality_summary(events).rows[0]
    assert row.recommendation_retention_rate.rate == 1.0
    assert row.alternative_switch_rate.rate == 0.0


@pytest.mark.asyncio
async def test_retention_false_when_the_final_active_type_differs_from_original(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    t0 = datetime.now(timezone.utc)
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0, original_chart_type="area", active_chart_type="area"),
        _event(event_name="alternative_view_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0 + timedelta(seconds=5), original_chart_type="area", active_chart_type="line"),
    ])
    events = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    row = analytics.compute_recommendation_quality_summary(events).rows[0]
    assert row.recommendation_retention_rate.rate == 0.0
    assert row.alternative_switch_rate.rate == 1.0


@pytest.mark.asyncio
async def test_retention_true_when_user_switches_back_to_the_original(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    t0 = datetime.now(timezone.utc)
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0, original_chart_type="area", active_chart_type="area"),
        _event(event_name="alternative_view_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0 + timedelta(seconds=5), original_chart_type="area", active_chart_type="line"),
        _event(event_name="alternative_view_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0 + timedelta(seconds=10), original_chart_type="area", active_chart_type="area"),
    ])
    events = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    row = analytics.compute_recommendation_quality_summary(events).rows[0]
    # Retention looks at the FINAL state — switched away and back nets to
    # "kept the recommendation" — but the switch itself still happened, so
    # alternative_switch_rate (presence of any alternative_view_selected
    # event) still counts it.
    assert row.recommendation_retention_rate.rate == 1.0
    assert row.alternative_switch_rate.rate == 1.0


# ── replacement matrix: only successful (net) switches ────────────────────

@pytest.mark.asyncio
async def test_replacement_matrix_counts_a_successful_switch(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    t0 = datetime.now(timezone.utc)
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0, original_chart_type="donut", active_chart_type="donut"),
        _event(event_name="alternative_view_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0 + timedelta(seconds=5), original_chart_type="donut", active_chart_type="composition_bar"),
    ])
    events = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    matrix = analytics.compute_replacement_matrix(events)
    assert len(matrix.cells) == 1
    cell = matrix.cells[0]
    assert (cell.original_chart_type, cell.active_chart_type) == ("donut", "composition_bar")
    assert cell.count == 1


@pytest.mark.asyncio
async def test_replacement_matrix_excludes_a_switch_back_to_the_original(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    t0 = datetime.now(timezone.utc)
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0, original_chart_type="donut", active_chart_type="donut"),
        _event(event_name="alternative_view_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0 + timedelta(seconds=5), original_chart_type="donut", active_chart_type="composition_bar"),
        _event(event_name="alternative_view_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0 + timedelta(seconds=10), original_chart_type="donut", active_chart_type="donut"),
    ])
    events = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    matrix = analytics.compute_replacement_matrix(events)
    assert matrix.cells == []


@pytest.mark.asyncio
async def test_replacement_matrix_excludes_queries_with_no_switch_at_all(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=datetime.now(timezone.utc), original_chart_type="donut", active_chart_type="donut"),
    ])
    events = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    assert analytics.compute_replacement_matrix(events).cells == []


# ── render failures counted without exposing error content ───────────────

@pytest.mark.asyncio
async def test_render_failures_are_counted_and_carry_no_error_content(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    now = datetime.now(timezone.utc)
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id, created_at=now,
               original_chart_type="waterfall", active_chart_type="waterfall"),
        _event(event_name="visualization_render_failed", tenant_id=tenant_id, query_id=query_id, created_at=now),
    ])
    events = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    row = analytics.compute_recommendation_quality_summary(events).rows[0]
    assert row.render_failure_rate.rate == 1.0
    # Structural — VisualizationTelemetryEvent has no column that could ever
    # carry an error message or stack trace in the first place.
    forbidden = {"error", "error_message", "stack", "stack_trace", "exception"}
    assert forbidden.isdisjoint(VisualizationTelemetryEvent.__table__.columns.keys())


# ── chart-type performance "unusually high" flags ─────────────────────────

@pytest.mark.asyncio
async def test_chart_type_performance_flags_unusually_high_switch_rate_only_with_sufficient_evidence(db):
    tenant_id = _unique("tenant")
    now = datetime.now(timezone.utc)
    events = []
    # 60 selections of "bar", 40 of which switch away — 66% switch rate,
    # well past the 35% threshold, with sample_size=60 (eligible_for_review).
    for i in range(60):
        query_id = _unique("q")
        events.append(_event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
                              created_at=now, original_chart_type="bar", active_chart_type="bar"))
        if i < 40:
            events.append(_event(event_name="alternative_view_selected", tenant_id=tenant_id, query_id=query_id,
                                  created_at=now + timedelta(seconds=1), original_chart_type="bar", active_chart_type="grouped_bar"))
    await _add_all(db, events)
    fetched = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    performance = analytics.compute_chart_type_performance(fetched)
    row = next(r for r in performance.rows if r.chart_type == "bar")
    assert row.switch_rate.evidence_status == EvidenceStatus.ELIGIBLE_FOR_REVIEW
    assert row.unusually_high_switch_rate is True


@pytest.mark.asyncio
async def test_chart_type_performance_never_flags_unusually_high_on_insufficient_evidence(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    t0 = datetime.now(timezone.utc)
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0, original_chart_type="bar", active_chart_type="bar"),
        _event(event_name="alternative_view_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0 + timedelta(seconds=1), original_chart_type="bar", active_chart_type="grouped_bar"),
    ])
    fetched = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    row = analytics.compute_chart_type_performance(fetched).rows[0]
    # 1 sample, 100% switch rate — would trip the raw threshold, but a
    # single sample is insufficient_evidence, so the flag must stay False.
    assert row.switch_rate.rate == 1.0
    assert row.switch_rate.evidence_status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert row.unusually_high_switch_rate is False


# ── weight proposals ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_weight_proposal_stays_within_configured_bounds(db):
    tenant_id = _unique("tenant")
    now = datetime.now(timezone.utc)
    events = []
    for i in range(60):
        query_id = _unique("q")
        events.append(_event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
                              created_at=now, original_chart_type="bar", active_chart_type="bar",
                              analytical_intent="comparison"))
        if i < 40:
            events.append(_event(event_name="alternative_view_selected", tenant_id=tenant_id, query_id=query_id,
                                  created_at=now + timedelta(seconds=1), original_chart_type="bar",
                                  active_chart_type="grouped_bar"))
    await _add_all(db, events)
    fetched = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    proposals = analytics.propose_ranking_weight_adjustments(fetched, group_dimension="analytical_intent")
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.affected_analytical_intent == "comparison"
    assert proposal.current_chart_preference == "bar"
    assert proposal.observed_replacement == "grouped_bar"
    assert proposal.sample_size == 60
    assert proposal.review_required is True
    for dimension, delta in proposal.proposed_weight_adjustment.items():
        low, high = WEIGHT_BOUNDS[dimension]
        adjusted = current_weights()[dimension] + delta
        assert low <= adjusted <= high


@pytest.mark.asyncio
async def test_weight_proposal_omitted_below_the_review_sample_threshold(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    t0 = datetime.now(timezone.utc)
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0, original_chart_type="bar", active_chart_type="bar", analytical_intent="comparison"),
        _event(event_name="alternative_view_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=t0 + timedelta(seconds=1), original_chart_type="bar", active_chart_type="grouped_bar"),
    ])
    fetched = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    assert analytics.propose_ranking_weight_adjustments(fetched) == []


def test_weight_adjustment_proposal_schema_pins_review_required_true():
    proposal = WeightAdjustmentProposal(
        current_chart_preference="bar", observed_replacement="grouped_bar",
        sample_size=100, retention_or_switch_rate=0.4,
        proposed_weight_adjustment={"analytical_intent_fit": 0.02},
    )
    assert proposal.review_required is True
    with pytest.raises(ValidationError):
        WeightAdjustmentProposal(
            current_chart_preference="bar", observed_replacement="grouped_bar",
            sample_size=100, retention_or_switch_rate=0.4,
            proposed_weight_adjustment={"analytical_intent_fit": 0.02},
            review_required=False,
        )


def test_weight_proposal_rejects_unknown_dimension():
    with pytest.raises(ValidationError):
        WeightAdjustmentProposal(
            current_chart_preference="bar", observed_replacement="grouped_bar",
            sample_size=100, retention_or_switch_rate=0.4,
            proposed_weight_adjustment={"not_a_real_dimension": 0.02},
        )


# ── ranking-configuration weight bounds validation ────────────────────────

def test_ranking_configuration_create_accepts_the_current_production_weights():
    payload = RankingConfigurationCreate(
        ranking_version=_unique("v"), effective_from=datetime.now(timezone.utc), weights=current_weights(),
    )
    assert set(payload.weights) == set(WEIGHT_DIMENSIONS)


def test_ranking_configuration_create_rejects_an_out_of_bounds_weight():
    weights = current_weights()
    weights["analytical_intent_fit"] = 5.0  # bound is [0, 1]
    with pytest.raises(ValidationError):
        RankingConfigurationCreate(ranking_version=_unique("v"), effective_from=datetime.now(timezone.utc), weights=weights)


def test_ranking_configuration_create_rejects_a_sign_flip_on_a_penalty_dimension():
    weights = current_weights()
    weights["complexity_penalty"] = 0.5  # bound is [-1, 0] — must stay a penalty, never a bonus
    with pytest.raises(ValidationError):
        RankingConfigurationCreate(ranking_version=_unique("v"), effective_from=datetime.now(timezone.utc), weights=weights)


def test_ranking_configuration_create_rejects_missing_dimensions():
    weights = current_weights()
    del weights["readability"]
    with pytest.raises(ValidationError):
        RankingConfigurationCreate(ranking_version=_unique("v"), effective_from=datetime.now(timezone.utc), weights=weights)


def test_ranking_configuration_create_rejects_unknown_dimensions():
    weights = current_weights()
    weights["made_up_dimension"] = 0.1
    with pytest.raises(ValidationError):
        RankingConfigurationCreate(ranking_version=_unique("v"), effective_from=datetime.now(timezone.utc), weights=weights)


# ── ranking-configuration draft / approve lifecycle ───────────────────────

@pytest.mark.asyncio
async def test_draft_configuration_is_created_with_draft_status(db):
    version = _unique("v")
    row = await ranking_configuration_service.create_draft(
        db, ranking_version=version, effective_from=datetime.now(timezone.utc),
        weights=current_weights(), created_by=_unique("user"),
    )
    assert row.status == "draft"
    assert row.approved_by is None


@pytest.mark.asyncio
async def test_duplicate_ranking_version_is_rejected(db):
    version = _unique("v")
    await ranking_configuration_service.create_draft(
        db, ranking_version=version, effective_from=datetime.now(timezone.utc),
        weights=current_weights(), created_by=_unique("user"),
    )
    with pytest.raises(ranking_configuration_service.DuplicateRankingVersionError):
        await ranking_configuration_service.create_draft(
            db, ranking_version=version, effective_from=datetime.now(timezone.utc),
            weights=current_weights(), created_by=_unique("user"),
        )


@pytest.mark.asyncio
async def test_approving_a_draft_does_not_change_production_weights_or_ranking_version(db):
    from app.orchestration import presentation_dataprofile

    weights_before = current_weights()
    version_before = presentation_dataprofile.RANKING_VERSION
    drafted_weights = current_weights()
    drafted_weights["analytical_intent_fit"] = 0.5
    row = await ranking_configuration_service.create_draft(
        db, ranking_version=_unique("v"), effective_from=datetime.now(timezone.utc),
        weights=drafted_weights, created_by=_unique("user"),
    )
    approved = await ranking_configuration_service.approve_configuration(
        db, configuration_id=row.id, approver_id=_unique("user"),
    )
    assert approved.status == "approved"
    # Nothing about approval touches the live module-level constants.
    assert current_weights() == weights_before
    assert presentation_dataprofile.RANKING_VERSION == version_before


@pytest.mark.asyncio
async def test_self_approval_is_rejected(db):
    drafter = _unique("user")
    row = await ranking_configuration_service.create_draft(
        db, ranking_version=_unique("v"), effective_from=datetime.now(timezone.utc),
        weights=current_weights(), created_by=drafter,
    )
    with pytest.raises(ranking_configuration_service.SelfApprovalError):
        await ranking_configuration_service.approve_configuration(db, configuration_id=row.id, approver_id=drafter)


@pytest.mark.asyncio
async def test_approving_an_already_approved_configuration_is_rejected(db):
    row = await ranking_configuration_service.create_draft(
        db, ranking_version=_unique("v"), effective_from=datetime.now(timezone.utc),
        weights=current_weights(), created_by=_unique("user"),
    )
    await ranking_configuration_service.approve_configuration(db, configuration_id=row.id, approver_id=_unique("user"))
    with pytest.raises(ranking_configuration_service.AlreadyReviewedError):
        await ranking_configuration_service.approve_configuration(db, configuration_id=row.id, approver_id=_unique("user"))


@pytest.mark.asyncio
async def test_approving_a_nonexistent_configuration_is_rejected(db):
    with pytest.raises(ranking_configuration_service.RankingConfigurationNotFoundError):
        await ranking_configuration_service.approve_configuration(db, configuration_id=_unique("missing"), approver_id=_unique("user"))


@pytest.mark.asyncio
async def test_approval_is_recorded_on_the_compliance_audit_ledger_not_product_telemetry(db):
    row = await ranking_configuration_service.create_draft(
        db, ranking_version=_unique("v"), effective_from=datetime.now(timezone.utc),
        weights=current_weights(), created_by=_unique("user"),
    )
    approver = _unique("user")
    await ranking_configuration_service.approve_configuration(db, configuration_id=row.id, approver_id=approver)
    result = await db.execute(
        select(AuditEvent).where(
            AuditEvent.subject_type == "ranking_configuration", AuditEvent.subject_id == row.ranking_version,
        )
    )
    audit_row = result.scalar_one()
    assert audit_row.event_name == "ranking_configuration_approved"
    assert audit_row.actor_id == approver
    # And NOT written to the product-telemetry table.
    telemetry_result = await db.execute(
        select(VisualizationTelemetryEvent).where(VisualizationTelemetryEvent.query_id == row.ranking_version)
    )
    assert telemetry_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_list_configurations_filters_by_status(db):
    created_by = _unique("user")
    draft_version = _unique("v")
    approved_version = _unique("v")
    draft_row = await ranking_configuration_service.create_draft(
        db, ranking_version=draft_version, effective_from=datetime.now(timezone.utc),
        weights=current_weights(), created_by=created_by,
    )
    approved_row = await ranking_configuration_service.create_draft(
        db, ranking_version=approved_version, effective_from=datetime.now(timezone.utc),
        weights=current_weights(), created_by=created_by,
    )
    await ranking_configuration_service.approve_configuration(db, configuration_id=approved_row.id, approver_id=_unique("user"))

    drafts = await ranking_configuration_service.list_configurations(db, status="draft")
    approved = await ranking_configuration_service.list_configurations(db, status="approved")
    assert draft_row.id in {r.id for r in drafts}
    assert approved_row.id in {r.id for r in approved}
    assert draft_row.id not in {r.id for r in approved}


# ── determinism ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ranking_version_comparison_is_deterministic(db):
    tenant_id = _unique("tenant")
    query_id = _unique("q")
    await _add_all(db, [
        _event(event_name="visualization_selected", tenant_id=tenant_id, query_id=query_id,
               created_at=datetime.now(timezone.utc), original_chart_type="bar", active_chart_type="bar",
               ranking_version="1.0.0"),
    ])
    events = await analytics.fetch_events(db, analytics.AnalyticsFilters(tenant_id=tenant_id))
    first = analytics.compute_recommendation_quality_summary(events, ("ranking_version",))
    second = analytics.compute_recommendation_quality_summary(events, ("ranking_version",))
    assert first.model_dump() == second.model_dump()


# ── weight changes never affect compatibility or explicit requests ───────

def test_invalid_candidates_can_never_become_selectable_via_weight_changes(monkeypatch):
    # Even an extreme, out-of-governance weight cannot make an
    # incompatible chart type appear in the candidate list — compatibility
    # (_is_compatible) is checked before any score is ever computed.
    import app.orchestration.presentation_dataprofile as pdp

    monkeypatch.setitem(pdp._WEIGHTS, "analytical_intent_fit", 999.0)
    monkeypatch.setitem(pdp._WEIGHTS, "complexity_penalty", 999.0)
    # radar requires measure_count in [3, 6] and category_count <= 5 — this
    # profile fails both, so radar must never be a candidate for COMPARISON
    # regardless of how the weights are set.
    profile = DataProfile(dimensions=("D",), measures=("A", "B"), category_count=3, measure_count=2)
    candidates = generate_candidates(AnalyticalIntent.COMPARISON, profile)
    assert "radar" not in candidates


def test_explicit_compatible_requests_are_unaffected_by_weight_changes(monkeypatch):
    import app.orchestration.presentation_dataprofile as pdp

    profile = DataProfile(dimensions=("D",), measures=("A", "B"), category_count=5, measure_count=2)
    query = "show a dumbbell chart"
    baseline = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, query)
    monkeypatch.setitem(pdp._WEIGHTS, "readability", 0.0)
    monkeypatch.setitem(pdp._WEIGHTS, "complexity_penalty", -0.01)
    with_weights_changed = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, query)
    assert baseline.chart_type == with_weights_changed.chart_type == "dumbbell"


# ── admin-only authorization ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_require_admin_rejects_a_non_admin_user():
    non_admin = User(
        id=_unique("user"), tenant_id=_unique("tenant"), email=f"{_unique('u')}@example.com",
        full_name="Non Admin", role="Viewer",
    )
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(non_admin)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_accepts_an_admin_user():
    admin = User(
        id=_unique("user"), tenant_id=_unique("tenant"), email=f"{_unique('u')}@example.com",
        full_name="Admin", role="Admin",
    )
    result = await require_admin(admin)
    assert result is admin
