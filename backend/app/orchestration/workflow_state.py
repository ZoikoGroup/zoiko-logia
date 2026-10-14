"""Explicit request workflow states (ZL-ENG-AGT-01 §05.2, App. B4).

# PROPOSED — reconcile with ZL-T0-13 (Event Catalog). The catalog defines the
# events a request emits but no request-level state names; these are the
# directive's names. The state is derived from the audit events the pipeline
# already emits in order, so every transition has a durable audit record
# behind it and ask_kriton needs no separate bookkeeping.

States, in order:
    received → checked → evidence_ready ⇄ tool_running → verifying
             → awaiting_review → released | failed | cancelled

Later stages may be skipped (a clarification goes from checked to released).
evidence_ready and tool_running may alternate, because the agent's
knowledge-base tool retrieves evidence during the tool loop. Any other move
backwards is recorded as an invalid transition (never raised: the request
must still finish safely) and appears in the workflow_completed audit event.
"""
from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum


class WorkflowState(str, Enum):
    RECEIVED = "received"
    CHECKED = "checked"
    EVIDENCE_READY = "evidence_ready"
    TOOL_RUNNING = "tool_running"
    VERIFYING = "verifying"
    AWAITING_REVIEW = "awaiting_review"
    RELEASED = "released"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = frozenset({WorkflowState.RELEASED, WorkflowState.FAILED, WorkflowState.CANCELLED})

_RANK = {
    WorkflowState.RECEIVED: 0, WorkflowState.CHECKED: 1,
    WorkflowState.EVIDENCE_READY: 2, WorkflowState.TOOL_RUNNING: 2,
    WorkflowState.VERIFYING: 3, WorkflowState.AWAITING_REVIEW: 4,
}

# Audit event → the state it shows the request has reached.
EVENT_STATES: dict[str, WorkflowState] = {
    "query_received": WorkflowState.RECEIVED,
    "request_validated": WorkflowState.RECEIVED,
    "context_resolved": WorkflowState.CHECKED,
    "prescreen_completed": WorkflowState.CHECKED,
    "risk_classified": WorkflowState.CHECKED,
    "route_selected": WorkflowState.CHECKED,
    "retrieval_completed": WorkflowState.EVIDENCE_READY,
    "bundle_built": WorkflowState.EVIDENCE_READY,
    "agent_tool_called": WorkflowState.TOOL_RUNNING,
    "calculation_completed": WorkflowState.TOOL_RUNNING,
    "validation_completed": WorkflowState.VERIFYING,
    "release_check_completed": WorkflowState.VERIFYING,
    "release_check_degraded": WorkflowState.VERIFYING,
    "human_review_created": WorkflowState.AWAITING_REVIEW,
    "request_rejected": WorkflowState.FAILED,
}


@dataclass
class WorkflowRun:
    state: WorkflowState = WorkflowState.RECEIVED
    path: list[str] = field(default_factory=lambda: [WorkflowState.RECEIVED.value])
    invalid: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)
    # Calculation receipts produced during the run (for the answer receipt).
    calculation_ids: list[str] = field(default_factory=list)
    # {ref_id: [{"start", "end", "overlap"}]} — exact supporting text per citation.
    citation_spans: dict = field(default_factory=dict)

    def advance(self, target: WorkflowState) -> None:
        if target == self.state:
            return
        if self.state in TERMINAL:
            self.invalid.append(f"{self.state.value}->{target.value}")
            return
        if target not in TERMINAL and _RANK[target] < _RANK[self.state]:
            self.invalid.append(f"{self.state.value}->{target.value}")
            return
        self.state = target
        self.path.append(target.value)

    def observe(self, event_name: str) -> None:
        target = EVENT_STATES.get(event_name)
        if target is not None:
            self.advance(target)

    def finish(self, *, released: bool) -> WorkflowState:
        """Terminal state for a request that returned a response. A response
        that went to review stays awaiting_review: it was not released."""
        if self.state == WorkflowState.AWAITING_REVIEW:
            return self.state
        self.advance(WorkflowState.RELEASED if released else WorkflowState.FAILED)
        return self.state

    def summary(self) -> dict:
        return {"final_state": self.state.value, "path": list(self.path),
                "invalid_transitions": list(self.invalid),
                "duration_ms": int((time.monotonic() - self.started) * 1000)}


current_run: ContextVar[WorkflowRun | None] = ContextVar("kriton_workflow_run", default=None)


def note_calculation(calculation_id: str) -> None:
    run = current_run.get()
    if run is not None and calculation_id:
        run.calculation_ids.append(calculation_id)


def note_citation_spans(spans: dict) -> None:
    run = current_run.get()
    if run is not None:
        run.citation_spans = spans


def observe(event_name: str) -> None:
    run = current_run.get()
    if run is not None:
        run.observe(event_name)
