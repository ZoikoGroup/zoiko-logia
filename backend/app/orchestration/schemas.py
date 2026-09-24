"""
Ask Kriton™ orchestration contracts — ZL-ENG-02 v1.0 §12 canonical response contract,
extended per ZL-ENG-03 §5 to also serve as the canonical schemas.py for the Massarius™
retrieval and evidence subsystem (app/domains/massarius/). Every Massarius™ module
imports its shared shapes from here rather than defining local variants (ZL-ENG-03
Gate 1) — massarius/schemas.py re-exports these types rather than redefining them,
since this file already anchors the live AskKritonResponse contract.
"""
from __future__ import annotations
from datetime import date
from typing import Literal, Optional, List
from pydantic import BaseModel, ConfigDict, Field
from app.domains.calculations.schemas import CalculationResult, LiveObservation, VerifiedChartSpec


# ── F0 task context ─────────────────────────────────────────────────────────

TaskType = Literal[
    "general_question",
    "policy_research",
    "document_evidence_extraction",
    "reconciliation",
]


class TaskContextSelection(BaseModel):
    """User selections only. Trusted identity/scope is never accepted here."""

    model_config = ConfigDict(extra="forbid")

    # None means automatic detection. Clients may still provide an explicit
    # override, but the normal path requires no workflow label.
    task_type: Optional[TaskType] = None
    engagement_id: Optional[str] = None
    purpose: Optional[str] = None
    jurisdiction: Optional[str] = None
    framework: Optional[str] = None
    entity: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    currency: Optional[str] = None
    language: str = "en"
    intended_use: Literal["research", "draft_workpaper", "internal_review"] = "research"


class TaskContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    task_type: TaskType
    task_spec_version: str
    actor_id: str
    tenant_id: str
    actor_role: str
    engagement_id: Optional[str] = None
    purpose: str
    jurisdiction: Optional[str] = None
    framework: Optional[str] = None
    entity: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    currency: Optional[str] = None
    language: str
    data_classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    intended_use: Literal["research", "draft_workpaper", "internal_review"]


class TaskSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_type: TaskType
    version: str
    required_fields: List[str]
    allowed_outputs: List[str]
    prohibited_actions: List[str]
    review_role: Optional[str] = None


class ContextDecision(BaseModel):
    status: Literal["complete", "clarification_required", "unsupported", "unauthorized"]
    missing_fields: List[str] = Field(default_factory=list)
    invalid_fields: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)
    clarification_questions: List[str] = Field(default_factory=list)
    resolved_context: Optional[TaskContext] = None


CapabilityId = Literal[
    "document.retrieve",
    "document.extract",
    "source.research",
    "policy.lookup",
    "numeric.calculate",
    "numeric.compare",
    "evidence.cite",
    "chart.generate",
    "response.compose",
]


class CapabilityStep(BaseModel):
    capability: CapabilityId
    reason: str


class WorkflowPlan(BaseModel):
    """A bounded, auditable plan. It can select registered capabilities only."""

    model_config = ConfigDict(frozen=True)

    version: Literal["1.0"] = "1.0"
    task_type: TaskType
    detection: Literal["automatic", "explicit_override"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason_codes: List[str] = Field(default_factory=list)
    steps: List[CapabilityStep] = Field(default_factory=list)


# ── Request ──────────────────────────────────────────────────────────────────

class AskKritonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    # Documents the user attached to this turn (app/domains/documents). Ids
    # only: ownership and readiness are re-verified server-side against the
    # caller's identity, because the client is not an authority on either.
    document_ids: List[str] = Field(default_factory=list)
    # Safety simulation overrides (playground only — not trusted in production)
    source_confidence: Optional[str] = None
    pre_bundle_state: Optional[str] = None
    privacy_class: Optional[str] = None
    # Additive F0 contract. Omitted by legacy clients, which remain on the
    # general-question workflow until they deliberately select a pilot task.
    task_context: Optional[TaskContextSelection] = None


# ── Retrieval Plan — ZL-ENG-03 §5.1 ──────────────────────────────────────────
# Produced and consumed by orchestration/retrieve.py before passage retrieval;
# it fixes the strategy, context, top-k and index version for replay.

RetrievalMethod = Literal["keyword", "vector", "ontology", "citation_anchor", "tenant_private", "hybrid"]


class RetrievalPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    retrieval_plan_id: str
    version: Literal["1.0"] = "1.0"
    strategy: str
    methods: List[RetrievalMethod] = Field(default_factory=list)
    jurisdiction: str = ""
    framework: str = ""
    requires_tenant_private_sources: bool = False
    requires_current_sources: bool = False
    top_k: int = Field(default=8, ge=1, le=50)
    index_version: str = "source-passages-lexical-v1"
    risk_notes: List[str] = Field(default_factory=list)


# ── Source Candidate — ZL-ENG-03 §5.2 ────────────────────────────────────────
# One retrieval hit, pre-bundle. EvidencePassage below is the immutable selected
# form recorded in the final bundle.

class SourceCandidate(BaseModel):
    source_id: str
    passage_ref: str = ""
    score: float = 0.0
    method: RetrievalMethod = "keyword"
    index_version: str = "v1"


class EvidencePassage(BaseModel):
    """Safe passage identity included in an API response; content stays server-side."""

    model_config = ConfigDict(frozen=True)

    passage_id: str
    source_id: str
    source_version_id: str
    locator: str
    content_hash: str
    score: float = 0.0
    rank: int = 0
    method: RetrievalMethod = "keyword"


class ExcludedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    source_version_id: Optional[str] = None
    passage_id: Optional[str] = None
    reason_code: str


# ── Source Bundle — ZL-ENG-02 §7.2, ZL-ENG-03 §5.5 ───────────────────────────
# Canonical, immutable evidence object. Built only by
# app/domains/massarius/bundle_builder.py — frozen so nothing downstream
# (including context_fit.py in a later phase) can mutate it after construction;
# adjustments must be recorded as separate audit-linked data instead.

class SourceSummary(BaseModel):
    id: str
    version_id: str = ""
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
    retrieval_plan: Optional[RetrievalPlan] = None
    passages: List[EvidencePassage] = Field(default_factory=list)
    excluded_evidence: List[ExcludedEvidence] = Field(default_factory=list)
    conflict_version_ids: List[str] = Field(default_factory=list)
    manifest_version: Literal["1.0"] = "1.0"


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
    chart_type: Literal["line", "bar", "donut", "gauge", "waterfall", "stacked_bar", "bullet", "treemap", "sankey", "kpi"]
    chart_label: str
    chart_x_label: str
    chart_y_label: str
    chart_points: List[ChartPoint] = Field(default_factory=list)
    calculation_id: str


class ComposedAnswer(BaseModel):
    text: str
    citations: List[SourceCitation] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    calculation_widget: Optional[CalculationWidget] = None
    calculation_result: Optional[CalculationResult] = None
    verified_charts: List[VerifiedChartSpec] = Field(default_factory=list)
    observations: List[LiveObservation] = Field(default_factory=list)
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
    effective_context: Optional[TaskContext] = None
    context_decision: Optional[ContextDecision] = None
    workflow_plan: Optional[WorkflowPlan] = None
    audit_reference: AuditReference
