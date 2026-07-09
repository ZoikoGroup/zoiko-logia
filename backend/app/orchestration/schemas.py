"""
Ask Kriton orchestration contracts — the envelope that ties retrieve ->
classify -> compose -> audit into one response for the frontend.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from app.domains.risk_safety.schemas import SafetyDecision


class AskKritonRequest(BaseModel):
    query: str
    jurisdiction: str = ""
    mode: str = "Workflow"
    source_confidence: Optional[str] = None
    pre_bundle_state: Optional[str] = None
    privacy_class: Optional[str] = None


class SourceSummary(BaseModel):
    id: str
    title: str
    category: str
    jurisdiction_scope: str
    version_label: str
    status: str


class SourceBundle(BaseModel):
    bundle_id: str
    retrieval_run_id: str
    category: str
    confidence_state: str  # HIGH_CONFIDENCE | LOW_CONFIDENCE | NO_ELIGIBLE_SOURCE
    sources: list[SourceSummary]


class ComposedAnswer(BaseModel):
    prompt_id: str
    prompt_name: str
    output_text: str


class AskKritonResponse(BaseModel):
    query_id: str
    outcome: str  # ANSWERED | REFUSED | HUMAN_REVIEW | CLARIFICATION | COMPOSE_UNAVAILABLE
    safety: SafetyDecision
    source_bundle: SourceBundle
    answer: Optional[ComposedAnswer] = None
