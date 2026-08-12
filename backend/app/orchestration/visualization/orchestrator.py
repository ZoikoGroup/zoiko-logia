"""
VisualizationOrchestrator (spec §7) — decides IF a visual is needed, which
family/type wins, which renderer handles it, and builds the resulting
VisualizationSpec straight from EvidenceModel (never from the LLM's free
text) so the narrative and the visual can never disagree about the numbers.

STATISTICAL family (LINE/BAR/KPI): deterministic rules + ava_advisor.py's
disambiguation signal, both folded into rules.score_candidates(). No LLM
fallback — deterministic rules + AVA together resolve every case this
pipeline can reach; an LLM fallback with nothing left to fall back FROM
would just be dead code (spec §28 "implement incrementally").

RELATIONSHIP/PROCESS family (EVIDENCE_GRAPH/PROCESS_FLOW): built from
evidence.entities/relationships, which only extraction.py populates — from
the user's OWN query text, never fabricated. See data_shape.py's docstring
for why the same entities/relationships can mean either shape depending on
intent.
"""
from __future__ import annotations

import statistics

from pydantic import BaseModel, Field

from app.orchestration.evidence import EvidenceModel
from app.orchestration.response_planner import ResponsePlan
from app.orchestration.visualization.registry import fallbacks_for, renderer_for, renderer_supports
from app.orchestration.visualization.rules import score_candidates
from app.orchestration.visualization.router import choose_visual_route
from app.orchestration.visualization.domain import DomainContext
from app.orchestration.visualization.spec import (
    VisualizationSpec, VisualizationEncoding, EncodingField, VisualizationDataPoint,
    GraphNode, GraphEdge, HeatmapCell, BoxSummary, ScatterPoint, DonutSlice,
)


class Candidate(BaseModel):
    type: str
    score: float


class OrchestratorResult(BaseModel):
    visual_required: bool
    family: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    selected: str | None = None
    capability_id: str | None = None
    canonical: str | None = None
    variant: str | None = None
    renderer: str | None = None
    fallback_order: list[str] = Field(default_factory=list)
    spec: VisualizationSpec | None = None
    # Complementary visuals (spec §17: "up to ~3 when each adds a distinct
    # insight") — built ONLY from an explicit allowlist of genuinely
    # different lenses on the SAME evidence (never a redundant alternate
    # chart type for identical data, e.g. never LINE+BAR together). See
    # _build_complementary_specs. Each is independently validated by the
    # caller (service.py) before being attached to a response — a secondary
    # that fails validation is dropped, never blocks the primary.
    secondary_specs: list[VisualizationSpec] = Field(default_factory=list)


def _build_line_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    measure_name = evidence.subject or (evidence.measures[0] if evidence.measures else "value")
    unit = evidence.units[0] if evidence.units else None
    return VisualizationSpec(
        id=spec_id,
        type="LINE",
        family="STATISTICAL",
        renderer="ECHARTS",
        title=measure_name,
        summary=_summarize_series(measure_name, evidence, unit),
        unit=unit,
        encoding=VisualizationEncoding(
            x=EncodingField(field="period", type="temporal"),
            y=EncodingField(field="value", type="quantitative", unit=unit),
        ),
        data=[VisualizationDataPoint(x=o.dimension, y=o.value) for o in evidence.observations],
        sources=evidence.sources,
    )


def _build_bar_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    measure_name = evidence.subject or (evidence.measures[0] if evidence.measures else "value")
    unit = evidence.units[0] if evidence.units else None
    return VisualizationSpec(
        id=spec_id,
        type="BAR",
        family="STATISTICAL",
        renderer="ECHARTS",
        title=measure_name,
        summary=_summarize_series(measure_name, evidence, unit),
        unit=unit,
        encoding=VisualizationEncoding(
            x=EncodingField(field="period", type="nominal"),
            y=EncodingField(field="value", type="quantitative", unit=unit),
        ),
        data=[VisualizationDataPoint(x=o.dimension, y=o.value) for o in evidence.observations],
        sources=evidence.sources,
    )


def _build_histogram_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """Bins the SAME real values dbnomics.py fetched for LINE/BAR — a second,
    honest way to look at data already retrieved, not a new data source."""
    measure_name = evidence.subject or (evidence.measures[0] if evidence.measures else "value")
    unit = evidence.units[0] if evidence.units else None
    values = [o.value for o in evidence.observations]
    lo, hi = min(values), max(values)
    bin_count = max(3, min(8, round(len(values) ** 0.5)))
    if hi == lo:
        bin_count = 1
    width = (hi - lo) / bin_count if bin_count and hi != lo else 1.0
    counts = [0] * bin_count
    for v in values:
        idx = min(bin_count - 1, int((v - lo) / width)) if width else 0
        counts[idx] += 1
    data = []
    for i in range(bin_count):
        start, end = lo + i * width, lo + (i + 1) * width
        data.append(VisualizationDataPoint(x=f"{start:.2f}–{end:.2f}", y=counts[i]))
    return VisualizationSpec(
        id=spec_id,
        type="HISTOGRAM",
        family="STATISTICAL",
        renderer="ECHARTS",
        title=f"Distribution of {measure_name}",
        summary=(
            f"Distribution of {len(values)} real {measure_name} values across {bin_count} bins, "
            f"ranging from {lo:g} to {hi:g}{(' ' + unit) if unit else ''}."
        ),
        unit=unit,
        encoding=VisualizationEncoding(
            x=EncodingField(field="bin", type="nominal"),
            y=EncodingField(field="count", type="quantitative"),
        ),
        data=data,
        sources=evidence.sources,
    )


def _build_box_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """Real min/Q1/median/Q3/max computed from the SAME values HISTOGRAM
    bins — a third, honest way to look at data already retrieved, not a new
    data source. Outliers use the standard 1.5*IQR rule over real values."""
    measure_name = evidence.subject or (evidence.measures[0] if evidence.measures else "value")
    unit = evidence.units[0] if evidence.units else None
    values = sorted(o.value for o in evidence.observations)
    q1, median, q3 = statistics.quantiles(values, n=4, method="inclusive")
    iqr = q3 - q1
    lo_fence, hi_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = [v for v in values if v < lo_fence or v > hi_fence]
    box = BoxSummary(
        label=measure_name, minimum=values[0], q1=q1, median=median,
        q3=q3, maximum=values[-1], outliers=outliers,
    )
    return VisualizationSpec(
        id=spec_id,
        type="BOX",
        family="STATISTICAL",
        renderer="ECHARTS",
        title=f"Distribution of {measure_name}",
        summary=(
            f"{len(values)} real {measure_name} values: min {values[0]:g}, median {median:g}, "
            f"max {values[-1]:g}{(' ' + unit) if unit else ''}"
            f"{f', {len(outliers)} outlier(s)' if outliers else ''}."
        ),
        unit=unit,
        box=box,
        sources=evidence.sources,
    )


def _build_scatter_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """Paired real values from TWO independently-fetched series
    (dbnomics.py's _find_two_series, already realigned to only their common
    periods) — never a fabricated pairing. correlation_coefficient is the
    real Pearson r computed from these SAME points."""
    x_name = evidence.subject or "X"
    y_name = evidence.secondary_subject or "Y"
    x_unit = evidence.units[0] if evidence.units else None
    y_unit = evidence.secondary_units[0] if evidence.secondary_units else None
    points = [
        ScatterPoint(label=x.dimension, x=x.value, y=y.value)
        for x, y in zip(evidence.observations, evidence.secondary_observations)
    ]
    r = None
    if len(points) >= 2:
        try:
            r = statistics.correlation(
                [p.x for p in points], [p.y for p in points],
            )
            # r is mathematically bounded to [-1, 1]; a near-perfectly-linear
            # real relationship can overshoot that by float error (e.g.
            # 1.0000000000000002) — clamp the artifact, not the real number.
            r = max(-1.0, min(1.0, r))
        except statistics.StatisticsError:
            r = None
    r_txt = f"; Pearson r = {r:.2f}" if r is not None else ""
    return VisualizationSpec(
        id=spec_id,
        type="SCATTER",
        family="STATISTICAL",
        renderer="ECHARTS",
        title=f"{x_name} vs {y_name}",
        summary=f"{len(points)} paired real observations of {x_name} and {y_name}{r_txt}.",
        encoding=VisualizationEncoding(
            x=EncodingField(field=x_name, type="quantitative", unit=x_unit),
            y=EncodingField(field=y_name, type="quantitative", unit=y_unit),
        ),
        scatter=points,
        correlation_coefficient=r,
        sources=evidence.sources,
    )


def _build_table_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """Every real observation as a row — for PRECISE_DATA intent, where a
    single KPI or a summarizing trend line would drop values the user
    explicitly asked to see in full."""
    measure_name = evidence.subject or (evidence.measures[0] if evidence.measures else "value")
    unit = evidence.units[0] if evidence.units else None
    value_col = f"{measure_name}{f' ({unit})' if unit else ''}"
    rows = [{"Period": o.dimension, value_col: f"{o.value:g}"} for o in evidence.observations]
    return VisualizationSpec(
        id=spec_id,
        type="TABLE",
        family="STATISTICAL",
        renderer="TABLE_ADAPTER",
        title=measure_name,
        summary=f"{len(rows)} real {measure_name} values, exactly as retrieved — nothing summarized or rounded beyond source precision.",
        unit=unit,
        columns=["Period", value_col],
        rows=rows,
        sources=evidence.sources,
    )


def _build_kpi_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    latest = evidence.observations[-1]
    measure_name = evidence.subject or (evidence.measures[0] if evidence.measures else "value")
    unit = evidence.units[0] if evidence.units else None
    return VisualizationSpec(
        id=spec_id,
        type="KPI",
        family="STATISTICAL",
        renderer="KPI_TILE",
        title=measure_name,
        label=measure_name,
        value=latest.value,
        unit=unit,
        summary=f"{measure_name}: {latest.value:g}{(' ' + unit) if unit else ''} ({latest.dimension}).",
        sources=evidence.sources,
    )


def _build_donut_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """Real, named shareholders and their declared ownership BAND
    (market_data.py's _find_ownership, Companies House persons-with-
    significant-control) — every slice value is a band midpoint, never an
    exact filed figure (DonutSlice.is_estimated)."""
    title = evidence.composition_subject or evidence.subject or "Ownership composition"
    slices = [DonutSlice(label=o.dimension, value=o.value) for o in evidence.composition]
    return VisualizationSpec(
        id=spec_id,
        type="DONUT",
        family="COMPOSITION",
        renderer="ECHARTS",
        title=title,
        summary=evidence.composition_caveat or "",
        unit="%",
        donut=slices,
        sources=evidence.sources,
    )


def _summarize_series(name: str, evidence: EvidenceModel, unit: str | None) -> str:
    obs = evidence.observations
    if len(obs) < 2:
        return f"{name}: {obs[0].value:g}{(' ' + unit) if unit else ''}." if obs else ""
    first, last = obs[0], obs[-1]
    direction = "increased" if last.value > first.value else ("decreased" if last.value < first.value else "held steady")
    return (
        f"{name} {direction} from {first.value:g} ({first.dimension}) to "
        f"{last.value:g} ({last.dimension}){(' ' + unit) if unit else ''}."
    )


def _build_evidence_graph_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    nodes = [GraphNode(id=e.id, label=e.name, type=e.type) for e in evidence.entities]
    edges = [
        GraphEdge(source=r.source_id, target=r.target_id, type=r.type, directed=r.directed)
        for r in evidence.relationships
    ]
    return VisualizationSpec(
        id=spec_id,
        type="EVIDENCE_GRAPH",
        family="RELATIONSHIP",
        renderer="GRAPH_ADAPTER",
        title=evidence.subject or "Evidence graph",
        # The deterministic answer already explains that this structure came
        # from the prompt; repeating counts below the graph adds no value.
        summary="",
        nodes=nodes,
        edges=edges,
        sources=evidence.sources,
    )


def _build_heatmap_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """Adjacency-intensity matrix from the SAME entities/relationships
    EVIDENCE_GRAPH builds from — a second, honest rendering of graph data
    already extracted from the user's own query text, not a new source."""
    id_to_label = {e.id: e.name for e in evidence.entities}
    counts: dict[tuple[str, str], int] = {}
    for r in evidence.relationships:
        src = id_to_label.get(r.source_id, r.source_id)
        tgt = id_to_label.get(r.target_id, r.target_id)
        counts[(src, tgt)] = counts.get((src, tgt), 0) + 1
    cells = [HeatmapCell(x=src, y=tgt, value=float(c)) for (src, tgt), c in counts.items()]
    return VisualizationSpec(
        id=spec_id,
        type="HEATMAP",
        family="RELATIONSHIP",
        renderer="ECHARTS",
        title=evidence.subject or "Relationship matrix",
        summary=(
            f"Adjacency matrix of {len(evidence.entities)} entities and {len(cells)} relationship "
            "cells, exactly as supplied — nothing inferred beyond what was stated."
        ),
        cells=cells,
        sources=evidence.sources,
    )


# Stage count above which a flow routes to X6 even without an explicit
# interactivity request — matches the design spec's own routing rule
# ("elif flow_complexity_score >= threshold: X6"). extraction.py only ever
# produces a simple linear chain today, so this rarely fires yet, but it's
# the honest complexity signal available (no branching data exists to
# measure real graph complexity beyond stage count).
_INTERACTIVE_STAGE_THRESHOLD = 6


def _build_process_flow_spec(evidence: EvidenceModel, spec_id: str, explicit_interactive: bool = False) -> VisualizationSpec:
    nodes = [GraphNode(id=e.id, label=e.name, type="stage") for e in evidence.entities]
    edges = [
        GraphEdge(source=r.source_id, target=r.target_id, type=r.type, directed=True)
        for r in evidence.relationships
    ]
    interactive = explicit_interactive or len(nodes) >= _INTERACTIVE_STAGE_THRESHOLD
    return VisualizationSpec(
        id=spec_id,
        type="PROCESS_FLOW",
        family="PROCESS",
        renderer="FLOW_ADAPTER",
        title=evidence.subject or "Process flow",
        summary="",
        nodes=nodes,
        edges=edges,
        interactive=interactive,
        sources=evidence.sources,
    )


# Ordinary questions intentionally render one visual. Previously this helper
# added the same KPI tile to every chart/table and a graph to every heatmap.
# That made different answers look repetitive and duplicated the evidence.
# Keep the hook for a future *explicit* multi-visual request, but never infer a
# second visual merely from the primary type.
def _build_complementary_specs(
    primary_type: str, evidence: EvidenceModel, spec_id: str,
) -> list[VisualizationSpec]:
    return []


class VisualizationOrchestrator:
    def decide(self, evidence: EvidenceModel, data_shape: str, plan: ResponsePlan, spec_id: str, query: str = "") -> OrchestratorResult:
        if not plan.visual_required or evidence.is_empty():
            return OrchestratorResult(visual_required=False)

        route = choose_visual_route(
            data_shape=data_shape,
            plan=plan,
            observation_count=len(evidence.observations),
            entity_count=len(evidence.entities),
            query=query,
        )
        if route is None:
            return OrchestratorResult(visual_required=False, family=plan.visual_family)

        ranked = score_candidates(
            data_shape,
            len(evidence.observations),
            plan.explicit_visual_request,
            entity_count=len(evidence.entities),
            edge_count=len(evidence.relationships),
            intent=plan.intent,
            explicit_heatmap_request=plan.explicit_heatmap_request,
            explicit_box_request=plan.requested_chart_variant == "BOX_PLOT",
            composition_count=len(evidence.composition),
        )
        if not ranked:
            return OrchestratorResult(visual_required=False)

        candidates = [Candidate(type=t, score=s) for t, s in ranked]
        # Candidate scoring now operates inside the route chosen from family
        # and canonical visual, rather than flattening every concrete type
        # into one global classification problem.
        supported_candidates = [c for c in candidates if c.type == route.selected_type]
        if not supported_candidates or supported_candidates[0].score < 0.55:
            return OrchestratorResult(
                visual_required=False, family=route.family,
                canonical=route.canonical, variant=route.variant,
                candidates=candidates,
            )
        selected_type = route.selected_type
        renderer = renderer_for(selected_type)
        if renderer is None or not renderer_supports(renderer, selected_type):
            return OrchestratorResult(
                visual_required=False, family=route.family,
                canonical=route.canonical, variant=route.variant,
                candidates=candidates, fallback_order=fallbacks_for(selected_type),
            )
        fallback_order = fallbacks_for(selected_type)

        try:
            if selected_type == "LINE":
                built_spec = _build_line_spec(evidence, spec_id)
            elif selected_type == "BAR":
                built_spec = _build_bar_spec(evidence, spec_id)
            elif selected_type == "HISTOGRAM":
                built_spec = _build_histogram_spec(evidence, spec_id)
            elif selected_type == "BOX":
                built_spec = _build_box_spec(evidence, spec_id)
            elif selected_type == "SCATTER":
                built_spec = _build_scatter_spec(evidence, spec_id)
            elif selected_type == "TABLE":
                built_spec = _build_table_spec(evidence, spec_id)
            elif selected_type == "KPI":
                built_spec = _build_kpi_spec(evidence, spec_id)
            elif selected_type == "EVIDENCE_GRAPH":
                built_spec = _build_evidence_graph_spec(evidence, spec_id)
            elif selected_type == "HEATMAP":
                built_spec = _build_heatmap_spec(evidence, spec_id)
            elif selected_type == "PROCESS_FLOW":
                built_spec = _build_process_flow_spec(evidence, spec_id, explicit_interactive=plan.explicit_interactive_request)
            elif selected_type == "DONUT":
                built_spec = _build_donut_spec(evidence, spec_id)
            else:
                built_spec = None
        except Exception:
            # Building the spec must never raise into the caller — a failed
            # visual degrades to no visual, not a broken answer (spec §19/§29).
            built_spec = None

        if built_spec:
            built_spec.family = route.family
            built_spec.capability_id = route.capability_id
            built_spec.canonical = route.canonical
            built_spec.fallback_order = fallback_order
            built_spec.variant = route.variant
            built_spec.domain_context = DomainContext(
                domain=plan.domain, subdomain=plan.subdomain, intent=plan.intent,
            )

        secondary_specs = _build_complementary_specs(selected_type, evidence, spec_id) if built_spec else []

        return OrchestratorResult(
            visual_required=built_spec is not None,
            family=route.family,
            candidates=candidates,
            selected=selected_type if built_spec else None,
            capability_id=route.capability_id if built_spec else None,
            canonical=route.canonical if built_spec else None,
            variant=route.variant if built_spec else None,
            renderer=renderer if built_spec else None,
            fallback_order=fallback_order,
            spec=built_spec,
            secondary_specs=secondary_specs,
        )
