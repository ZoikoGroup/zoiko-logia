"""
Frontend visualization-interaction telemetry.

Same honest scope as telemetry.py's log_decision() — this codebase has no
observability pipeline (Sentry/Datadog/OTel) wired in, and building one is a
separate infra decision, not something to fake as a side effect of the
rendering layer. This logs one structured event per meaningful client
interaction (view switched, exported, saved, table view opened, render
failed) through Python's standard logging module, under its own logger name.
Wiring that logger to a real sink is an operational choice for whoever
deploys this.

Deliberately NOT written through record_event_async (audit_ledger) — that is
a hash-chained, tenant-scoped compliance audit trail for governance events
(query received, prescreen completed, ...); a high-frequency, best-effort UI
interaction stream is a different concern and would pollute that chain with
non-governance noise for no compliance benefit.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("kriton.frontend_interaction")

# Closed vocabulary (spec: "a consistent event-name vocabulary") — an
# unrecognized name is dropped rather than silently logged as free text,
# so this stays a small, comparable set instead of accumulating one-offs.
_ALLOWED_EVENTS = frozenset({
    "advisor_evaluated", "view_selected", "exported_png", "exported_csv",
    "saved", "table_view_opened", "render_failed", "engine_fallback",
    "preference_set", "interacted",
})

_ALLOWED_CATEGORIES = frozenset({"chart", "graph", "flow"})


def log_frontend_interaction(
    *,
    event: str,
    category: str,
    visualization_id: str | None = None,
    visualization_type: str | None = None,
    renderer: str | None = None,
    detail: dict | None = None,
) -> bool:
    """Log one structured interaction event. Returns whether it was accepted
    (an unrecognized event/category is dropped, not raised — a malformed
    telemetry call must never be able to break the caller)."""
    if event not in _ALLOWED_EVENTS or category not in _ALLOWED_CATEGORIES:
        return False
    logger.info(json.dumps({
        "event": event,
        "category": category,
        "visualization_id": visualization_id,
        "visualization_type": visualization_type,
        "renderer": renderer,
        "detail": detail or {},
    }, default=str))
    return True
