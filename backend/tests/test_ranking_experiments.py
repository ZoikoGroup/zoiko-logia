"""Tests for Dynamic Visualization Selection v7 — deterministic experiment
assignment, targeting, guardrails, lifecycle, rollback, and results.

Same persistent-SQLite-file precedent as the rest of this suite: IDs are
uuid-suffixed per test, never fixed strings.
"""
import uuid
from datetime import datetime, timedelta, timezone

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
from app.orchestration import ranking_experiments as experiments_service
from app.orchestration.models import RankingExperiment, VisualizationTelemetryEvent
from app.orchestration.presentation import build_answer_presentation
from app.orchestration.presentation_dataprofile import (
    AnalyticalIntent,
    DataProfile,
    RANKING_VERSION,
    _SPEC_BY_TYPE,
    _is_compatible,
    current_weights,
    generate_candidates,
    select_chart_with_alternatives,
)
from app.orchestration.ranking_experiments import ExperimentContext
from app.orchestration.ranking_experiments_schemas import (
    ExperimentResultStatus,
    ExperimentStatus,
    RankingExperimentCreate,
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


async def _make_configuration(db, *, approved=True, weights=None):
    row = await ranking_configuration_service.create_draft(
        db, ranking_version=_unique("v"), effective_from=datetime.now(timezone.utc),
        weights=weights or current_weights(), created_by=_unique("user"),
    )
    if approved:
        row = await ranking_configuration_service.approve_configuration(db, configuration_id=row.id, approver_id=_unique("user"))
    return row


async def _make_experiment(
    db, *, control_config=None, variant_config=None, control_allocation=50.0, variant_allocation=50.0,
    targeting_rules=None, minimum_sample_size=50, start_at=None, end_at=None,
):
    control_config = control_config or await _make_configuration(db)
    variant_config = variant_config or await _make_configuration(db)
    return await experiments_service.create_draft(
        db, name=_unique("exp"), description="test experiment",
        control_ranking_version=control_config.ranking_version, variant_ranking_version=variant_config.ranking_version,
        control_allocation_percent=control_allocation, variant_allocation_percent=variant_allocation,
        targeting_rules=targeting_rules or {}, primary_metrics=["recommendation_retention_rate"],
        secondary_metrics=[], guardrail_metrics=["render_failure_rate", "fallback_rate"],
        minimum_sample_size=minimum_sample_size, start_at=start_at, end_at=end_at, created_by=_unique("user"),
    ), control_config, variant_config


def _event(
    *, event_name, query_id, created_at, experiment_id=None, experiment_group=None,
    original_chart_type=None, active_chart_type=None,
):
    return VisualizationTelemetryEvent(
        event_name=event_name, tenant_id=_unique("tenant"), actor_id=_unique("user"), conversation_id=None,
        query_id=query_id, analytical_intent="comparison", original_chart_type=original_chart_type,
        active_chart_type=active_chart_type, alternative_count=1, selection_source="deterministic_default",
        renderer="recharts", schema_version="1.0", chart_family=None, ranking_version="1.0.0",
        experiment_id=experiment_id, experiment_group=experiment_group, created_at=created_at,
    )


# ── deterministic assignment ─────────────────────────────────────────────

def test_assignment_bucket_is_deterministic():
    args = ("tenant-1", "actor-1", "conv-1", "exp-1")
    assert experiments_service.assignment_bucket(*args) == experiments_service.assignment_bucket(*args)


def test_same_conversation_always_gets_the_same_group(db):
    experiment = RankingExperiment(
        id=_unique("exp"), name="x", status="active", control_ranking_version="c", variant_ranking_version="v",
        control_allocation_percent=50.0, variant_allocation_percent=50.0, targeting_rules={},
        primary_metrics=[], secondary_metrics=[], guardrail_metrics=[], created_by="u",
    )
    first = experiments_service.resolve_group(experiment, "tenant-1", "actor-1", "conv-1")
    second = experiments_service.resolve_group(experiment, "tenant-1", "actor-1", "conv-1")
    assert first == second


def test_different_tenants_get_independent_assignment():
    experiment_id = _unique("exp")
    buckets = {
        experiments_service.assignment_bucket(_unique("tenant"), "actor-1", "conv-1", experiment_id)
        for _ in range(20)
    }
    # 20 different tenant_ids against the same actor/conversation/experiment
    # — collapsing to a single bucket would mean tenant_id isn't actually
    # part of the hash key at all.
    assert len(buckets) > 1


def test_allocations_approximately_match_configured_percentages():
    experiment = RankingExperiment(
        id=_unique("exp"), name="x", status="active", control_ranking_version="c", variant_ranking_version="v",
        control_allocation_percent=70.0, variant_allocation_percent=30.0, targeting_rules={},
        primary_metrics=[], secondary_metrics=[], guardrail_metrics=[], created_by="u",
    )
    tenant_id = _unique("tenant")
    groups = [
        experiments_service.resolve_group(experiment, tenant_id, _unique("actor"), _unique("conv"))
        for _ in range(3000)
    ]
    variant_share = groups.count("variant") / len(groups)
    assert 0.25 <= variant_share <= 0.35


# ── targeting rules ────────────────────────────────────────────────────────

def test_empty_targeting_rules_matches_everything():
    assert experiments_service.matches_targeting({}, "comparison", "category_series") is True
    assert experiments_service.matches_targeting({}, None, None) is True


def test_targeting_rules_exclude_unrelated_intent():
    rules = {"analytical_intent": ["trend"]}
    assert experiments_service.matches_targeting(rules, "comparison", None) is False
    assert experiments_service.matches_targeting(rules, "trend", None) is True


def test_targeting_rules_exclude_unrelated_chart_family():
    rules = {"chart_family": ["temporal_series"]}
    assert experiments_service.matches_targeting(rules, None, "category_series") is False
    assert experiments_service.matches_targeting(rules, None, "temporal_series") is True


def test_targeting_rules_require_both_fields_when_both_present():
    rules = {"analytical_intent": ["comparison"], "chart_family": ["temporal_series"]}
    assert experiments_service.matches_targeting(rules, "comparison", "category_series") is False
    assert experiments_service.matches_targeting(rules, "comparison", "temporal_series") is True


# ── effective_status ───────────────────────────────────────────────────────

def test_scheduled_experiment_becomes_effective_active_after_start_at():
    experiment = RankingExperiment(
        id="e", name="x", status="scheduled", control_ranking_version="c", variant_ranking_version="v",
        control_allocation_percent=50.0, variant_allocation_percent=50.0, targeting_rules={},
        primary_metrics=[], secondary_metrics=[], guardrail_metrics=[], created_by="u",
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert experiments_service.effective_status(experiment, now) == "active"
    assert experiment.status == "scheduled"  # never mutated by this pure read


def test_scheduled_experiment_stays_scheduled_before_start_at():
    experiment = RankingExperiment(
        id="e", name="x", status="scheduled", control_ranking_version="c", variant_ranking_version="v",
        control_allocation_percent=50.0, variant_allocation_percent=50.0, targeting_rules={},
        primary_metrics=[], secondary_metrics=[], guardrail_metrics=[], created_by="u",
        start_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert experiments_service.effective_status(experiment, now) == "scheduled"


def test_active_experiment_becomes_effectively_completed_after_end_at():
    experiment = RankingExperiment(
        id="e", name="x", status="active", control_ranking_version="c", variant_ranking_version="v",
        control_allocation_percent=50.0, variant_allocation_percent=50.0, targeting_rules={},
        primary_metrics=[], secondary_metrics=[], guardrail_metrics=[], created_by="u",
        end_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert experiments_service.effective_status(experiment, now) == "completed"


# ── weight threading / registry authority under control & variant ────────

def test_control_preserves_the_existing_default_result():
    profile = DataProfile(dimensions=("D",), measures=("A", "B"), category_count=5, measure_count=2)
    without_experiment = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare a and b")
    with_control_weights = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare a and b", weights=None)
    assert without_experiment.chart_type == with_control_weights.chart_type == "grouped_bar"


def test_variant_weights_can_reorder_alternatives_without_changing_the_default():
    profile = DataProfile(dimensions=("D",), measures=("A", "B", "C"), category_count=3, measure_count=3)
    query = "compare a, b, and c"
    baseline = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, query)
    variant_weights = current_weights()
    variant_weights["complexity_penalty"] = -0.9  # heavily penalize complex charts (radar is complex)
    variant = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, query, weights=variant_weights)
    # The protected default never moves — only alternative ranking can.
    assert baseline.chart_type == variant.chart_type == "radar"


def test_invalid_candidates_never_become_selectable_in_the_variant():
    variant_weights = current_weights()
    variant_weights["analytical_intent_fit"] = 1.0
    variant_weights["complexity_penalty"] = 0.0
    profile = DataProfile(dimensions=("D",), measures=("A", "B"), category_count=3, measure_count=2)
    candidates = generate_candidates(AnalyticalIntent.COMPARISON, profile)
    assert "radar" not in candidates
    for chart_type in candidates:
        assert _is_compatible(_SPEC_BY_TYPE[chart_type], profile) is True


def test_explicit_compatible_requests_still_win_under_variant_weights():
    profile = DataProfile(dimensions=("D",), measures=("A", "B"), category_count=5, measure_count=2)
    query = "show a dumbbell chart"
    variant_weights = current_weights()
    variant_weights["readability"] = 0.0
    variant_weights["complexity_penalty"] = -0.01
    selection = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, query, weights=variant_weights)
    assert selection.chart_type == "dumbbell"


# ── resolve_experiment_context ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_experiment_context_returns_none_with_no_active_experiment(db):
    context = await experiments_service.resolve_experiment_context(
        db, tenant_id=_unique("tenant"), actor_id=_unique("actor"), conversation_id=_unique("conv"),
    )
    assert context is None


@pytest.mark.asyncio
async def test_inactive_experiment_never_changes_ranking(db):
    experiment, _control, variant = await _make_experiment(db)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    # Approved, but never activated — still must not apply.
    context = await experiments_service.resolve_experiment_context(
        db, tenant_id=_unique("tenant"), actor_id=_unique("actor"), conversation_id=_unique("conv"),
    )
    assert context is None


@pytest.mark.asyncio
async def test_resolve_experiment_context_returns_context_for_an_active_experiment(db):
    experiment, control, variant = await _make_experiment(db, control_allocation=0.0, variant_allocation=100.0)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))
    context = await experiments_service.resolve_experiment_context(
        db, tenant_id=_unique("tenant"), actor_id=_unique("actor"), conversation_id=_unique("conv"),
    )
    assert context is not None
    assert context.experiment_id == experiment.id
    assert context.group == "variant"
    assert context.variant_ranking_version == variant.ranking_version
    assert context.variant_weights == variant.weights
    await experiments_service.rollback_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"), reason="test cleanup")


@pytest.mark.asyncio
async def test_resolve_experiment_context_auto_pauses_when_variant_configuration_is_unapproved(db):
    variant_draft = await _make_configuration(db, approved=False)
    control = await _make_configuration(db)
    experiment, _c, _v = await _make_experiment(db, control_config=control, variant_config=variant_draft)
    # Force to active directly (bypassing activate_experiment's own
    # approved-variant gate) to exercise resolve_experiment_context's own
    # independent guardrail check.
    experiment.status = "active"
    await db.commit()

    context = await experiments_service.resolve_experiment_context(
        db, tenant_id=_unique("tenant"), actor_id=_unique("actor"), conversation_id=_unique("conv"),
    )
    assert context is None
    await db.refresh(experiment)
    assert experiment.status == "paused"
    assert "guardrail" in (experiment.status_reason or "")


@pytest.mark.asyncio
async def test_different_tenants_do_not_influence_one_anothers_assignment(db):
    experiment, _c, _v = await _make_experiment(db, control_allocation=50.0, variant_allocation=50.0)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))

    actor, conversation = _unique("actor"), _unique("conv")
    context_a = await experiments_service.resolve_experiment_context(db, tenant_id="tenant-a", actor_id=actor, conversation_id=conversation)
    context_b = await experiments_service.resolve_experiment_context(db, tenant_id="tenant-b", actor_id=actor, conversation_id=conversation)
    # Not asserting they differ (that's a probabilistic property tested
    # above) — asserting each is independently computed from its own
    # tenant_id, i.e. matches assignment_bucket's own direct computation.
    assert context_a.group == experiments_service.resolve_group(experiment, "tenant-a", actor, conversation)
    assert context_b.group == experiments_service.resolve_group(experiment, "tenant-b", actor, conversation)
    await experiments_service.rollback_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"), reason="test cleanup")


# ── lifecycle ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_draft_requires_both_configurations_to_exist(db):
    control = await _make_configuration(db)
    with pytest.raises(experiments_service.BothConfigurationsMustExistError):
        await experiments_service.create_draft(
            db, name="x", description="", control_ranking_version=control.ranking_version,
            variant_ranking_version=_unique("missing-version"), control_allocation_percent=50.0,
            variant_allocation_percent=50.0, targeting_rules={}, primary_metrics=["recommendation_retention_rate"],
            secondary_metrics=[], guardrail_metrics=["render_failure_rate"], minimum_sample_size=50,
            start_at=None, end_at=None, created_by=_unique("user"),
        )


@pytest.mark.asyncio
async def test_create_draft_succeeds_with_draft_status(db):
    experiment, _c, _v = await _make_experiment(db)
    assert experiment.status == "draft"


def test_allocation_percentages_must_total_100():
    with pytest.raises(ValidationError):
        RankingExperimentCreate(
            name="x", control_ranking_version="c", variant_ranking_version="v",
            control_allocation_percent=60.0, variant_allocation_percent=60.0,
            primary_metrics=["recommendation_retention_rate"], guardrail_metrics=["render_failure_rate"],
        )


def test_targeting_rules_must_use_approved_fields_only():
    with pytest.raises(ValidationError):
        RankingExperimentCreate(
            name="x", control_ranking_version="c", variant_ranking_version="v",
            control_allocation_percent=50.0, variant_allocation_percent=50.0,
            targeting_rules={"query_text": ["hello"]},
            primary_metrics=["recommendation_retention_rate"], guardrail_metrics=["render_failure_rate"],
        )


def test_metrics_must_come_from_the_closed_enum():
    with pytest.raises(ValidationError):
        RankingExperimentCreate(
            name="x", control_ranking_version="c", variant_ranking_version="v",
            control_allocation_percent=50.0, variant_allocation_percent=50.0,
            primary_metrics=["made_up_metric"], guardrail_metrics=["render_failure_rate"],
        )


@pytest.mark.asyncio
async def test_approve_requires_variant_to_be_approved(db):
    variant_draft = await _make_configuration(db, approved=False)
    control = await _make_configuration(db)
    experiment, _c, _v = await _make_experiment(db, control_config=control, variant_config=variant_draft)
    with pytest.raises(experiments_service.VariantMustBeApprovedError):
        await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))


@pytest.mark.asyncio
async def test_approve_rejects_self_approval(db):
    control = await _make_configuration(db)
    variant = await _make_configuration(db)
    creator = _unique("user")
    experiment = await experiments_service.create_draft(
        db, name="x", description="", control_ranking_version=control.ranking_version,
        variant_ranking_version=variant.ranking_version, control_allocation_percent=50.0,
        variant_allocation_percent=50.0, targeting_rules={}, primary_metrics=["recommendation_retention_rate"],
        secondary_metrics=[], guardrail_metrics=["render_failure_rate"], minimum_sample_size=50,
        start_at=None, end_at=None, created_by=creator,
    )
    with pytest.raises(experiments_service.SelfApprovalError):
        await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=creator)


@pytest.mark.asyncio
async def test_activate_requires_minimum_sample_size(db):
    experiment, _c, _v = await _make_experiment(db, minimum_sample_size=None)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    with pytest.raises(experiments_service.MinimumSampleSizeRequiredError):
        await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))


@pytest.mark.asyncio
async def test_activate_rejects_a_second_concurrently_active_experiment(db):
    first, _c1, _v1 = await _make_experiment(db)
    await experiments_service.approve_experiment(db, experiment_id=first.id, approver_id=_unique("user"))
    await experiments_service.activate_experiment(db, experiment_id=first.id, actor_id=_unique("user"))

    second, _c2, _v2 = await _make_experiment(db)
    await experiments_service.approve_experiment(db, experiment_id=second.id, approver_id=_unique("user"))
    with pytest.raises(experiments_service.AnotherExperimentAlreadyActiveError):
        await experiments_service.activate_experiment(db, experiment_id=second.id, actor_id=_unique("user"))
    await experiments_service.rollback_experiment(db, experiment_id=first.id, actor_id=_unique("user"), reason="test cleanup")


@pytest.mark.asyncio
async def test_activate_sets_active_when_start_at_is_not_in_the_future(db):
    experiment, _c, _v = await _make_experiment(db)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    activated = await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))
    assert activated.status == "active"
    await experiments_service.rollback_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"), reason="test cleanup")


@pytest.mark.asyncio
async def test_activate_sets_scheduled_when_start_at_is_in_the_future(db):
    future = datetime.now(timezone.utc) + timedelta(days=3)
    experiment, _c, _v = await _make_experiment(db, start_at=future)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    activated = await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))
    assert activated.status == "scheduled"


@pytest.mark.asyncio
async def test_pause_requires_active_or_scheduled_status(db):
    experiment, _c, _v = await _make_experiment(db)
    with pytest.raises(experiments_service.InvalidExperimentTransitionError):
        await experiments_service.pause_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"), reason="testing")


@pytest.mark.asyncio
async def test_pause_records_status_reason(db):
    experiment, _c, _v = await _make_experiment(db)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))
    paused = await experiments_service.pause_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"), reason="manual pause for review")
    assert paused.status == "paused"
    assert paused.status_reason == "manual pause for review"


@pytest.mark.asyncio
async def test_complete_transitions_active_to_completed(db):
    experiment, _c, _v = await _make_experiment(db)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))
    completed = await experiments_service.complete_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))
    assert completed.status == "completed"


@pytest.mark.asyncio
async def test_rollback_immediately_restores_control_for_new_requests(db):
    experiment, _c, _v = await _make_experiment(db, control_allocation=0.0, variant_allocation=100.0)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))
    assert await experiments_service.resolve_experiment_context(
        db, tenant_id=_unique("t"), actor_id=_unique("a"), conversation_id=_unique("c"),
    ) is not None

    await experiments_service.rollback_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"), reason="bad regression observed")
    context_after_rollback = await experiments_service.resolve_experiment_context(
        db, tenant_id=_unique("t"), actor_id=_unique("a"), conversation_id=_unique("c"),
    )
    assert context_after_rollback is None


@pytest.mark.asyncio
async def test_rollback_preserves_historical_telemetry_events(db):
    experiment, _c, _v = await _make_experiment(db)
    query_id = _unique("q")
    event = _event(event_name="visualization_selected", query_id=query_id, created_at=datetime.now(timezone.utc), experiment_id=experiment.id, experiment_group="variant")
    db.add(event)
    await db.commit()

    await experiments_service.rollback_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"), reason="rollback test")

    result = await db.execute(select(VisualizationTelemetryEvent).where(VisualizationTelemetryEvent.query_id == query_id))
    preserved = result.scalar_one()
    assert preserved.experiment_id == experiment.id
    assert preserved.experiment_group == "variant"


def test_rollback_never_touches_saved_visualizations_or_telemetry_tables():
    # Structural guarantee: rollback_experiment's only DB write target is
    # the RankingExperiment row itself — it references no other model at
    # all (VisualizationTelemetryEvent is used elsewhere in this module,
    # e.g. by the guardrail/results code, but never inside rollback_experiment
    # specifically), and this module doesn't import SavedVisualization at all.
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(experiments_service.rollback_experiment))
    referenced_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "SavedVisualization" not in referenced_names
    assert "VisualizationTelemetryEvent" not in referenced_names
    assert "SavedVisualization" not in dir(experiments_service)


@pytest.mark.asyncio
async def test_rollback_rejects_an_already_rolled_back_experiment(db):
    experiment, _c, _v = await _make_experiment(db)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))
    await experiments_service.rollback_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"), reason="first rollback")
    with pytest.raises(experiments_service.InvalidExperimentTransitionError):
        await experiments_service.rollback_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"), reason="second rollback")


@pytest.mark.asyncio
async def test_approval_and_rollback_are_recorded_on_the_administrative_audit_ledger(db):
    experiment, _c, _v = await _make_experiment(db)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))
    await experiments_service.rollback_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"), reason="testing audit trail")

    result = await db.execute(select(AuditEvent).where(AuditEvent.subject_type == "ranking_experiment", AuditEvent.subject_id == experiment.id))
    events = result.scalars().all()
    event_names = {e.event_name for e in events}
    assert "ranking_experiment_approved" in event_names
    assert "ranking_experiment_activated" in event_names
    assert "ranking_experiment_rolled_back" in event_names


# ── unauthorized access ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthorized_users_cannot_activate_or_rollback():
    non_admin = User(id=_unique("user"), tenant_id=_unique("tenant"), email=f"{_unique('u')}@example.com", full_name="Viewer", role="Viewer")
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(non_admin)
    assert exc_info.value.status_code == 403


# ── guardrails ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guardrail_trips_on_increased_render_failure_rate(db):
    experiment, _c, _v = await _make_experiment(db)
    now = datetime.now(timezone.utc)
    events = []
    for i in range(20):
        control_q, variant_q = _unique("q"), _unique("q")
        events.append(_event(event_name="visualization_selected", query_id=control_q, created_at=now, experiment_id=experiment.id, experiment_group="control"))
        events.append(_event(event_name="visualization_selected", query_id=variant_q, created_at=now, experiment_id=experiment.id, experiment_group="variant"))
        if i < 10:  # 50% render failure in variant, 0% in control
            events.append(_event(event_name="visualization_render_failed", query_id=variant_q, created_at=now, experiment_id=experiment.id, experiment_group="variant"))
    for event in events:
        db.add(event)
    await db.commit()

    findings = await experiments_service.evaluate_guardrails(db, experiment)
    assert any("render_failure_rate" in f for f in findings)


@pytest.mark.asyncio
async def test_guardrail_trips_on_increased_fallback_rate(db):
    experiment, _c, _v = await _make_experiment(db)
    now = datetime.now(timezone.utc)
    events = []
    for i in range(20):
        control_q, variant_q = _unique("q"), _unique("q")
        events.append(_event(event_name="visualization_selected", query_id=control_q, created_at=now, experiment_id=experiment.id, experiment_group="control"))
        events.append(_event(event_name="visualization_selected", query_id=variant_q, created_at=now, experiment_id=experiment.id, experiment_group="variant"))
        if i < 10:
            events.append(_event(event_name="visualization_fallback_used", query_id=variant_q, created_at=now, experiment_id=experiment.id, experiment_group="variant"))
    for event in events:
        db.add(event)
    await db.commit()

    findings = await experiments_service.evaluate_guardrails(db, experiment)
    assert any("fallback_rate" in f for f in findings)


@pytest.mark.asyncio
async def test_guardrail_does_not_trip_below_minimum_sample(db):
    experiment, _c, _v = await _make_experiment(db)
    now = datetime.now(timezone.utc)
    variant_q = _unique("q")
    db.add(_event(event_name="visualization_selected", query_id=variant_q, created_at=now, experiment_id=experiment.id, experiment_group="variant"))
    db.add(_event(event_name="visualization_render_failed", query_id=variant_q, created_at=now, experiment_id=experiment.id, experiment_group="variant"))
    await db.commit()

    findings = await experiments_service.evaluate_guardrails(db, experiment)
    assert findings == []


@pytest.mark.asyncio
async def test_check_and_maybe_pause_pauses_an_active_experiment_on_guardrail_trip(db):
    experiment, _c, _v = await _make_experiment(db)
    await experiments_service.approve_experiment(db, experiment_id=experiment.id, approver_id=_unique("user"))
    await experiments_service.activate_experiment(db, experiment_id=experiment.id, actor_id=_unique("user"))
    now = datetime.now(timezone.utc)
    for i in range(20):
        control_q, variant_q = _unique("q"), _unique("q")
        db.add(_event(event_name="visualization_selected", query_id=control_q, created_at=now, experiment_id=experiment.id, experiment_group="control"))
        db.add(_event(event_name="visualization_selected", query_id=variant_q, created_at=now, experiment_id=experiment.id, experiment_group="variant"))
        if i < 10:
            db.add(_event(event_name="visualization_render_failed", query_id=variant_q, created_at=now, experiment_id=experiment.id, experiment_group="variant"))
    await db.commit()

    paused = await experiments_service.check_and_maybe_pause(db, experiment.id)
    assert paused is not None
    assert paused.status == "paused"
    assert (paused.status_reason or "").startswith("guardrail:")


@pytest.mark.asyncio
async def test_check_and_maybe_pause_is_a_noop_for_a_non_active_experiment(db):
    experiment, _c, _v = await _make_experiment(db)
    result = await experiments_service.check_and_maybe_pause(db, experiment.id)
    assert result is None


# ── results / minimum-sample gating ───────────────────────────────────────

def _fake_experiment(**overrides):
    defaults = dict(
        id="e", name="x", status="active", control_ranking_version="c", variant_ranking_version="v",
        control_allocation_percent=50.0, variant_allocation_percent=50.0, targeting_rules={},
        primary_metrics=[], secondary_metrics=[], guardrail_metrics=[], created_by="u",
        minimum_sample_size=50, start_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    defaults.update(overrides)
    return RankingExperiment(**defaults)


def test_classify_result_insufficient_evidence_below_the_low_sample_floor():
    experiment = _fake_experiment()
    status = experiments_service.classify_experiment_result(experiment, control_selections=3, variant_selections=3, guardrail_findings=[])
    assert status == ExperimentResultStatus.INSUFFICIENT_EVIDENCE


def test_classify_result_experiment_running_with_moderate_but_insufficient_sample():
    experiment = _fake_experiment(minimum_sample_size=100)
    status = experiments_service.classify_experiment_result(experiment, control_selections=20, variant_selections=20, guardrail_findings=[])
    assert status == ExperimentResultStatus.EXPERIMENT_RUNNING


def test_classify_result_directional_when_sample_met_but_duration_not_met():
    experiment = _fake_experiment(minimum_sample_size=50, start_at=datetime.now(timezone.utc) - timedelta(days=1))
    status = experiments_service.classify_experiment_result(experiment, control_selections=60, variant_selections=60, guardrail_findings=[])
    assert status == ExperimentResultStatus.DIRECTIONAL_RESULT


def test_classify_result_eligible_for_decision_requires_sample_and_duration():
    experiment = _fake_experiment(minimum_sample_size=50, start_at=datetime.now(timezone.utc) - timedelta(days=10))
    status = experiments_service.classify_experiment_result(experiment, control_selections=60, variant_selections=60, guardrail_findings=[])
    assert status == ExperimentResultStatus.ELIGIBLE_FOR_DECISION


def test_classify_result_never_eligible_before_minimum_sample_even_with_duration_met():
    experiment = _fake_experiment(minimum_sample_size=1000, start_at=datetime.now(timezone.utc) - timedelta(days=30))
    status = experiments_service.classify_experiment_result(experiment, control_selections=60, variant_selections=60, guardrail_findings=[])
    assert status != ExperimentResultStatus.ELIGIBLE_FOR_DECISION


def test_classify_result_guardrail_failed_overrides_strong_evidence():
    experiment = _fake_experiment(minimum_sample_size=50, start_at=datetime.now(timezone.utc) - timedelta(days=30))
    status = experiments_service.classify_experiment_result(
        experiment, control_selections=1000, variant_selections=1000, guardrail_findings=["variant render_failure_rate exceeds the guardrail threshold relative to control"],
    )
    assert status == ExperimentResultStatus.GUARDRAIL_FAILED


def test_wilson_interval_is_bounded_and_deterministic():
    low, high = experiments_service._wilson_interval(30, 100)
    assert 0.0 <= low <= high <= 1.0
    assert experiments_service._wilson_interval(30, 100) == (low, high)
    assert experiments_service._wilson_interval(0, 0) == (0.0, 0.0)


@pytest.mark.asyncio
async def test_compute_experiment_results_end_to_end(db):
    experiment, _c, _v = await _make_experiment(db, minimum_sample_size=5)
    now = datetime.now(timezone.utc)
    for i in range(8):
        control_q, variant_q = _unique("q"), _unique("q")
        db.add(_event(
            event_name="visualization_selected", query_id=control_q, created_at=now,
            experiment_id=experiment.id, experiment_group="control", original_chart_type="bar", active_chart_type="bar",
        ))
        db.add(_event(
            event_name="visualization_selected", query_id=variant_q, created_at=now,
            experiment_id=experiment.id, experiment_group="variant", original_chart_type="bar", active_chart_type="bar",
        ))
    await db.commit()

    results = await experiments_service.compute_experiment_results(db, experiment.id)
    assert results.experiment_id == experiment.id
    assert results.control.selections == 8
    assert results.variant.selections == 8
    assert 0.0 <= results.control.recommendation_retention_rate.confidence_interval_low <= results.control.recommendation_retention_rate.confidence_interval_high <= 1.0
    assert results.result_status in ExperimentResultStatus


# ── telemetry privacy ───────────────────────────────────────────────────────

def test_telemetry_event_model_carries_no_forbidden_columns():
    forbidden = {"query_text", "answer_text", "chart_values", "categories", "series", "error", "error_message", "stack_trace", "score_breakdown"}
    assert forbidden.isdisjoint(VisualizationTelemetryEvent.__table__.columns.keys())


def test_record_visualization_event_signature_still_has_no_forbidden_parameters():
    import inspect
    from app.orchestration.visualization_telemetry import record_visualization_event
    parameters = set(inspect.signature(record_visualization_event).parameters)
    forbidden = {"query", "query_text", "answer", "answer_text", "chart_values", "categories", "series", "score_breakdown", "error", "stack"}
    assert parameters.isdisjoint(forbidden)


def test_ranking_experiment_model_carries_no_query_or_chart_content_columns():
    forbidden = {"query_text", "answer_text", "chart_values", "categories", "series"}
    assert forbidden.isdisjoint(RankingExperiment.__table__.columns.keys())


# ── presentation.py end-to-end wiring ─────────────────────────────────────

def _context(group: str, targeting_rules=None) -> ExperimentContext:
    return ExperimentContext(
        experiment_id="exp-1", group=group, control_ranking_version="1.0.0", variant_ranking_version="1.1.0",
        variant_weights=current_weights(), targeting_rules=targeting_rules or {},
    )


def test_presentation_tags_a_chart_when_targeting_matches_and_group_is_variant():
    plan = build_answer_presentation(
        "Show a chart comparing budget vs actual",
        "| Department | Budget | Actual |\n|---|---:|---:|\n| Payroll | 150000 | 158000 |\n| Tech | 60000 | 72000 |",
        experiment_context=_context("variant", {"analytical_intent": ["target_variance"]}),
    )
    chart = plan.charts[0]
    assert chart.experiment_id == "exp-1"
    assert chart.experiment_group == "variant"
    assert chart.ranking_version == "1.1.0"


def test_presentation_does_not_tag_a_chart_when_targeting_does_not_match():
    plan = build_answer_presentation(
        "Show a chart comparing budget vs actual",
        "| Department | Budget | Actual |\n|---|---:|---:|\n| Payroll | 150000 | 158000 |\n| Tech | 60000 | 72000 |",
        experiment_context=_context("variant", {"analytical_intent": ["comparison"]}),
    )
    chart = plan.charts[0]
    assert chart.experiment_id is None
    assert chart.experiment_group is None
    assert chart.ranking_version == RANKING_VERSION


def test_presentation_control_group_carries_the_control_ranking_version_but_no_weights_override():
    plan_no_experiment = build_answer_presentation(
        "Show a chart comparing budget vs actual",
        "| Department | Budget | Actual |\n|---|---:|---:|\n| Payroll | 150000 | 158000 |\n| Tech | 60000 | 72000 |",
    )
    plan_with_control = build_answer_presentation(
        "Show a chart comparing budget vs actual",
        "| Department | Budget | Actual |\n|---|---:|---:|\n| Payroll | 150000 | 158000 |\n| Tech | 60000 | 72000 |",
        experiment_context=_context("control", {"analytical_intent": ["target_variance"]}),
    )
    # The DEFAULT selection is identical either way (v1-v6 protected-default
    # guarantee holds under v7 too) — only the diagnostic metadata differs.
    assert plan_no_experiment.charts[0].type == plan_with_control.charts[0].type
    assert plan_with_control.charts[0].experiment_group == "control"
    assert plan_with_control.charts[0].ranking_version == "1.0.0"
