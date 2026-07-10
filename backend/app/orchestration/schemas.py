"""
Ask Kriton™ orchestration contracts — ZL-ENG-02 v1.0 §12 canonical response contract.
The frontend renders from route and outcome fields only; it must not parse answer text.
"""
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field


# ── Request ──────────────────────────────────────────────────────────────────

class AskKritonRequest(BaseModel):
    query: str
    jurisdiction: str = ""
    mode: str = "Workflow"
    # Safety simulation overrides (playground only — not trusted in production)
    source_confidence: Optional[str] = None
    pre_bundle_state: Optional[str] = None
    privacy_class: Optional[str] = None


# ── Source Bundle — §7.2 ─────────────────────────────────────────────────────

class SourceSummary(BaseModel):
    id: str
    title: str
    category: str
    jurisdiction_scope: str
    version_label: str
    status: str


class SourceBundle(BaseModel):
    source_bundle_id: str
    retrieval_method: str = "keyword_mvp"          # §7 — "RAG" label prohibited until §7 criteria met
    eligible_source_count: int = 0
    excluded_source_count: int = 0
    sources: List[SourceSummary] = Field(default_factory=list)
    exclusion_reasons: List[str] = Field(default_factory=list)
    jurisdiction: str = ""
    authority_level: str = "secondary"             # primary | secondary | internal
    freshness_state: str = "unknown"               # current | stale | unknown
    licence_state: str = "unknown"                 # permitted | restricted | unknown
    confidence_state: str = "insufficient"         # sufficient | limited | insufficient |
                                                   # conflicting_sources | stale_sources | restricted_sources


# ── Answer — §12 ─────────────────────────────────────────────────────────────

class SourceCitation(BaseModel):
    ref_id: str
    source_id: str
    title: str


class ComposedAnswer(BaseModel):
    text: str
    citations: List[SourceCitation] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    # Internal fields — kept for model_gateway wiring; never exposed to frontend
    prompt_id: str = "inline"
    prompt_name: str = "Inline RAG Prompt"
    output_text: str = ""  # alias for text, retained for backward compat


# ── Safety State — §12 ───────────────────────────────────────────────────────

class SafetyState(BaseModel):
    risk_level: str                          # LOW | MEDIUM | HIGH | RESTRICTED
    policy_state: str                        # allowed | blocked | needs_more_context
    disclaimer_required: bool = False


# ── Next Action — §12 clarification example ──────────────────────────────────

class NextAction(BaseModel):
    type: str                                # ask_clarifying_question | escalate | ...
    message: str


# ── Audit Reference — §12 (opaque — never expose internal hashes) ─────────────

class AuditReference(BaseModel):
    audit_chain_id: str


# ── Canonical Response Contract — §12 ────────────────────────────────────────

class AskKritonResponse(BaseModel):
    query_id: str
    correlation_id: str
    outcome: str       # answered | refused | clarification_required | escalated | rejected
    route: str         # LLM | REFUSAL | CLARIFICATION | HUMAN_REVIEW | SECURITY_INCIDENT | REJECTED
    safety: SafetyState
    confidence_state: str
    source_bundle: Optional[SourceBundle] = None
    answer: Optional[ComposedAnswer] = None
    next_action: Optional[NextAction] = None
    audit_reference: AuditReference
