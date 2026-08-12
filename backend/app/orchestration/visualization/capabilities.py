"""Executable visualization capability metadata.

Only capabilities backed end-to-end by today's EvidenceModel, validator and
frontend renderer are routable. The larger taxonomy can be normalized here
incrementally without adding selection branches.
"""
from __future__ import annotations

from dataclasses import dataclass
from app.orchestration.visualization.image_taxonomy import IMAGE_TAXONOMY_BY_ID


@dataclass(frozen=True)
class VisualizationCapability:
    id: str
    name: str
    family: str
    canonical_type: str
    variant: str
    selected_type: str
    domains: tuple[str, ...]
    supported_intents: tuple[str, ...]
    supported_data_shapes: tuple[str, ...]
    renderer: str
    minimum_observations: int = 0
    minimum_entities: int = 0
    interaction_level: str = "LOW"
    fallbacks: tuple[str, ...] = ("TEXT",)
    requires_explicit_heatmap: bool = False
    requires_interactivity: bool = False
    excludes_explicit_heatmap: bool = False
    priority: float = 0.8
    requested_variant: str | None = None


ALL_DOMAINS = (
    "GENERAL", "ACCOUNTING", "FINANCE", "TAX", "AUDIT", "ASSURANCE",
    "TREASURY", "FP&A", "ACCOUNTS_RECEIVABLE", "ACCOUNTS_PAYABLE",
    "COMPLIANCE", "RISK", "FRAUD_FORENSICS", "SUPPLY_CHAIN", "OPERATIONS",
    "SALES", "CUSTOMER_ANALYTICS", "HR_PAYROLL", "PROJECT_MANAGEMENT", "IT_ANALYTICS",
)


ROUTABLE_CAPABILITIES: tuple[VisualizationCapability, ...] = (
    VisualizationCapability(
        "bar_chart", "Bar Chart", "COMPARISON", "BAR", "BAR_CHART", "BAR",
        ALL_DOMAINS, ("TREND", "__EXPLICIT_VISUAL__"), ("TIME_SERIES",), "ECHARTS",
        minimum_observations=3, priority=0.98, requested_variant="BAR_CHART",
        fallbacks=("LINE", "TABLE", "TEXT"),
    ),
    VisualizationCapability(
        "step_line_chart", "Step Line Chart", "TREND", "LINE", "STEP_LINE_CHART", "LINE",
        ALL_DOMAINS, ("TREND", "__EXPLICIT_VISUAL__"), ("TIME_SERIES",), "ECHARTS",
        minimum_observations=3, priority=0.98, requested_variant="STEP_LINE_CHART",
    ),
    VisualizationCapability(
        "spline_line_chart", "Spline Line Chart", "TREND", "LINE", "SPLINE_LINE_CHART", "LINE",
        ALL_DOMAINS, ("TREND", "__EXPLICIT_VISUAL__"), ("TIME_SERIES",), "ECHARTS",
        minimum_observations=3, priority=0.98, requested_variant="SPLINE_LINE_CHART",
    ),
    VisualizationCapability(
        "area_chart", "Area Chart", "TREND", "AREA", "AREA_CHART", "LINE",
        ALL_DOMAINS, ("TREND", "__EXPLICIT_VISUAL__"), ("TIME_SERIES",), "ECHARTS",
        minimum_observations=3, priority=0.98, requested_variant="AREA_CHART",
    ),
    VisualizationCapability(
        "line_with_markers", "Line with Markers", "TREND", "LINE", "LINE_WITH_MARKERS", "LINE",
        ALL_DOMAINS, ("TREND", "__EXPLICIT_VISUAL__"), ("TIME_SERIES",), "ECHARTS",
        minimum_observations=3, priority=0.98, requested_variant="LINE_WITH_MARKERS",
    ),
    VisualizationCapability(
        "heatmap", "Heatmap", "RELATIONSHIP", "HEATMAP",
        "ADJACENCY_HEATMAP", "HEATMAP", ALL_DOMAINS, ("RELATIONSHIP",),
        ("NODES_EDGES",), "ECHARTS", minimum_entities=2,
        requires_explicit_heatmap=True, priority=0.97, fallbacks=("TABLE", "TEXT"),
    ),
    VisualizationCapability(
        "evidence_graph", "Evidence Graph", "GRAPH_NETWORK", "GRAPH",
        "EVIDENCE_GRAPH", "EVIDENCE_GRAPH", ALL_DOMAINS,
        ("EVIDENCE_ANALYSIS", "RELATIONSHIP", "NETWORK", "DEPENDENCY", "LINEAGE"),
        ("NODES_EDGES",), "GRAPH_ADAPTER", minimum_entities=2,
        excludes_explicit_heatmap=True, interaction_level="HIGH", priority=0.95,
        fallbacks=("TABLE", "TEXT"),
    ),
    VisualizationCapability(
        "workflow_diagram", "Workflow Diagram", "PROCESS", "FLOW",
        "INTERACTIVE_WORKFLOW", "PROCESS_FLOW", ALL_DOMAINS, ("PROCESS",),
        ("DIRECTED_STAGES",), "FLOW_ADAPTER", minimum_entities=2,
        requires_interactivity=True, interaction_level="HIGH", priority=0.92,
        fallbacks=("BASIC_FLOWCHART", "TEXT"),
    ),
    VisualizationCapability(
        "flowchart_basic", "Flowchart (Basic)", "PROCESS", "FLOW",
        "BASIC_FLOWCHART", "PROCESS_FLOW", ALL_DOMAINS, ("PROCESS",),
        ("DIRECTED_STAGES",), "FLOW_ADAPTER", minimum_entities=2,
        priority=0.90, fallbacks=("TEXT",),
    ),
    VisualizationCapability(
        "histogram", "Histogram", "DISTRIBUTION", "HISTOGRAM",
        "STANDARD_HISTOGRAM", "HISTOGRAM", ALL_DOMAINS, ("DISTRIBUTION",),
        ("TIME_SERIES",), "ECHARTS", minimum_observations=8, priority=0.85,
        fallbacks=("TABLE", "TEXT"),
    ),
    VisualizationCapability(
        "box_plot", "Box Plot", "DISTRIBUTION", "BOX", "BOX_PLOT", "BOX",
        ALL_DOMAINS, ("DISTRIBUTION", "__EXPLICIT_VISUAL__"), ("TIME_SERIES",),
        "ECHARTS", minimum_observations=4, priority=0.94, requested_variant="BOX_PLOT",
        fallbacks=("HISTOGRAM", "TABLE", "TEXT"),
    ),
    VisualizationCapability(
        "scatter_plot", "Scatter Plot", "CORRELATION", "SCATTER", "STANDARD_SCATTER", "SCATTER",
        ALL_DOMAINS, ("CORRELATION",), ("XY_NUMERIC",),
        "ECHARTS", minimum_observations=3, priority=0.93,
        fallbacks=("TABLE", "TEXT"),
    ),
    VisualizationCapability(
        "table_data_grid", "Table / Data Grid", "TABULAR", "TABLE",
        "EXACT_VALUES_TABLE", "TABLE", ALL_DOMAINS, ("PRECISE_DATA",),
        ("TIME_SERIES",), "TABLE_ADAPTER", minimum_observations=2, priority=0.90,
    ),
    VisualizationCapability(
        "line_chart", "Line Chart", "TREND", "LINE", "STANDARD_LINE", "LINE",
        ALL_DOMAINS, ("TREND", "__EXPLICIT_VISUAL__"), ("TIME_SERIES",),
        "ECHARTS", minimum_observations=3, priority=0.90,
        fallbacks=("BAR", "TABLE", "TEXT"),
    ),
    VisualizationCapability(
        "kpi_card", "KPI Card", "KPI", "KPI", "KPI_CARD", "KPI",
        ALL_DOMAINS, ("CURRENT_METRIC", "PRECISE_DATA"), ("SCALAR",),
        "KPI_TILE", minimum_observations=1, priority=0.85,
    ),
    VisualizationCapability(
        "donut_chart", "Donut Chart", "COMPOSITION", "PIE_DONUT",
        "DONUT_CHART", "DONUT", ALL_DOMAINS, ("COMPOSITION",),
        ("PART_TO_WHOLE",), "ECHARTS", priority=0.85,
        fallbacks=("TABLE", "TEXT"),
    ),
)

# Fail at startup if an active route drifts away from the supplied taxonomy.
for _capability in ROUTABLE_CAPABILITIES:
    _source = IMAGE_TAXONOMY_BY_ID.get(_capability.id)
    if _source is None:
        raise RuntimeError(f"routable capability {_capability.id!r} is absent from image taxonomy")
    if _source.canonical_type != _capability.canonical_type:
        raise RuntimeError(
            f"canonical mismatch for {_capability.id!r}: "
            f"taxonomy={_source.canonical_type}, route={_capability.canonical_type}"
        )
