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
    # Safety simulation overrides (playground only — not trusted in production)
    source_confidence: Optional[str] = None
    pre_bundle_state: Optional[str] = None
    privacy_class: Optional[str] = None
    clarification_cycle: int = Field(default=0, ge=0, le=2)
    # Dynamic Visualization Selection v4 — a client-generated identifier for
    # the current chat thread (already exists client-side, see
    # frontend/app/ask-kriton/page.tsx's activeConversationId; v4 is the
    # first time it's sent to the backend). Used only to scope the
    # visualization-repetition penalty and telemetry to the current
    # conversation — never trusted for authorization, and optional so older
    # clients keep working unchanged.
    conversation_id: Optional[str] = Field(default=None, max_length=200)

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain non-whitespace text")
        return value


# ── Visualization telemetry — v4 (client-originated events only) ────────────
# visualization_selected / alternative_views_shown / visualization_fallback_used
# are backend-only, emitted automatically at answer-generation time
# (orchestration/service.py) — deliberately not in this Literal, so a client
# can never post a fabricated "visualization_selected" event to manipulate
# its own recent_chart_types repetition history.

class VisualizationTelemetryRequest(BaseModel):
    event_name: Literal[
        "alternative_view_selected", "visualization_exported_png", "visualization_exported_csv",
        "visualization_saved", "visualization_render_failed",
        # v10 — "View as table" opened; a permitted personalization signal
        # (see visualization_personalization.py's PERSONALIZATION SIGNALS
        # allow-list). Purely a UI-interaction marker, no table content.
        "table_view_opened",
    ]
    conversation_id: Optional[str] = Field(default=None, max_length=200)
    query_id: Optional[str] = Field(default=None, max_length=200)
    analytical_intent: Optional[str] = Field(default=None, max_length=100)
    original_chart_type: Optional[str] = Field(default=None, max_length=100)
    active_chart_type: Optional[str] = Field(default=None, max_length=100)
    alternative_count: Optional[int] = Field(default=None, ge=0, le=3)
    selection_source: Optional[Literal[
        "deterministic_default", "explicit_user_request", "alternative_switch", "safe_fallback", "legacy_payload", "personalized",
    ]] = None
    renderer: Optional[str] = Field(default=None, max_length=50)
    schema_version: Optional[str] = Field(default=None, max_length=20)
    chart_family: Optional[str] = Field(default=None, max_length=50)
    ranking_version: Optional[str] = Field(default=None, max_length=50)
    experiment_id: Optional[str] = Field(default=None, max_length=100)
    experiment_group: Optional[Literal["control", "variant"]] = None


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
    # "document" (a source_library.Source row) | "live_api" (a live_sources
    # provider response). license_gate.check_eligibility() routes on this:
    # document sources are licence-checked against source_library.Source,
    # live ones against the LiveSourceProvider registry — same eligibility
    # vocabulary, different table.
    #
    # Defaults to "document" so every existing producer keeps its previous
    # behaviour; live_sources.service.to_source_summary() is the only place
    # that sets "live_api". Without the field declared here Pydantic
    # silently dropped that keyword argument, so the attribute never
    # existed and Checkpoint A raised AttributeError on the first query
    # that retrieved anything at all.
    source_type: str = "document"


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
    chart_type: Literal["line", "bar", "donut", "gauge", "waterfall", "stacked_bar", "bullet", "treemap", "sankey", "kpi"] = "line"
    chart_label: str = ""
    chart_x_label: str = ""
    chart_y_label: str = ""
    chart_points: List[ChartPoint] = Field(default_factory=list)
    calculation_id: str


class PresentationSeries(BaseModel):
    name: str
    values: List[str] = Field(default_factory=list)
    unit: str = ""


class VisualizationLayer(BaseModel):
    mark: Literal["bar", "line", "area", "point"]
    series_index: int = Field(ge=0, le=15)
    axis: Literal["primary", "secondary"] = "primary"
    stack: str | None = Field(default=None, max_length=40)


class VisualizationGrammar(BaseModel):
    """Closed declarative grammar; contains references, never code or data."""

    version: Literal["1.0"] = "1.0"
    renderer: Literal["echarts"] = "echarts"
    composition: Literal["layer", "facet"]
    layers: List[VisualizationLayer] = Field(min_length=1, max_length=16)
    facet_columns: int | None = Field(default=None, ge=1, le=4)
    fallback_chart_type: PresentationChartType | None = None


PresentationChartType = Literal[
    "bar", "line", "area", "donut", "dual_axis",
    # Dynamic Visualization Selection v1 — see
    # app/orchestration/presentation_dataprofile.py.
    "grouped_bar", "stacked_bar", "percentage_stacked_bar", "diverging_bar", "histogram", "box_plot", "radar",
    "funnel", "slope",
    # v2 — correlation and financial_movement intents.
    "scatter", "bubble", "heatmap", "correlation_matrix", "dumbbell", "lollipop", "bullet", "waterfall",
    # v5 — temporal/composition brought into the candidate system.
    "composition_bar",
]


class PresentationChart(BaseModel):
    chart_id: str
    type: PresentationChartType = "bar"
    title: str
    categories: List[str] = Field(default_factory=list)
    series: List[PresentationSeries] = Field(default_factory=list)
    unit: str = ""
    domain: Literal["general", "accounting", "audit", "tax"] = "general"
    summary_mode: Literal["latest", "total", "average"] = "total"
    # Dynamic Visualization Selection v3 — see
    # presentation_dataprofile.select_chart_with_alternatives. All optional
    # and defaulted so a v1/v2 payload (missing these fields entirely, live
    # or previously saved) still validates and renders unchanged; a chart
    # outside the ranked-alternatives system (temporal, single-measure
    # composition) simply carries empty/None values here, same as before.
    alternatives: List[PresentationChartType] = Field(default_factory=list)
    original_chart_type: PresentationChartType | None = None
    fallback_note: str | None = None
    schema_version: str = "1.0"
    # Dynamic Visualization Selection v4 — diagnostic/telemetry metadata,
    # not used for rendering. analytical_intent lets the frontend report it
    # without re-deriving it; selection_source records why THIS chart_type
    # was chosen (see presentation_dataprofile.SelectionSource) at the time
    # the backend built this payload — the frontend updates its own copy to
    # "alternative_switch" locally when the user picks a different view, and
    # to "legacy_payload" when rendering a v1/v2 payload missing this field.
    analytical_intent: str | None = None
    selection_source: Literal[
        "deterministic_default", "explicit_user_request", "alternative_switch", "safe_fallback", "legacy_payload", "personalized",
    ] | None = None
    # Dynamic Visualization Selection v7 — diagnostic/telemetry metadata
    # only, same posture as analytical_intent/selection_source above. Set
    # only when a RankingExperiment matched this chart's own intent/family
    # and a deterministic conversation-level assignment placed it in that
    # experiment; ranking_version reflects whichever arm (control/variant)
    # actually scored this chart's alternatives, defaulting to the global
    # production RANKING_VERSION when no experiment applies.
    experiment_id: str | None = None
    experiment_group: Literal["control", "variant"] | None = None
    ranking_version: str | None = None
    preference_affected_selection: bool = False
    # Dynamic Visualization Selection v10 — diagnostic/telemetry metadata
    # only, same posture as preference_affected_selection above. All
    # default to inert/off so a v1-v9 payload (missing these fields
    # entirely, live or previously saved) still validates and renders
    # unchanged. personalization_affected_selection is true only when a
    # consent-based signal actually won a near-tie break on THIS chart —
    # never when an explicit request or saved preference decided it, and
    # never merely because the caller has personalization enabled.
    personalization_enabled: bool = False
    personalization_affected_selection: bool = False
    personalization_model_version: str | None = None
    personalization_confidence_band: Literal["low", "medium", "high"] | None = None
    preferred_output: Literal["auto", "chart", "table"] = "auto"
    visual_density: Literal["compact", "standard", "detailed"] = "standard"
    contrast_preference: Literal["system", "standard", "high"] = "system"
    reduced_motion: bool = False
    table_alternative_default_open: bool = False
    label_orientation: Literal["auto", "horizontal", "vertical"] = "auto"
    grammar: VisualizationGrammar | None = None


class PresentationFlowPosition(BaseModel):
    x: float
    y: float


class PresentationFlowNode(BaseModel):
    id: str = Field(max_length=100)
    position: PresentationFlowPosition
    label: str = Field(max_length=300)


class PresentationFlowEdge(BaseModel):
    id: str = Field(max_length=100)
    source: str = Field(max_length=100)
    target: str = Field(max_length=100)


class PresentationGuide(BaseModel):
    guide_id: str
    type: Literal["process", "timeline", "checklist", "decision_flow", "sequence"]
    title: str
    items: List[str] = Field(default_factory=list)
    domain: Literal["general", "accounting", "audit", "tax"] = "general"
    renderer: Literal["html", "mermaid", "react_flow"] = "html"
    editable: bool = False
    # Populated only after a user edits a React Flow workflow. Keeping this
    # state in the governed guide schema lets save/reload preserve layout and
    # connections while ordinary generated guides remain compact.
    flow_nodes: List[PresentationFlowNode] = Field(default_factory=list)
    flow_edges: List[PresentationFlowEdge] = Field(default_factory=list)


GraphEntityType = Literal[
    "invoice", "supplier", "purchase_order", "receipt", "payment",
    "bank_transaction", "ledger_entry", "contract", "approval", "user",
    "source_document", "audit_evidence",
]
GraphRelationshipType = Literal[
    "issued_by", "belongs_to", "references", "approved_by", "paid_by",
    "matched_to", "recorded_as", "supported_by", "derived_from", "reconciled_with",
]


class GraphNode(BaseModel):
    id: str
    label: str
    entity_type: GraphEntityType
    status: str = ""
    source_reference: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship_type: GraphRelationshipType
    label: str = ""
    direction: Literal["directed", "bidirectional"] = "directed"


class PresentationGraph(BaseModel):
    graph_id: str
    title: str
    summary: str
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    layout: Literal["breadthfirst", "cose", "concentric"] = "cose"
    confidence: float = 1.0


class AnswerPresentation(BaseModel):
    layout: Literal["concise", "descriptive", "comparison", "step_by_step", "data_visualization", "calculation"] = "concise"
    table_count: int = 0
    has_steps: bool = False
    charts: List[PresentationChart] = Field(default_factory=list)
    guides: List[PresentationGuide] = Field(default_factory=list)
    graphs: List[PresentationGraph] = Field(default_factory=list)
    sections: List[str] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)


ResponseBlockType = Literal[
    "markdown", "visualization", "calculation", "limitations", "citations", "suggested_actions"
]


class ResponseBlock(BaseModel):
    """Ordered, renderer-neutral response instruction.

    Blocks reference governed payloads already present on ComposedAnswer;
    they never duplicate or permit model-authored chart/calculation data.
    Older clients can ignore this field and continue rendering text,
    presentation, citations and calculation_widget directly.
    """

    id: str = Field(min_length=1, max_length=100)
    type: ResponseBlockType
    content: str | None = Field(default=None, max_length=100_000)
    resource_ids: List[str] = Field(default_factory=list, max_length=200)


ResponseMode = Literal[
    "concise", "educational", "analytical", "calculation", "workflow", "compound"
]


class ComposedAnswer(BaseModel):
    text: str
    citations: List[SourceCitation] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    calculation_widget: Optional[CalculationWidget] = None
    presentation: Optional[AnswerPresentation] = None
    response_mode: ResponseMode = "concise"
    blocks: List[ResponseBlock] = Field(default_factory=list, max_length=50)
    # Internal fields — kept for model_gateway wiring; never exposed to frontend
    prompt_id: str = "inline"
    prompt_name: str = "Inline RAG Prompt"
    output_text: str = ""  # alias for text, retained for backward compat

    def model_post_init(self, __context: object) -> None:
        """Build a deterministic plan when callers use the legacy fields."""
        if self.blocks:
            return
        blocks = [ResponseBlock(id="answer-text", type="markdown", content=self.text)]
        presentation = self.presentation
        if presentation is not None:
            resource_ids = [chart.chart_id for chart in presentation.charts]
            resource_ids.extend(guide.guide_id for guide in presentation.guides)
            resource_ids.extend(graph.graph_id for graph in presentation.graphs)
            if resource_ids or presentation.sections or presentation.follow_up_questions:
                blocks.append(ResponseBlock(
                    id="answer-presentation", type="visualization", resource_ids=resource_ids,
                ))
        if self.calculation_widget is not None:
            blocks.append(ResponseBlock(
                id="answer-calculation", type="calculation",
                resource_ids=[self.calculation_widget.calculation_id],
            ))
        if self.limitations:
            blocks.append(ResponseBlock(
                id="answer-limitations", type="limitations", content="\n".join(self.limitations),
            ))
        if self.citations:
            blocks.append(ResponseBlock(
                id="answer-citations", type="citations",
                resource_ids=[citation.ref_id for citation in self.citations],
            ))
        self.blocks = blocks
        if self.calculation_widget is not None:
            self.response_mode = "calculation"
        elif presentation is not None and (presentation.guides or presentation.graphs):
            self.response_mode = "workflow"
        elif presentation is not None and presentation.charts:
            self.response_mode = "analytical"
        elif presentation is not None and presentation.layout == "descriptive":
            self.response_mode = "educational"
        if len(blocks) > 2 and self.response_mode not in {"calculation", "workflow"}:
            self.response_mode = "compound"


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
