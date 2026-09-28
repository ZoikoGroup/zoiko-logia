"""
Shadow-mode comparison logging for the semantic query classifier
(migration Phase 4).

Runs classify_query() ALONGSIDE the existing regex-based pipeline for real
requests, entirely in the background — this module is fire-and-forget by
design and NEVER awaited by the request path. A slow, rate-limited, or
failing Groq call here can add zero latency and cause zero failures for a
real user request; the whole point of shadow mode is that it must be
impossible for this to affect production behavior at all.

Logs old-vs-new agreement so real traffic becomes an evaluation dataset
before classify_query() is trusted with actual routing decisions (a later,
separate migration phase this module does not perform).
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.orchestration.query_classifier import classify_query

logger = logging.getLogger("kriton.query_classifier.shadow")

# asyncio.create_task() only holds a WEAK reference via the running loop —
# without something else keeping the Task object alive, it can be garbage
# collected mid-flight (a well-known asyncio gotcha), silently dropping the
# shadow comparison. This set is that "something else"; entries remove
# themselves via the done-callback once finished.
_inflight: set[asyncio.Task] = set()


async def _compare_and_log(
    query: str, *, query_id: str, old_intent: str | None, old_wants_visualization: bool,
) -> None:
    started = time.monotonic()
    try:
        new_intent = await classify_query(query)
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        logger.info(
            "query_classifier_shadow",
            extra={
                "query_id": query_id,
                "semantic_classifier_success": True,
                "semantic_classifier_latency_ms": latency_ms,
                "fallback_used": new_intent.source == "fallback",
                "domain": new_intent.domain,
                "intent": new_intent.intent,
                "confidence": new_intent.confidence,
                "ambiguous": new_intent.ambiguous,
                "out_of_scope": new_intent.out_of_scope,
                "wants_visualization": new_intent.wants_visualization,
                "old_intent": old_intent,
                "old_wants_visualization": old_wants_visualization,
                "intent_agreement": old_intent == new_intent.intent,
                "visualization_agreement": old_wants_visualization == new_intent.wants_visualization,
            },
        )
    except Exception:
        # Shadow mode must never surface an error anywhere a real request
        # could observe it — this coroutine isn't awaited by the caller, so
        # an uncaught exception here would only ever become an "Exception in
        # callback" line in the server log, never a failed response. Still
        # caught explicitly and logged as a normal failure metric rather
        # than left to asyncio's default (noisier, less structured) handling.
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        logger.warning(
            "query_classifier_shadow_failed",
            extra={"query_id": query_id, "semantic_classifier_success": False,
                   "semantic_classifier_latency_ms": latency_ms},
        )


def log_shadow_comparison(
    query: str, *, query_id: str, old_intent: str | None, old_wants_visualization: bool,
) -> None:
    """Fire the shadow comparison in the background and return immediately.
    Never awaited, never raises into the caller."""
    task = asyncio.create_task(
        _compare_and_log(
            query, query_id=query_id, old_intent=old_intent,
            old_wants_visualization=old_wants_visualization,
        )
    )
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)
