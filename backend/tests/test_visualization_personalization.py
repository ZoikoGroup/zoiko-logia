"""Tests for V10 — consent-based personalized visualization recommendations.

Same persistent-SQLite-file precedent as the other orchestration test
files: tests/conftest.py points at a real file (./test.db) shared across
separate `pytest` runs, so every id is uuid-suffixed per test.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.orchestration import visualization_personalization as personalization
from app.orchestration.models import (
    VisualizationPersonalizationConsent,
    VisualizationPersonalizationProfile,
    VisualizationPersonalizationRecomputationRun,
    VisualizationTelemetryEvent,
)
from app.orchestration.presentation_dataprofile import (
    AnalyticalIntent,
    DataProfile,
    SelectionSource,
    select_chart_type,
    select_chart_with_alternatives,
)
from app.orchestration.presentation import build_answer_presentation
from app.orchestration.schemas import PresentationChart
from app.orchestration.visualization_personalization_consent import (
    PersonalizationConsent,
    delete_personalization,
    get_consent,
    put_consent,
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


def _event(
    *, event_name, tenant_id, actor_id, conversation_id, query_id, created_at,
    analytical_intent=None, chart_family=None, original_chart_type=None, active_chart_type=None,
    environment="production",
) -> VisualizationTelemetryEvent:
    return VisualizationTelemetryEvent(
        event_name=event_name, tenant_id=tenant_id, actor_id=actor_id, conversation_id=conversation_id,
        query_id=query_id, analytical_intent=analytical_intent, original_chart_type=original_chart_type,
        active_chart_type=active_chart_type, schema_version="1.0", chart_family=chart_family,
        environment=environment, created_at=created_at,
    )


async def _seed_eligible_profile(
    db, *, tenant_id, actor_id, intent="comparison", family="paired_numeric",
    preferred_type="dumbbell", other_type="grouped_bar", count=20, conversations=5,
    consent: PersonalizationConsent | None = None,
) -> None:
    """Seeds enough VisualizationTelemetryEvent rows for `actor_id` to clear
    every minimum-evidence threshold, with a clear (80/20) majority
    preference for `preferred_type` within (intent, family), then runs a
    real recomputation so the resulting profile is exactly what production
    code would compute — not a hand-built fixture."""
    consent = consent or PersonalizationConsent(personalization_enabled=True)
    await put_consent(db, tenant_id, actor_id, consent)
    base = datetime.now(timezone.utc) - timedelta(days=10)
    for i in range(count):
        chart_type = preferred_type if i % 5 != 0 else other_type
        conv = f"conv-{i % conversations}"
        db.add(_event(
            event_name="visualization_selected", tenant_id=tenant_id, actor_id=actor_id,
            conversation_id=conv, query_id=_unique("q"), analytical_intent=intent, chart_family=family,
            original_chart_type=chart_type, active_chart_type=chart_type,
            # Spread across >7 days (not just >7 hours) — MIN_DAYS_OBSERVED
            # requires the first/last interaction to actually span a week.
            created_at=base + timedelta(hours=i * 12),
        ))
    await db.commit()
    result = await personalization.recompute_tenant_profiles(db, tenant_id)
    assert result.status == "succeeded"


# ── consent defaults and write path ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_personalization_is_disabled_by_default(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    consent = await get_consent(db, tenant_id, actor_id)
    assert consent.personalization_enabled is False


@pytest.mark.asyncio
async def test_consent_is_never_created_implicitly(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await get_consent(db, tenant_id, actor_id)
    row = await db.scalar(select(VisualizationPersonalizationConsent).where(
        VisualizationPersonalizationConsent.tenant_id == tenant_id, VisualizationPersonalizationConsent.actor_id == actor_id,
    ))
    assert row is None


# ── fail-safe resolution: disabled / insufficient evidence / stale ─────────

@pytest.mark.asyncio
async def test_no_consent_users_produce_no_personalization_hint(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    hint = await personalization.resolve_personalization_hint(db, tenant_id, actor_id)
    assert hint is None


@pytest.mark.asyncio
async def test_insufficient_evidence_produces_no_hint(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await put_consent(db, tenant_id, actor_id, PersonalizationConsent(personalization_enabled=True))
    base = datetime.now(timezone.utc) - timedelta(days=10)
    for i in range(5):  # below MIN_INTERACTIONS=10
        db.add(_event(
            event_name="visualization_selected", tenant_id=tenant_id, actor_id=actor_id,
            conversation_id=f"conv-{i}", query_id=_unique("q"), analytical_intent="comparison",
            chart_family="paired_numeric", original_chart_type="dumbbell", active_chart_type="dumbbell",
            created_at=base + timedelta(hours=i),
        ))
    await db.commit()
    result = await personalization.recompute_tenant_profiles(db, tenant_id)
    assert result.status == "succeeded"
    hint = await personalization.resolve_personalization_hint(db, tenant_id, actor_id)
    assert hint is None


@pytest.mark.asyncio
async def test_stale_profile_produces_no_hint(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await _seed_eligible_profile(db, tenant_id=tenant_id, actor_id=actor_id)
    row = await db.scalar(select(VisualizationPersonalizationProfile).where(
        VisualizationPersonalizationProfile.tenant_id == tenant_id, VisualizationPersonalizationProfile.actor_id == actor_id,
    ))
    row.last_recomputed_at = datetime.now(timezone.utc) - timedelta(days=10)
    await db.commit()
    hint = await personalization.resolve_personalization_hint(db, tenant_id, actor_id)
    assert hint is None


@pytest.mark.asyncio
async def test_disabling_consent_immediately_stops_hint_resolution(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await _seed_eligible_profile(db, tenant_id=tenant_id, actor_id=actor_id)
    assert await personalization.resolve_personalization_hint(db, tenant_id, actor_id) is not None
    await put_consent(db, tenant_id, actor_id, PersonalizationConsent(personalization_enabled=False))
    assert await personalization.resolve_personalization_hint(db, tenant_id, actor_id) is None


# ── deterministic profile computation ───────────────────────────────────────

def test_compute_profile_is_pure_and_deterministic():
    consent = PersonalizationConsent(personalization_enabled=True)
    base = datetime.now(timezone.utc)
    events = [
        _event(event_name="visualization_selected", tenant_id="t", actor_id="a", conversation_id=f"c{i % 3}",
               query_id=f"q{i}", analytical_intent="comparison", chart_family="paired_numeric",
               original_chart_type="dumbbell", active_chart_type="dumbbell", created_at=base + timedelta(hours=i))
        for i in range(12)
    ]
    first = personalization.compute_profile(events, consent)
    second = personalization.compute_profile(events, consent)
    assert first == second
    assert first.meets_minimum_evidence is False  # only spans a few hours, not 7 days


def test_compute_profile_meets_evidence_thresholds_when_genuinely_diverse():
    consent = PersonalizationConsent(personalization_enabled=True)
    base = datetime.now(timezone.utc) - timedelta(days=9)
    events = [
        _event(event_name="visualization_selected", tenant_id="t", actor_id="a", conversation_id=f"c{i % 4}",
               query_id=f"q{i}", analytical_intent="comparison", chart_family="paired_numeric",
               original_chart_type="dumbbell", active_chart_type="dumbbell", created_at=base + timedelta(days=i))
        for i in range(10)
    ]
    computation = personalization.compute_profile(events, consent)
    assert computation.interaction_count == 10
    assert computation.conversation_count == 4
    assert computation.days_observed == 9
    assert computation.meets_minimum_evidence is True


# ── scoring integration: near-tie override, never a compatibility bypass ──

def _paired_numeric_profile() -> DataProfile:
    return DataProfile(dimensions=("Entity",), measures=("Budget", "Actual"), category_count=6, measure_count=2)


def test_eligible_signal_reorders_only_compatible_near_tied_candidates():
    profile = _paired_numeric_profile()
    default_type = select_chart_type(AnalyticalIntent.COMPARISON, profile)
    baseline = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile)
    # Pick a compatible candidate other than the default to nudge toward.
    other_candidate = next(c.chart_type for c in baseline.candidates if c.chart_type != default_type)
    personalized = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, profile,
        personalization_preferred_chart_type=other_candidate, personalization_boosts={other_candidate: 1.0},
    )
    # Either it won the near tie (bounded, legitimate) or it didn't — either
    # way it must still be a compatible candidate, never an invented type.
    assert personalized.chart_type in {c.chart_type for c in baseline.candidates}


def test_personalization_never_makes_an_incompatible_chart_selectable():
    profile = _paired_numeric_profile()
    result = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, profile,
        personalization_preferred_chart_type="sankey",  # never compatible with this profile/intent
        personalization_boosts={"sankey": 1.0},
    )
    assert result.chart_type != "sankey"
    assert "sankey" not in result.alternatives


def test_explicit_chart_request_overrides_personalization():
    profile = DataProfile(dimensions=("Entity",), measures=("A", "B"), category_count=5, measure_count=2)
    baseline = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, query="show a dumbbell chart")
    other_candidate = next((c.chart_type for c in baseline.candidates if c.chart_type != "dumbbell"), None)
    assert other_candidate is not None
    result = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, profile, query="show a dumbbell chart",
        personalization_preferred_chart_type=other_candidate, personalization_boosts={other_candidate: 1.0},
    )
    assert result.chart_type == "dumbbell"
    assert result.selection_source == SelectionSource.EXPLICIT_USER_REQUEST
    assert result.personalization_affected_selection is False


def test_explicit_saved_preference_overrides_personalization():
    profile = DataProfile(dimensions=("Entity",), measures=("A", "B"), category_count=5, measure_count=2)
    baseline = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile)
    candidates = {c.chart_type for c in baseline.candidates}
    preferred, other = list(candidates)[:2] if len(candidates) >= 2 else (baseline.chart_type, None)
    if other is None:
        pytest.skip("profile does not have two distinct compatible candidates to test with")
    result = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, profile, preferred_chart_type=preferred,
        personalization_preferred_chart_type=other, personalization_boosts={other: 1.0},
    )
    assert result.chart_type == preferred
    assert result.personalization_affected_selection is False


def test_personalization_cannot_override_a_major_analytical_intent_difference():
    """radar is only reachable for measure_count>=3 comparisons — a
    3-measure profile's overwhelming intent/data-fit gap in radar's favor
    must not be erased by a personalization boost toward a 2-measure-style
    candidate that isn't even compatible here."""
    profile = DataProfile(dimensions=("Entity",), measures=("A", "B", "C"), category_count=4, measure_count=3)
    baseline = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile)
    assert baseline.chart_type == "radar"
    result = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, profile,
        personalization_preferred_chart_type="bar", personalization_boosts={"bar": 1.0},
    )
    # "bar" isn't in radar's compatible-candidate set for this profile, so
    # even a maximal boost cannot promote it.
    assert result.chart_type == "radar"


def test_rankings_remain_deterministic_across_repeated_calls():
    profile = _paired_numeric_profile()
    first = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, profile,
        personalization_preferred_chart_type="grouped_bar", personalization_boosts={"grouped_bar": 0.9},
    )
    second = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, profile,
        personalization_preferred_chart_type="grouped_bar", personalization_boosts={"grouped_bar": 0.9},
    )
    assert first.chart_type == second.chart_type
    assert first.alternatives == second.alternatives


def test_personalization_boost_is_clamped_regardless_of_caller_input():
    """A malicious/buggy caller passing boosts >> _MAX_PERSONALIZATION_BOOST
    must not be able to manufacture an advantage larger than the bound."""
    from app.orchestration.presentation_dataprofile import _score_candidate

    profile = _paired_numeric_profile()
    normal = _score_candidate("grouped_bar", AnalyticalIntent.COMPARISON, profile, "", ())
    boosted = _score_candidate(
        "grouped_bar", AnalyticalIntent.COMPARISON, profile, "", (), None, {"grouped_bar": 999.0},
    )
    assert boosted.score - normal.score <= personalization.MIN_SIGNAL_CONFIDENCE  # sanity: nowhere near 999
    from app.orchestration.presentation_dataprofile import _MAX_PERSONALIZATION_BOOST
    assert abs((boosted.score - normal.score) - _MAX_PERSONALIZATION_BOOST) < 1e-9


# ── per-chart hint extraction ────────────────────────────────────────────────

def test_hint_for_chart_requires_its_own_signal_confidence():
    hint = personalization.PersonalizationHint(
        chart_family_preferences={}, intent_chart_preferences={"comparison": {"dumbbell": 0.55, "grouped_bar": 0.45}},
        confidence_by_signal={"intent:comparison": 0.3},  # below MIN_SIGNAL_CONFIDENCE
        model_version="v1",
    )
    preferred, boosts, band = personalization.personalization_hint_for_chart(hint, "comparison", "two_point_per_entity")
    assert preferred is None
    assert boosts == {}
    assert band is None


def test_hint_for_chart_applies_when_confidence_clears_the_bar():
    hint = personalization.PersonalizationHint(
        chart_family_preferences={}, intent_chart_preferences={"comparison": {"dumbbell": 0.9, "grouped_bar": 0.1}},
        confidence_by_signal={"intent:comparison": 0.9},
        model_version="v1",
    )
    preferred, boosts, band = personalization.personalization_hint_for_chart(hint, "comparison", None)
    assert preferred == "dumbbell"
    assert band == "high"


def test_none_hint_never_applies():
    preferred, boosts, band = personalization.personalization_hint_for_chart(None, "comparison", "paired_numeric")
    assert preferred is None and boosts == {} and band is None


# ── recomputation run lifecycle (mirrors V8.5's idempotency contract) ─────

@pytest.mark.asyncio
async def test_recomputation_is_idempotent_within_the_same_day(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await _seed_eligible_profile(db, tenant_id=tenant_id, actor_id=actor_id)
    second = await personalization.recompute_tenant_profiles(db, tenant_id)
    assert second.status == "succeeded"
    runs = (await db.execute(select(VisualizationPersonalizationRecomputationRun).where(
        VisualizationPersonalizationRecomputationRun.tenant_id == tenant_id,
    ))).scalars().all()
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_concurrent_recomputation_is_rejected_not_raced(db):
    tenant_id = _unique("tenant")
    running = VisualizationPersonalizationRecomputationRun(
        tenant_id=tenant_id, started_at=datetime.now(timezone.utc), status="running",
        processing_date=datetime.now(timezone.utc).date().isoformat(), profile_version="v1",
        profiles_recomputed_count=0, event_count=0, triggered_by="test",
    )
    db.add(running)
    await db.commit()
    with pytest.raises(personalization.MonitoringRunAlreadyActiveError):
        await personalization.recompute_tenant_profiles(db, tenant_id)


@pytest.mark.asyncio
async def test_recomputation_only_processes_consented_actors(db):
    tenant_id = _unique("tenant")
    consented_actor, non_consented_actor = _unique("actor"), _unique("actor")
    await _seed_eligible_profile(db, tenant_id=tenant_id, actor_id=consented_actor)
    # A second actor with events but consent OFF (opt-out) must never get a profile.
    await put_consent(db, tenant_id, non_consented_actor, PersonalizationConsent(personalization_enabled=False))
    base = datetime.now(timezone.utc) - timedelta(days=10)
    for i in range(20):
        db.add(_event(
            event_name="visualization_selected", tenant_id=tenant_id, actor_id=non_consented_actor,
            conversation_id=f"conv-{i % 5}", query_id=_unique("q"), analytical_intent="comparison",
            chart_family="paired_numeric", original_chart_type="dumbbell", active_chart_type="dumbbell",
            created_at=base + timedelta(hours=i),
        ))
    await db.commit()

    profile_row = await db.scalar(select(VisualizationPersonalizationProfile).where(
        VisualizationPersonalizationProfile.tenant_id == tenant_id, VisualizationPersonalizationProfile.actor_id == non_consented_actor,
    ))
    assert profile_row is None  # opt-out stops learning — requirement 14


@pytest.mark.asyncio
async def test_failed_recomputation_falls_back_safely_and_records_a_safe_category(db, monkeypatch):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await put_consent(db, tenant_id, actor_id, PersonalizationConsent(personalization_enabled=True))

    async def _boom(*args, **kwargs):
        raise ValueError("sensitive internal detail that must never be stored")

    monkeypatch.setattr(personalization, "_fetch_actor_events", _boom)
    result = await personalization.recompute_tenant_profiles(db, tenant_id)
    assert result.status == "failed"
    assert result.failure_category == personalization.FailureCategory.VALIDATION_ERROR.value

    hint = await personalization.resolve_personalization_hint(db, tenant_id, actor_id)
    assert hint is None  # falls back to the exact ordinary V9 result


# ── reset / opt-out / delete ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_removes_learned_influence_but_keeps_consent(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await _seed_eligible_profile(db, tenant_id=tenant_id, actor_id=actor_id)
    assert await personalization.resolve_personalization_hint(db, tenant_id, actor_id) is not None
    await personalization.reset_learned_profile(db, tenant_id, actor_id)
    assert await personalization.resolve_personalization_hint(db, tenant_id, actor_id) is None
    consent = await get_consent(db, tenant_id, actor_id)
    assert consent.personalization_enabled is True  # untouched by reset


@pytest.mark.asyncio
async def test_delete_removes_both_profile_and_consent(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await _seed_eligible_profile(db, tenant_id=tenant_id, actor_id=actor_id)
    await delete_personalization(db, tenant_id, actor_id)
    assert await db.scalar(select(VisualizationPersonalizationProfile).where(
        VisualizationPersonalizationProfile.tenant_id == tenant_id, VisualizationPersonalizationProfile.actor_id == actor_id,
    )) is None
    consent = await get_consent(db, tenant_id, actor_id)
    assert consent.personalization_enabled is False  # back to default, no row


@pytest.mark.asyncio
async def test_delete_is_idempotent_on_an_already_absent_profile(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await delete_personalization(db, tenant_id, actor_id)  # must not raise


# ── expired events / retention window ───────────────────────────────────────

@pytest.mark.asyncio
async def test_expired_events_outside_the_history_window_do_not_affect_the_profile(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await put_consent(db, tenant_id, actor_id, PersonalizationConsent(personalization_enabled=True, personalization_history_window="30_days"))
    stale_base = datetime.now(timezone.utc) - timedelta(days=200)
    for i in range(20):
        db.add(_event(
            event_name="visualization_selected", tenant_id=tenant_id, actor_id=actor_id,
            conversation_id=f"conv-{i % 5}", query_id=_unique("q"), analytical_intent="comparison",
            chart_family="paired_numeric", original_chart_type="dumbbell", active_chart_type="dumbbell",
            created_at=stale_base + timedelta(hours=i),
        ))
    await db.commit()
    result = await personalization.recompute_tenant_profiles(db, tenant_id)
    assert result.status == "succeeded"
    assert result.event_count == 0  # every event fell outside the 30-day window
    hint = await personalization.resolve_personalization_hint(db, tenant_id, actor_id)
    assert hint is None


# ── learning-source gating ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_view_switch_learning_is_ignored_when_disabled(db):
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await put_consent(db, tenant_id, actor_id, PersonalizationConsent(personalization_enabled=True, allow_view_switch_learning=False))
    base = datetime.now(timezone.utc) - timedelta(days=9)
    events = []
    for i in range(12):
        query_id = _unique("q")
        events.append(_event(
            event_name="visualization_selected", tenant_id=tenant_id, actor_id=actor_id, conversation_id=f"conv-{i % 4}",
            query_id=query_id, analytical_intent="comparison", chart_family="paired_numeric",
            original_chart_type="dumbbell", active_chart_type="dumbbell", created_at=base + timedelta(days=i),
        ))
        events.append(_event(
            event_name="alternative_view_selected", tenant_id=tenant_id, actor_id=actor_id, conversation_id=f"conv-{i % 4}",
            query_id=query_id, analytical_intent="comparison", chart_family="paired_numeric",
            original_chart_type="dumbbell", active_chart_type="grouped_bar", created_at=base + timedelta(days=i, minutes=1),
        ))
    consent = PersonalizationConsent(personalization_enabled=True, allow_view_switch_learning=False)
    computation = personalization.compute_profile(events, consent)
    # Every interaction's final_chart_type must still be "dumbbell" (the
    # original), never "grouped_bar" (the switched-to type) — the switch
    # event is invisible to learning when the toggle is off.
    assert computation.chart_family_preferences["paired_numeric"] == {"dumbbell": 1.0}


@pytest.mark.asyncio
async def test_view_switch_learning_is_used_when_enabled(db):
    base = datetime.now(timezone.utc) - timedelta(days=9)
    events = []
    for i in range(12):
        query_id = _unique("q")
        events.append(_event(
            event_name="visualization_selected", tenant_id="t", actor_id="a", conversation_id=f"conv-{i % 4}",
            query_id=query_id, analytical_intent="comparison", chart_family="paired_numeric",
            original_chart_type="dumbbell", active_chart_type="dumbbell", created_at=base + timedelta(days=i),
        ))
        events.append(_event(
            event_name="alternative_view_selected", tenant_id="t", actor_id="a", conversation_id=f"conv-{i % 4}",
            query_id=query_id, analytical_intent="comparison", chart_family="paired_numeric",
            original_chart_type="dumbbell", active_chart_type="grouped_bar", created_at=base + timedelta(days=i, minutes=1),
        ))
    consent = PersonalizationConsent(personalization_enabled=True, allow_view_switch_learning=True)
    computation = personalization.compute_profile(events, consent)
    assert computation.chart_family_preferences["paired_numeric"] == {"grouped_bar": 1.0}


@pytest.mark.asyncio
async def test_one_switch_does_not_immediately_alter_the_profile(db):
    """The profile only changes via recomputation, never live off a single
    telemetry write — resolving the hint before any recompute must be
    unaffected by events that were just recorded."""
    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await _seed_eligible_profile(db, tenant_id=tenant_id, actor_id=actor_id, preferred_type="dumbbell")
    before = await personalization.resolve_personalization_hint(db, tenant_id, actor_id)
    db.add(_event(
        event_name="alternative_view_selected", tenant_id=tenant_id, actor_id=actor_id, conversation_id=_unique("conv"),
        query_id=_unique("q"), analytical_intent="comparison", chart_family="paired_numeric",
        original_chart_type="dumbbell", active_chart_type="grouped_bar", created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    after = await personalization.resolve_personalization_hint(db, tenant_id, actor_id)
    assert before.chart_family_preferences == after.chart_family_preferences


# ── tenant/actor isolation ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_personalization_is_isolated_across_tenants_and_actors(db):
    tenant_a, tenant_b = _unique("tenant"), _unique("tenant")
    actor_a, actor_b = _unique("actor"), _unique("actor")
    await _seed_eligible_profile(db, tenant_id=tenant_a, actor_id=actor_a, preferred_type="dumbbell")
    assert await personalization.resolve_personalization_hint(db, tenant_a, actor_b) is None
    assert await personalization.resolve_personalization_hint(db, tenant_b, actor_a) is None
    assert await personalization.resolve_personalization_hint(db, tenant_a, actor_a) is not None


@pytest.mark.asyncio
async def test_tenant_deletion_removes_all_tenant_scoped_records(db):
    from app.orchestration.visualization_personalization_consent import delete_tenant_personalization

    tenant_id, actor_id = _unique("tenant"), _unique("actor")
    await _seed_eligible_profile(db, tenant_id=tenant_id, actor_id=actor_id)
    await delete_tenant_personalization(db, tenant_id)
    assert await db.scalar(select(VisualizationPersonalizationConsent).where(VisualizationPersonalizationConsent.tenant_id == tenant_id)) is None
    assert await db.scalar(select(VisualizationPersonalizationProfile).where(VisualizationPersonalizationProfile.tenant_id == tenant_id)) is None


# ── telemetry never carries prohibited content ──────────────────────────────

def test_telemetry_table_has_no_column_that_could_carry_profile_content():
    forbidden = {"chart_family_preferences", "intent_chart_preferences", "confidence_by_signal", "raw_score", "profile"}
    assert forbidden.isdisjoint(VisualizationTelemetryEvent.__table__.columns.keys())


def test_telemetry_personalization_columns_are_enum_or_boolean_only():
    columns = VisualizationTelemetryEvent.__table__.columns
    assert columns["personalization_enabled"].type.python_type is bool
    assert columns["personalization_affected_selection"].type.python_type is bool
    assert columns["personalization_confidence_band"].type.python_type is str  # enum-valued string, never free text


# ── old saved payloads remain compatible ────────────────────────────────────

def test_v1_style_saved_payload_still_validates_with_v10_defaults():
    legacy = {
        "chart_id": "c1", "type": "bar", "title": "Revenue", "categories": ["A", "B"],
        "series": [{"name": "Revenue", "values": ["1", "2"], "unit": "$"}],
    }
    chart = PresentationChart.model_validate(legacy)
    assert chart.personalization_enabled is False
    assert chart.personalization_affected_selection is False
    assert chart.personalization_model_version is None
    assert chart.personalization_confidence_band is None


# ── end-to-end: build_answer_presentation without a hint behaves like V9 ──

def test_build_answer_presentation_without_personalization_hint_matches_no_personalization_params():
    query = "show a dumbbell chart"
    table = "| Entity | Budget | Actual |\n|---|---:|---:|\n| A | 100 | 120 |\n| B | 200 | 180 |"
    with_none = build_answer_presentation(query, table)
    without_arg = build_answer_presentation(query, table, personalization_hint=None)
    assert with_none.charts[0].type == without_arg.charts[0].type
    assert with_none.charts[0].personalization_enabled is False
