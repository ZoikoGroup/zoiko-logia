"""Dynamic Visualization Selection v4 — privacy-safe product telemetry.

Two responsibilities, deliberately kept in one small module:
  1. record_visualization_event() — write one allow-listed row per chart
     selection/interaction event.
  2. get_recent_chart_types() — read back the current conversation's recent
     chart types for the repetition-penalty scoring dimension.

The privacy boundary is enforced by the function SIGNATURE, not by
filtering afterward: record_visualization_event has no parameter that could
carry query text, answer text, chart values, source data, prompts,
reasoning summaries, or user-generated labels — there is no field to
accidentally pass one into. This is intentionally a separate table and
module from app/orchestration/audit_events.py (backed by AuditEvent /
audit_events.py's chain-hashed compliance ledger) — that ledger has its own
retention, correction (CompensatingEvent), and replay-relevance rules
governing a fundamentally different kind of record; product telemetry about
chart-rendering UX doesn't belong in it.
"""
from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration.models import VisualizationTelemetryEvent

_logger = logging.getLogger(__name__)

VisualizationEventName = Literal[
    "visualization_selected",
    "alternative_views_shown",
    "alternative_view_selected",
    "visualization_exported_png",
    "visualization_exported_csv",
    "visualization_saved",
    "visualization_render_failed",
    "visualization_fallback_used",
]

_MAX_RECENT_CHART_TYPES = 5


async def record_visualization_event(
    db: AsyncSession,
    *,
    event_name: VisualizationEventName,
    tenant_id: str,
    actor_id: str | None = None,
    conversation_id: str | None = None,
    query_id: str | None = None,
    analytical_intent: str | None = None,
    original_chart_type: str | None = None,
    active_chart_type: str | None = None,
    alternative_count: int | None = None,
    selection_source: str | None = None,
    renderer: str | None = None,
    schema_version: str | None = None,
    chart_family: str | None = None,
    ranking_version: str | None = None,
    experiment_id: str | None = None,
    experiment_group: str | None = None,
    preference_affected_selection: bool | None = None,
    environment: str | None = None,
    personalization_enabled: bool | None = None,
    personalization_affected_selection: bool | None = None,
    personalization_model_version: str | None = None,
    personalization_confidence_band: str | None = None,
) -> None:
    """Best-effort: a telemetry failure must never break chart rendering,
    view switching, exports, or saving (see callers in service.py) — this
    function itself never raises, it logs and returns."""
    try:
        if environment is None:
            from app.core.config import get_settings
            raw_environment = get_settings().APP_ENV.lower()
            environment = raw_environment if raw_environment in {"production", "staging", "development", "test"} else "development"
        db.add(VisualizationTelemetryEvent(
            event_name=event_name,
            tenant_id=tenant_id,
            actor_id=actor_id,
            conversation_id=conversation_id,
            query_id=query_id,
            analytical_intent=analytical_intent,
            original_chart_type=original_chart_type,
            active_chart_type=active_chart_type,
            alternative_count=alternative_count,
            selection_source=selection_source,
            renderer=renderer,
            schema_version=schema_version,
            chart_family=chart_family,
            ranking_version=ranking_version,
            experiment_id=experiment_id,
            experiment_group=experiment_group,
            preference_affected_selection=preference_affected_selection,
            environment=environment,
            personalization_enabled=personalization_enabled,
            personalization_affected_selection=personalization_affected_selection,
            personalization_model_version=personalization_model_version,
            personalization_confidence_band=personalization_confidence_band,
        ))
        await db.commit()
    except Exception:
        _logger.warning("visualization_telemetry_write_failed", extra={"event_name": event_name}, exc_info=True)
        await db.rollback()


async def get_recent_chart_types(
    db: AsyncSession, *, tenant_id: str, actor_id: str | None, conversation_id: str | None,
    limit: int = _MAX_RECENT_CHART_TYPES,
) -> tuple[str, ...]:
    """Newest-first chart types actually selected earlier in this exact
    conversation. Scoped by (tenant_id, actor_id, conversation_id) together
    — tenant_id alone isn't enough in a multi-user workspace, and
    conversation_id alone isn't trustworthy on its own since it's a
    client-generated string never used for authorization. Without a
    conversation_id (older clients, or a query outside any chat thread)
    there is by definition no "current conversation" history to return.
    Capped at 5 regardless of the caller-supplied limit."""
    if not conversation_id:
        return ()
    capped_limit = min(limit, _MAX_RECENT_CHART_TYPES)
    try:
        result = await db.execute(
            select(VisualizationTelemetryEvent.active_chart_type)
            .where(
                VisualizationTelemetryEvent.event_name == "visualization_selected",
                VisualizationTelemetryEvent.tenant_id == tenant_id,
                VisualizationTelemetryEvent.actor_id == actor_id,
                VisualizationTelemetryEvent.conversation_id == conversation_id,
                VisualizationTelemetryEvent.active_chart_type.is_not(None),
            )
            .order_by(VisualizationTelemetryEvent.created_at.desc())
            .limit(capped_limit)
        )
        return tuple(row[0] for row in result.all())
    except Exception:
        _logger.warning("visualization_telemetry_read_failed", exc_info=True)
        return ()
