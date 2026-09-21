"""
VisualizationSpec — the renderer-neutral contract between the backend
visualization pipeline and the frontend. The LLM never emits this (and never
emits executable frontend code); it is built deterministically from
EvidenceModel by visualization/orchestrator.py and checked by
visualization/validator.py before it's ever sent to a client.

Implemented types: LINE, BAR and HISTOGRAM (family=STATISTICAL,
renderer=ECHARTS), KPI (renderer=KPI_TILE), EVIDENCE_GRAPH and HEATMAP
(family=RELATIONSHIP, renderer=GRAPH_ADAPTER/ECHARTS respectively —
EVIDENCE_GRAPH's renderer resolves to Cytoscape or G6 behind a feature
flag), PROCESS_FLOW (family=PROCESS, renderer=FLOW_ADAPTER — frontend
resolves to X6 for interactive flows, Mermaid for simple/read-only ones per
the `interactive` field below — see orchestrator.py's _build_process_flow_spec),
TABLE (family=STATISTICAL, renderer=TABLE_ADAPTER — real period/value rows
straight from EvidenceModel.observations, for PRECISE_DATA-intent questions
with multiple real values; never LLM-authored markdown). Other graph
subtypes (KNOWLEDGE_GRAPH, DEPENDENCY_GRAPH) are registry-only placeholders
— see registry.py.

Mermaid rendering here is NOT the LLM-authored ```mermaid text system that
was removed earlier — it's deterministic mermaid SYNTAX generated from this
SAME validated nodes/edges structure (frontend/components/visualization/
MermaidFlow.tsx), never free-text from the model. Same safety posture as
every other renderer in this pipeline.

HISTOGRAM, HEATMAP and BOX are NOT new data sources — all three reinterpret
evidence already produced by an existing source (see intent_classifier.py's
DISTRIBUTION docstring, orchestrator.py's _build_heatmap_spec and
_build_box_spec) rather than fabricating anything new. SCATTER (family=
STATISTICAL, renderer=ECHARTS) DOES use a dedicated connector —
dbnomics.py's _find_two_series resolves a correlation-shaped query's two
named subjects to two independently-fetched, real series, realigned to only
their common periods; see orchestrator.py's _build_scatter_spec.

DONUT (family=COMPOSITION, renderer=ECHARTS) also uses a dedicated
connector — market_data.py's _find_ownership resolves a real UK company's
persons-with-significant-control (Companies House) into named shareholders
and their declared ownership BAND. Every DonutSlice.value is a band
midpoint, never an exact filed percentage — see DonutSlice.is_estimated and
orchestrator.py's _build_donut_spec.

CANDLESTICK (family=FINANCIAL, renderer=ECHARTS) uses real OHLC bars already
fetched by market_data.py's fetch_market_sources() for a history-shaped
market-data question (Polygon/Alpha Vantage) — previously only ever
surfaced as a text citation, never a chart; see orchestrator.py's
_build_candlestick_spec.

GROUPED_BAR (family=COMPARISON, renderer=ECHARTS; STACKED_BAR_CHART is a
`variant` of the same type, not a separate one) is NOT a new data source —
it reinterprets the SAME real, independently-fetched, period-aligned pair
SCATTER already uses (dbnomics.py's _find_two_series), only when explicitly
requested as a bar chart rather than a scatter plot; see orchestrator.py's
_build_grouped_bar_spec.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from app.orchestration.visualization.domain import DomainContext


class EncodingField(BaseModel):
    field: str
    type: str            # temporal | quantitative | nominal | ordinal
    unit: str | None = None


class VisualizationEncoding(BaseModel):
    x: EncodingField
    y: EncodingField


class VisualizationDataPoint(BaseModel):
    x: str
    y: float


class GraphNode(BaseModel):
    id: str
    label: str
    type: str = "entity"


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str = "related_to"
    directed: bool = True


class HeatmapCell(BaseModel):
    x: str
    y: str
    value: float


class ScatterPoint(BaseModel):
    label: str    # the shared period label the pair was observed at
    x: float
    y: float


class DonutSlice(BaseModel):
    label: str
    value: float               # percent (0-100)
    # True for every slice this pipeline produces today — Companies House PSC
    # data only ever states a BAND, so `value` is always the band's midpoint,
    # never an exact filed figure. Carried per-slice (not a single spec-level
    # flag) so a future exact-percentage source could mix in real slices
    # without every existing slice appearing falsely precise.
    is_estimated: bool = True


class OHLCSlice(BaseModel):
    """One real trading-period bar (open/high/low/close), straight from
    Polygon/Alpha Vantage's get_history() — never a synthesized bar."""
    dimension: str    # a date/timestamp label
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


class NamedSeries(BaseModel):
    """One labeled series within a multi-series chart (GROUPED_BAR/
    STACKED_BAR_CHART variant) — general-purpose, reusable shape for any
    future multi-series need, not hardcoded to exactly two series."""
    name: str
    data: list[VisualizationDataPoint] = Field(default_factory=list)


class BoxSummary(BaseModel):
    label: str
    minimum: float
    q1: float
    median: float
    q3: float
    maximum: float
    outliers: list[float] = Field(default_factory=list)


class VisualizationSpec(BaseModel):
    version: str = "1.0"
    id: str
    type: str             # "LINE" | "BAR" | "HISTOGRAM" | "BOX" | "SCATTER" | "KPI" | "EVIDENCE_GRAPH" | "HEATMAP" | "PROCESS_FLOW" | "TABLE"
    family: str            # "STATISTICAL" | "RELATIONSHIP" | "PROCESS"
    renderer: str           # "RECHARTS" | "ECHARTS" | "KPI_TILE" | "GRAPH_ADAPTER" | "FLOW_ADAPTER" | "TABLE_ADAPTER"
    capability_id: str | None = None
    # Hierarchical routing metadata. `type` remains the wire-compatible
    # concrete type consumed by existing clients.
    canonical: str | None = None
    variant: str | None = None
    domain_context: DomainContext = Field(default_factory=DomainContext)
    # Same-family fallback types the router would degrade to if this one
    # failed to render/validate (registry.py's FALLBACKS) — surfaced so the
    # frontend's "View" alternatives menu offers real, backend-declared
    # alternatives rather than a hardcoded per-type list.
    fallback_order: list[str] = Field(default_factory=list)

    title: str | None = None
    summary: str | None = None   # accessibility text summary (spec §24)
    unit: str | None = None

    # Chart types (LINE / BAR / HISTOGRAM)
    encoding: VisualizationEncoding | None = None
    data: list[VisualizationDataPoint] = Field(default_factory=list)

    # Scalar types (KPI)
    value: float | None = None
    label: str | None = None

    # Graph/flow types (EVIDENCE_GRAPH / PROCESS_FLOW)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    # PROCESS_FLOW only — True routes to X6 (interactive), False to Mermaid
    # (simple/read-only). Meaningless for other types.
    interactive: bool = False
    # Optional user-selected frontend engines. Old/saved payloads omit these
    # and continue through the adapters' automatic selection.
    graph_engine: str | None = None       # auto | cytoscape | g6
    flow_engine: str | None = None        # mermaid | x6

    # Matrix types (HEATMAP) — x/y axis category labels are derived from the
    # cells themselves at render time rather than duplicated here.
    cells: list[HeatmapCell] = Field(default_factory=list)

    # Distribution summary types (BOX) — real min/Q1/median/Q3/max computed
    # from the SAME observation values HISTOGRAM bins, never fabricated.
    box: BoxSummary | None = None

    # Paired-numeric types (SCATTER) — real, independently-fetched,
    # period-aligned values from dbnomics.py's _find_two_series. correlation
    # is the real Pearson r computed from these SAME points, never a guess.
    scatter: list[ScatterPoint] = Field(default_factory=list)
    correlation_coefficient: float | None = None

    # Parts-of-a-whole types (DONUT) — real, named holders and their percent
    # share; see DonutSlice.is_estimated for why these are band midpoints,
    # not exact filed figures.
    donut: list[DonutSlice] = Field(default_factory=list)

    # Trading-bar types (CANDLESTICK) — real OHLC bars, never synthesized.
    candlestick: list[OHLCSlice] = Field(default_factory=list)

    # Multi-series types (GROUPED_BAR — `variant="STACKED_BAR_CHART"` flips
    # the frontend to stacked rendering of the SAME series data).
    series: list[NamedSeries] = Field(default_factory=list)

    # Tabular types (TABLE) — real rows, each a plain string->string map;
    # column order is `columns`, not dict iteration order (Python dicts
    # preserve insertion order, but this is explicit rather than relying on it).
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(default_factory=list)

    sources: list[str] = Field(default_factory=list)
