"""
Visualization decision-path telemetry (spec §25).

This codebase has no observability platform wired in today (no Sentry/
Datadog/OTel — confirmed by inspection before writing this). Building a real
telemetry *pipeline* (collector, backend, dashboards) is a separate,
substantial infra decision, not something to bolt on silently as a side
effect of a visualization feature. What this module does instead is the
honest, buildable piece: emit one structured (JSON-serializable) event per
visualization decision through Python's standard logging module, under a
dedicated logger name, capturing every field the spec's decision-path list
asks for that this pipeline actually produces. Wiring that logger to a real
sink (a file, a log-shipping agent, an APM) is an operational choice for
whoever deploys this — this module doesn't assume one.
"""
from __future__ import annotations

import json
import logging

from app.orchestration.visualization.orchestrator import OrchestratorResult
from app.orchestration.visualization.validator import VisualizationValidationResult

logger = logging.getLogger("kriton.visualization")


def log_decision(
    *,
    query_id: str,
    query: str | None = None,
    intent: str,
    data_shape: str,
    response_mode: str,
    visual_required: bool,
    result: OrchestratorResult,
    validation: VisualizationValidationResult | None,
    render_success: bool,
) -> None:
    event = {
        "query_id": query_id,
        "query": query,
        "intent": intent,
        "data_shape": data_shape,
        "response_mode": response_mode,
        "visual_required": visual_required,
        "candidate_scores": [{"type": c.type, "score": c.score} for c in result.candidates],
        "selected_visual": result.selected,
        "capability_id": result.capability_id,
        "visual_family": result.family,
        "canonical_visual": result.canonical,
        "selected_variant": result.variant,
        "domain": result.spec.domain_context.domain if result.spec else None,
        "subdomain": result.spec.domain_context.subdomain if result.spec else None,
        "selected_renderer": result.renderer,
        "fallback_order": result.fallback_order,
        "validation_result": validation.passed if validation else None,
        "validation_failures": validation.failures if validation else [],
        "render_success": render_success,
        "fallback_used": not render_success and visual_required,
    }
    logger.info(json.dumps(event, default=str))
