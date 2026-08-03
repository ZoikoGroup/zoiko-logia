"""
Counters for how often the LLM classifier is actually consulted, and whether
it answers.

Why this exists as its own module rather than being read back out of the audit
ledger: the ledger is the durable record and already carries every one of
these facts (`rules_applied`, `understanding.source`), but nothing reads it to
answer the two operational questions that decide whether
RISK_LLM_CLASSIFIER_MODE should stay on:

  1. Is the provider answering, or silently failing on every request?
  2. Is the query-understanding budget buying anything, or timing out?

Both were unanswerable, which meant the classifier could be enabled and
degrade to deterministic behaviour indefinitely with no signal — the same
failure shape as a source that stops updating while still returning HTTP 200.

Deliberately process-local and reset by a restart. These are a live gauge, not
an audit trail; the ledger remains the record of what happened to any
individual query. Counters over durations on purpose: latency is already
recorded per query in `understanding.latency_ms`, and a mean here would hide
the tail that actually matters.
"""
from __future__ import annotations

import threading
from typing import Literal

# What became of a risk classification. The distinction that matters is
# "never asked" vs "asked and got nothing" — the first is normal in fallback
# mode, the second means the provider is down.
ClassificationOutcome = Literal[
    "deterministic",          # a deterministic label settled it; no call made
    "llm_applied",            # LLM answered and its verdict was used
    "llm_unavailable",        # LLM was called and returned nothing
    "llm_skipped_sensitive",  # privacy class forbade an external call
    "local_model",            # the local ML pipeline settled it
]

# What became of a query-understanding attempt. Three ways to end up on the
# deterministic path, and they mean completely different things:
UnderstandingOutcome = Literal[
    "not_consulted",     # confident deterministic result, or mode is off
    "semantic_applied",  # the remote result was used
    "timed_out",         # asked, and the budget expired first
    "provider_failed",   # asked, and the provider returned nothing
]

_lock = threading.Lock()
_classification: dict[str, int] = {}
_understanding: dict[str, int] = {}


def record_classification(outcome: ClassificationOutcome) -> None:
    # Called from a worker thread (orchestration dispatches
    # classify_after_bundle through asyncio.to_thread), so the lock is load
    # bearing, not decorative.
    with _lock:
        _classification[outcome] = _classification.get(outcome, 0) + 1


def record_understanding(outcome: UnderstandingOutcome) -> None:
    with _lock:
        _understanding[outcome] = _understanding.get(outcome, 0) + 1


def reset() -> None:
    with _lock:
        _classification.clear()
        _understanding.clear()


def _rate(numerator: int, denominator: int) -> float | None:
    # None rather than 0.0 when nothing has happened yet: a 0% success rate
    # and "no requests" are different states, and reporting the first for the
    # second is how a healthy deployment looks broken on its first minute.
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def snapshot() -> dict:
    with _lock:
        classification = dict(_classification)
        understanding = dict(_understanding)

    attempted = classification.get("llm_applied", 0) + classification.get("llm_unavailable", 0)
    consulted = (
        understanding.get("semantic_applied", 0)
        + understanding.get("timed_out", 0)
        + understanding.get("provider_failed", 0)
    )
    return {
        "classification": {
            "counts": classification,
            "total": sum(classification.values()),
            # Of the calls actually made, how many came back. A low value here
            # with a non-zero total is the signal to check the key, the model
            # name, or the provider.
            "llm_answer_rate": _rate(classification.get("llm_applied", 0), attempted),
        },
        "query_understanding": {
            "counts": understanding,
            "total": sum(understanding.values()),
            # Of the calls actually made, how many landed inside the budget.
            # A low value means QUERY_UNDERSTANDING_REMOTE_TIMEOUT_SECONDS is
            # too tight for the configured model — the request is not wasted
            # (its result still warms the classifier cache) but the rewrite
            # never arrives.
            "within_budget_rate": _rate(understanding.get("semantic_applied", 0), consulted),
        },
        "note": (
            "Process-local counters, reset on restart. The audit ledger remains "
            "the durable per-query record."
        ),
    }
