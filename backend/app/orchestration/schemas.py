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
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Request ──────────────────────────────────────────────────────────────────

class AskKritonRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    jurisdiction: str = ""
    mode: str = "Workflow"
    # Which persisted conversation this turn belongs to (see
    # app/domains/chat_history) — omitted/None starts a new conversation.
    conversation_id: Optional[str] = None
    # Prior user queries in this conversation, most recent last — NOT the
    # composed answers (those carry disclaimer/citation text that has no
    # business re-entering the grounded prompt as "context"). Populated by
    # the frontend from its client-side turn history; empty for a fresh
    # conversation. Used only to resolve elliptical follow-ups ("what about
    # for £20,000 instead") that are unclassifiable in isolation — see
    # orchestration/followup.py's is_elliptical_followup().
    history: List[str] = Field(default_factory=list)
    # Safety simulation overrides (playground only — not trusted in production)
    source_confidence: Optional[str] = None
    pre_bundle_state: Optional[str] = None
    privacy_class: Optional[str] = None
    clarification_cycle: int = Field(default=0, ge=0, le=2)

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain non-whitespace text")
        return value


# ── Retrieval Plan — ZL-ENG-03 §5.1 ──────────────────────────────────────────
# Produced ahead of retrieval to declare strategy/intent; the live keyword_mvp
# retrieval layer (orchestration/retrieve.py) doesn't consume this yet — it's
# the typed shape license_gate.py's Checkpoint A reasons about today, and what
# a future planner module would populate.

RetrievalMethod = Literal["keyword", "vector", "ontology", "citation_anchor", "tenant_private", "hybrid", "live_api"]


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
    # Live external-data addition (app/domains/live_sources/) — defaulted so
    # every existing construction site is unaffected.
    source_type: Literal["document", "live_api"] = "document"


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
    # Live external-data addition, same rationale as SourceSummary.source_type.
    source_type: Literal["document", "live_api"] = "document"
    # Only ever set for source_type="live_api" (a real external URL a user
    # can click through to — e.g. the ONS dataset page, the SEC EDGAR
    # company page). Document sources have no public URL today — there's no
    # file-serving endpoint for uploaded/ingested documents at all, so
    # `file_path` is just an internal server path, not something a browser
    # could fetch. Left None rather than fabricating a broken-looking link.
    source_url: Optional[str] = None
    url: str | None = None
    evidence_preview: str = ""


# ── Calculation widget — governed calculation architecture, interactive
# rendering (2026-07-23, see docs/calculation_architecture.md). Carries a
# governed FormulaResult's inputs/output as structured data so the frontend
# can render live sliders and a chart, instead of only prose. Every value
# here is the same Decimal-as-string convention used everywhere else in the
# calculation domain — never a binary float, and every WidgetInput's
# min/max/step lets the frontend build a slider without guessing sensible
# bounds. Recomputation on a slider change calls back into
# app/domains/calculation/router.py's /recompute endpoint (execute_formula()
# again) rather than duplicating formula math in JavaScript — one verified
# source of truth for the number, same principle Checkpoint C's provenance
# model already depends on.
class WidgetInput(BaseModel):
    name: str
    label: str
    value: str
    unit: str
    min: str
    max: str
    step: str


class ChartPoint(BaseModel):
    x: str
    y: str


class CalculationWidget(BaseModel):
    formula_id: str
    formula_name: str
    formula_display: str
    methodology_reference: str
    inputs: List[WidgetInput] = Field(default_factory=list)
    output_label: str
    output_value: str
    output_unit: str
    chart_label: str = ""
    chart_x_label: str = ""
    chart_y_label: str = ""
    chart_points: List[ChartPoint] = Field(default_factory=list)
    calculation_id: str


class PresentationSeries(BaseModel):
    name: str
    values: List[str] = Field(default_factory=list)


class PresentationMetric(BaseModel):
    """A single headline number derived from a table that reduces to one row
    (e.g. "Total revenue: $482,000") — a chart with one data point isn't a
    chart, it's a stat. No delta/trend in v1: a single row has no second
    point to diff against, so nothing is computed rather than guessed."""
    metric_id: str
    label: str
    value: str
    unit: str = ""


class PresentationChart(BaseModel):
    chart_id: str
    type: Literal["bar", "line", "area", "donut"] = "bar"
    title: str
    categories: List[str] = Field(default_factory=list)
    series: List[PresentationSeries] = Field(default_factory=list)
    unit: str = ""


class PresentationGuide(BaseModel):
    guide_id: str
    type: Literal["process", "timeline", "checklist", "decision_flow"]
    title: str
    items: List[str] = Field(default_factory=list)


class AnswerPresentation(BaseModel):
    layout: Literal["concise", "descriptive", "comparison", "step_by_step", "data_visualization", "calculation"] = "concise"
    table_count: int = 0
    has_steps: bool = False
    charts: List[PresentationChart] = Field(default_factory=list)
    metrics: List[PresentationMetric] = Field(default_factory=list)
    guides: List[PresentationGuide] = Field(default_factory=list)
    sections: List[str] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)


class ComposedAnswer(BaseModel):
    text: str
    citations: List[SourceCitation] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    calculation_widget: Optional[CalculationWidget] = None
    presentation: Optional[AnswerPresentation] = None
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
    # Populated by the orchestration router after ask_kriton() returns (see
    # chat_history.service.resolve_conversation) — never set inside
    # ask_kriton() itself, so none of its many return branches need to know
    # about conversation persistence.
    conversation_id: Optional[str] = None
