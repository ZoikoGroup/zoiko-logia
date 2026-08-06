"""Tests for Dynamic Visualization Selection v4's telemetry module —
recording events, recent-chart-type extraction/isolation, and the privacy
boundary enforced by record_visualization_event's signature.

IDs are uuid-suffixed per test rather than fixed strings: tests/conftest.py
points at a real SQLite file (./test.db) that persists across separate
`pytest` invocations, not a fresh in-memory DB per run — a fixed
conversation_id like "conv-A" would accumulate rows across runs and break
exact-count/order assertions the second time the suite runs.
"""
import inspect
import uuid

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.orchestration.models import VisualizationTelemetryEvent
from app.orchestration.schemas import VisualizationTelemetryRequest
from app.orchestration.visualization_telemetry import (
    get_recent_chart_types,
    record_visualization_event,
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


async def _select(db, event_name, tenant_id, actor_id, conversation_id, query_id, chart_type, alternatives=0):
    await record_visualization_event(
        db, event_name=event_name, tenant_id=tenant_id, actor_id=actor_id, conversation_id=conversation_id,
        query_id=query_id, analytical_intent="comparison", original_chart_type=chart_type,
        active_chart_type=chart_type, alternative_count=alternatives, selection_source="deterministic_default",
        renderer="recharts", schema_version="1.0",
    )


@pytest.mark.asyncio
async def test_recent_chart_types_extracted_only_from_the_current_conversation(db):
    tenant_id, actor_id = _unique("tenant"), _unique("user")
    conv_a, conv_b = _unique("conv"), _unique("conv")
    await _select(db, "visualization_selected", tenant_id, actor_id, conv_a, "q1", "grouped_bar")
    await _select(db, "visualization_selected", tenant_id, actor_id, conv_b, "q2", "radar")
    recent = await get_recent_chart_types(db, tenant_id=tenant_id, actor_id=actor_id, conversation_id=conv_a)
    assert recent == ("grouped_bar",)


@pytest.mark.asyncio
async def test_at_most_five_recent_chart_types_are_supplied(db):
    tenant_id, actor_id, conversation_id = _unique("tenant"), _unique("user"), _unique("conv")
    for i, chart_type in enumerate(["bar", "grouped_bar", "radar", "dumbbell", "lollipop", "bullet", "scatter"]):
        await _select(db, "visualization_selected", tenant_id, actor_id, conversation_id, f"q{i}", chart_type)
    recent = await get_recent_chart_types(db, tenant_id=tenant_id, actor_id=actor_id, conversation_id=conversation_id)
    assert len(recent) == 5
    # Newest-first — the last 5 inserted, most recent first.
    assert recent == ("scatter", "bullet", "lollipop", "dumbbell", "radar")


@pytest.mark.asyncio
async def test_non_selected_event_types_are_excluded_from_recent_history(db):
    tenant_id, actor_id, conversation_id = _unique("tenant"), _unique("user"), _unique("conv")
    await _select(db, "visualization_selected", tenant_id, actor_id, conversation_id, "q1", "grouped_bar")
    # alternative_views_shown and visualization_fallback_used are real rows
    # in the same table, but must never count as "a chart was selected".
    await _select(db, "alternative_views_shown", tenant_id, actor_id, conversation_id, "q1", "dumbbell")
    await _select(db, "visualization_fallback_used", tenant_id, actor_id, conversation_id, "q1", "bar")
    recent = await get_recent_chart_types(db, tenant_id=tenant_id, actor_id=actor_id, conversation_id=conversation_id)
    assert recent == ("grouped_bar",)


@pytest.mark.asyncio
async def test_different_users_never_share_history(db):
    tenant_id, conversation_id = _unique("tenant"), _unique("conv")
    user_a, user_b = _unique("user"), _unique("user")
    await _select(db, "visualization_selected", tenant_id, user_a, conversation_id, "q1", "grouped_bar")
    recent = await get_recent_chart_types(db, tenant_id=tenant_id, actor_id=user_b, conversation_id=conversation_id)
    assert recent == ()


@pytest.mark.asyncio
async def test_different_workspaces_never_share_history(db):
    actor_id, conversation_id = _unique("user"), _unique("conv")
    tenant_a, tenant_b = _unique("tenant"), _unique("tenant")
    await _select(db, "visualization_selected", tenant_a, actor_id, conversation_id, "q1", "grouped_bar")
    recent = await get_recent_chart_types(db, tenant_id=tenant_b, actor_id=actor_id, conversation_id=conversation_id)
    assert recent == ()


@pytest.mark.asyncio
async def test_no_conversation_id_returns_no_history(db):
    recent = await get_recent_chart_types(db, tenant_id=_unique("tenant"), actor_id=_unique("user"), conversation_id=None)
    assert recent == ()


@pytest.mark.asyncio
async def test_recording_an_event_persists_the_expected_row(db):
    conversation_id = _unique("conv")
    await _select(db, "visualization_selected", _unique("tenant"), _unique("user"), conversation_id, "q1", "waterfall", alternatives=2)
    result = await db.execute(
        select(VisualizationTelemetryEvent).where(VisualizationTelemetryEvent.conversation_id == conversation_id)
    )
    row = result.scalar_one()
    assert row.active_chart_type == "waterfall"
    assert row.alternative_count == 2
    assert row.selection_source == "deterministic_default"
    assert row.renderer == "recharts"


@pytest.mark.asyncio
async def test_recording_an_event_persists_experiment_and_personalization_fields(db):
    """Regression test: service.py's real call sites pass experiment_id/
    experiment_group (v7) and personalization_enabled/
    personalization_affected_selection/personalization_model_version/
    personalization_confidence_band (v10) as keyword arguments — this must
    round-trip through to the persisted row, not just be accepted as a
    parameter. Caught a real bug where the v10 fields were added to the
    ORM model and to every service.py call site but never actually added
    as parameters on this function itself, which raised TypeError on every
    live /ask call that returned a chart."""
    conversation_id = _unique("conv")
    await record_visualization_event(
        db, event_name="visualization_selected", tenant_id=_unique("tenant"), actor_id=_unique("user"),
        conversation_id=conversation_id, query_id="q1", analytical_intent="comparison",
        original_chart_type="grouped_bar", active_chart_type="grouped_bar", alternative_count=0,
        selection_source="personalized", renderer="recharts", schema_version="1.0",
        experiment_id="exp-1", experiment_group="control",
        personalization_enabled=True, personalization_affected_selection=True,
        personalization_model_version="personalization-1.0", personalization_confidence_band="high",
    )
    result = await db.execute(
        select(VisualizationTelemetryEvent).where(VisualizationTelemetryEvent.conversation_id == conversation_id)
    )
    row = result.scalar_one()
    assert row.experiment_id == "exp-1"
    assert row.experiment_group == "control"
    assert row.personalization_enabled is True
    assert row.personalization_affected_selection is True
    assert row.personalization_model_version == "personalization-1.0"
    assert row.personalization_confidence_band == "high"


@pytest.mark.asyncio
async def test_telemetry_write_failure_never_raises(db, monkeypatch):
    # A telemetry failure must never break the surrounding workflow (chart
    # rendering, answer generation) — record_visualization_event must
    # swallow the error, not propagate it.
    async def _boom():
        raise RuntimeError("simulated DB outage")
    monkeypatch.setattr(db, "commit", _boom)
    await record_visualization_event(
        db, event_name="visualization_selected", tenant_id=_unique("tenant"), actor_id=_unique("user"),
        conversation_id=_unique("conv"), query_id="q1", analytical_intent="comparison",
        original_chart_type="grouped_bar", active_chart_type="grouped_bar", alternative_count=0,
        selection_source="deterministic_default", renderer="recharts", schema_version="1.0",
    )  # no exception raised


@pytest.mark.asyncio
async def test_get_recent_chart_types_failure_returns_empty_tuple_not_an_exception(db, monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB outage")
    monkeypatch.setattr(db, "execute", _boom)
    recent = await get_recent_chart_types(db, tenant_id=_unique("tenant"), actor_id=_unique("user"), conversation_id=_unique("conv"))
    assert recent == ()


def test_client_cannot_post_a_backend_only_event_name():
    # visualization_selected / alternative_views_shown /
    # visualization_fallback_used are only ever emitted server-side, at
    # answer-generation time — the client-facing schema must reject them,
    # so a client can never fabricate a "visualization_selected" event to
    # manipulate its own recent_chart_types repetition history.
    for backend_only_event in ("visualization_selected", "alternative_views_shown", "visualization_fallback_used"):
        with pytest.raises(ValidationError):
            VisualizationTelemetryRequest(event_name=backend_only_event)


def test_client_can_post_the_five_client_side_event_names():
    for event_name in (
        "alternative_view_selected", "visualization_exported_png", "visualization_exported_csv",
        "visualization_saved", "visualization_render_failed",
    ):
        request = VisualizationTelemetryRequest(event_name=event_name)
        assert request.event_name == event_name


def test_record_visualization_event_signature_cannot_carry_sensitive_content():
    # The privacy boundary is structural: assert none of these parameter
    # names exist on the function at all, so there is no field a future
    # call site could accidentally populate with sensitive content.
    parameters = set(inspect.signature(record_visualization_event).parameters)
    forbidden = {
        "query", "query_text", "answer", "answer_text", "chart_values", "categories", "series",
        "source_data", "prompt", "prompt_text", "reasoning_summary", "reasoning", "title", "label",
        "credentials", "token", "password",
    }
    assert parameters.isdisjoint(forbidden)
