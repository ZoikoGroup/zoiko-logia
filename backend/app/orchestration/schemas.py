"""
Ask Kriton™ orchestration contracts — ZL-ENG-02 v1.0 §12 canonical response contract,
extended per ZL-ENG-03 §5 to also serve as the canonical schemas.py for the Massarius™
retrieval and evidence subsystem (app/domains/massarius/). Every Massarius™ module
imports its shared shapes from here rather than defining local variants (ZL-ENG-03
Gate 1) — massarius/schemas.py re-exports these types rather than redefining them,
since this file already anchors the live AskKritonResponse contract.
"""
from __future__ import annotations
from typing import Literal, Optional, List
from pydantic import BaseModel, ConfigDict, Field

from app.orchestration.visualization.spec import VisualizationSpec


# ── Request ──────────────────────────────────────────────────────────────────

class AskKritonRequest(BaseModel):
    query: str
    jurisdiction: str = ""
    mode: str = "Workflow"
    # Round-tripped by the client across a clarification exchange so
    # resolve_policy() can escalate instead of looping forever on a query that
    # keeps coming back "needs clarification".
    clarification_cycle: int = 0
    # Client-generated — scopes audit correlation to one chat thread. Not yet
    # used for any server-side conversation memory.
    conversation_id: Optional[str] = None
    # Safety simulation overrides (playground only — not trusted in production)
    source_confidence: Optional[str] = None
    pre_bundle_state: Optional[str] = None
    privacy_class: Optional[str] = None


# ── Retrieval Plan — ZL-ENG-03 §5.1 ──────────────────────────────────────────
# Produced ahead of retrieval to declare strategy/intent; the live keyword_mvp
# retrieval layer (orchestration/retrieve.py) doesn't consume this yet — it's
# the typed shape license_gate.py's Checkpoint A reasons about today, and what
# a future planner module would populate.

RetrievalMethod = Literal["keyword", "vector", "ontology", "citation_anchor", "tenant_private", "hybrid"]


class RetrievalPlan(BaseModel):
    retrieval_plan_id: str
    strategy: str
    methods: List[RetrievalMethod] = Field(default_factory=list)
    jurisdiction: str = ""
    framework: str = ""
    requires_tenant_private_sources: bool = False
    requires_current_sources: bool = False
    risk_notes: List[str] = Field(default_factory=list)


# ── Source Candidate — ZL-ENG-03 §5.2 ────────────────────────────────────────
# One retrieval hit, pre-bundle. keyword_mvp retrieval today produces
# SourceSummary directly; SourceCandidate is the richer shape license_gate.py
# and bundle_builder.py operate on once a candidate needs passage/score detail.

class SourceCandidate(BaseModel):
    source_id: str
    passage_ref: str = ""
    score: float = 0.0
    method: RetrievalMethod = "keyword"
    index_version: str = "v1"


# ── Source Bundle — ZL-ENG-02 §7.2, ZL-ENG-03 §5.5 ───────────────────────────
# Canonical, immutable evidence object. Built only by
# app/domains/massarius/bundle_builder.py — frozen so nothing downstream
# (including context_fit.py in a later phase) can mutate it after construction;
# adjustments must be recorded as separate audit-linked data instead.

class SourceSummary(BaseModel):
    id: str
    title: str
    category: str
    jurisdiction_scope: str
    version_label: str
    status: str


SourceDisplayState = Literal["show", "summarise", "internal_reasoning_only"]


class SourceBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    # ZL-ENG-03 additions — per-source exposure resolution (Checkpoint B) and
    # the retrieval index version this bundle was built against.
    source_display_states: dict[str, SourceDisplayState] = Field(default_factory=dict)
    index_version: str = "v1"


# ── Citation Map — ZL-ENG-03 §5.4 ────────────────────────────────────────────
# claim -> passage -> citation binding, used by answer_validator.py's citation
# and grounding checks.

class CitationBinding(BaseModel):
    claim_text: str
    passage_ref: str
    citation_id: str
    source_id: str


class CitationMap(BaseModel):
    bindings: List[CitationBinding] = Field(default_factory=list)

    def citation_ids(self) -> set[str]:
        return {b.citation_id for b in self.bindings}


# ── Validation Result — ZL-ENG-03 §5.6, Checkpoint C ─────────────────────────
# Canonical shared shape (composition_validator.py's local ValidationResult
# predates this and is being superseded by massarius/answer_validator.py,
# which returns this type).

class ValidationResult(BaseModel):
    passed: bool
    failures: List[str] = Field(default_factory=list)
    degraded_route: Optional[str] = None   # route to use if failed


# ── Redaction Report — ZL-ENG-03 §5.7 (Phase 3 dependency, schema defined now)
# redaction.py itself is out of scope for Phase 1 (still an unbuilt Phase 3
# module in app/domains/rag/) — this shape exists so bundle_builder.py and
# errors.py can reference it without a forward-reference hack later.

class RedactionReport(BaseModel):
    redacted: bool = False
    fields_redacted: List[str] = Field(default_factory=list)
    reason: Optional[str] = None


# ── Answer — §12 ─────────────────────────────────────────────────────────────

class SourceCitation(BaseModel):
    ref_id: str
    source_id: str
    title: str
    # Public URL the answer was grounded in (web-search sources) — the
    # frontend renders this as a clickable link. None for internal/governed
    # sources with no public URL.
    url: Optional[str] = None
    # The actual retrieved snippet this citation was grounded in (WebSource.snippet)
    # — not a fabricated summary. None for sources with no snippet text.
    evidence_preview: Optional[str] = None
    # Provenance for sources that know their own origin and currency (market
    # and company data). None for a plain web-search hit, which has neither a
    # named provider nor a meaningful freshness class.
    provider: Optional[str] = None
    fetched_at: Optional[str] = None
    freshness: Optional[str] = None   # realtime | delayed | historical | filing


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
    risk_level: str                          # ZERO | LOW | MEDIUM | HIGH | RESTRICTED
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
    # Additive field — deterministic, evidence-backed visualization decided by
    # orchestration/visualization/orchestrator.py. Only ever set on "answered"
    # outcomes, after safety/validation has already approved the text answer
    # (see service.py) — never a substitute for or bypass of that gate. None
    # on every response this pipeline can't back with real (non-fabricated)
    # evidence; existing clients that don't read this field are unaffected.
    visualization: Optional[VisualizationSpec] = None
    # Complementary visuals (spec §17) — a genuinely different lens on the
    # SAME evidence as `visualization` (e.g. current-value KPI alongside a
    # trend line), never a redundant alternate chart type. Empty list when
    # none apply; each entry independently validated before being attached
    # (see orchestrator.py's _build_complementary_specs docstring).
    secondary_visualizations: List[VisualizationSpec] = Field(default_factory=list)


# ── Frontend visualization-interaction telemetry ─────────────────────────────

class VisualizationTelemetryEvent(BaseModel):
    event: str
    category: str
    visualization_id: Optional[str] = None
    visualization_type: Optional[str] = None
    renderer: Optional[str] = None
    detail: dict = Field(default_factory=dict)
