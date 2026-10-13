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

import re
import statistics

from pydantic import BaseModel, Field

from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.response_planner import ResponsePlan
from app.orchestration.chart_tables import build_chart_table_spec, is_chart_table
from app.orchestration.kroki_diagrams import KROKI_CAPABILITIES, downgrade_if_unrenderable
from app.orchestration.visualization.capabilities import ROUTABLE_CAPABILITIES
from app.orchestration.visualization.registry import fallbacks_for, renderer_for, renderer_supports
from app.orchestration.visualization.rules import score_candidates
from app.orchestration.visualization.router import choose_visual_route
from app.orchestration.visualization.domain import DomainContext
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization.spec import (
    VisualizationSpec, VisualizationEncoding, EncodingField, VisualizationDataPoint,
    GraphNode, GraphEdge, HeatmapCell, BoxSummary, ScatterPoint, DonutSlice,
    OHLCSlice, NamedSeries,
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
    # The type the router originally chose, before any fallback cascade
    # substituted a different type due to validation failure. Equal to
    # `selected` when no fallback fired. See _build_spec_for_type's caller
    # in decide() and telemetry.py's fallback_used field.
    requested_type: str | None = None
    # Complementary visuals (spec §17: "up to ~3 when each adds a distinct
    # insight") — built ONLY from an explicit allowlist of genuinely
    # different lenses on the SAME evidence (never a redundant alternate
    # chart type for identical data, e.g. never LINE+BAR together). See
    # _build_complementary_specs. Each is independently validated by the
    # caller (service.py) before being attached to a response — a secondary
    # that fails validation is dropped, never blocks the primary.
    secondary_specs: list[VisualizationSpec] = Field(default_factory=list)


def _plot_points(evidence: EvidenceModel) -> list[Observation]:
    """The points a LINE or BAR should draw.

    Normally evidence.observations. For a market-history question those are
    empty — the real series arrives as evidence.ohlc, one trading bar per
    period — so a line or bar is drawn from each bar's CLOSE.

    Close rather than open, high or low because it is the figure the answer
    text quotes ("MSFT 1d closes, 400 bars from...") and the one a reader
    means by the price on a given day; picking another would let the chart
    and the prose disagree. Nothing is invented: these are values already in
    the evidence the candlestick would otherwise have drawn.
    """
    if evidence.observations:
        return list(evidence.observations)
    return [
        Observation(dimension=bar.dimension, value=bar.close, measure="close")
        for bar in evidence.ohlc
    ]


def _series_name(evidence: EvidenceModel) -> str:
    return (
        evidence.subject
        or (evidence.measures[0] if evidence.measures else "")
        or evidence.ohlc_subject
        or "value"
    )


def _build_line_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    measure_name = _series_name(evidence)
    unit = evidence.units[0] if evidence.units else None
    series: list[NamedSeries] = []
    title = measure_name
    summary = _summarize_series(measure_name, evidence, unit)
    if evidence.secondary_observations:
        secondary_name = evidence.secondary_subject or "Series B"
        title = f"{measure_name} vs {secondary_name}"
        series = [
            NamedSeries(
                name=measure_name,
                data=[VisualizationDataPoint(x=o.dimension, y=o.value) for o in evidence.observations],
            ),
            NamedSeries(
                name=secondary_name,
                data=[VisualizationDataPoint(x=o.dimension, y=o.value) for o in evidence.secondary_observations],
            ),
        ]
        summary = (
            f"{len(evidence.observations)} real, period-aligned observations of "
            f"{measure_name} and {secondary_name}."
        )
    return VisualizationSpec(
        id=spec_id,
        type="LINE",
        family="STATISTICAL",
        renderer="RECHARTS",
        title=title,
        summary=summary,
        unit=unit,
        encoding=VisualizationEncoding(
            x=EncodingField(field="period", type="temporal"),
            y=EncodingField(field="value", type="quantitative", unit=unit),
        ),
        data=[VisualizationDataPoint(x=o.dimension, y=o.value) for o in _plot_points(evidence)],
        series=series,
        sources=evidence.sources,
    )


def _build_bar_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    measure_name = _series_name(evidence)
    unit = evidence.units[0] if evidence.units else None
    return VisualizationSpec(
        id=spec_id,
        type="BAR",
        family="STATISTICAL",
        renderer="RECHARTS",
        title=measure_name,
        summary=_summarize_series(measure_name, evidence, unit),
        unit=unit,
        encoding=VisualizationEncoding(
            x=EncodingField(field="period", type="nominal"),
            y=EncodingField(field="value", type="quantitative", unit=unit),
        ),
        data=[VisualizationDataPoint(x=o.dimension, y=o.value) for o in _plot_points(evidence)],
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
        renderer="RECHARTS",
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
    columns = ["Period", value_col]
    rows = [{"Period": o.dimension, value_col: f"{o.value:g}"} for o in evidence.observations]
    if evidence.secondary_observations:
        secondary_name = evidence.secondary_subject or "Series B"
        secondary_unit = evidence.secondary_units[0] if evidence.secondary_units else unit
        secondary_col = f"{secondary_name}{f' ({secondary_unit})' if secondary_unit else ''}"
        columns.append(secondary_col)
        for row, observation in zip(rows, evidence.secondary_observations):
            row[secondary_col] = f"{observation.value:g}"
    return VisualizationSpec(
        id=spec_id,
        type="TABLE",
        family="STATISTICAL",
        renderer="TABLE_ADAPTER",
        title=measure_name,
        summary=f"{len(rows)} real {measure_name} values, exactly as retrieved — nothing summarized or rounded beyond source precision.",
        unit=unit,
        columns=columns,
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


def _build_gauge_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """A stated figure against the stated target it is measured by.

    Both numbers come from the user's own sentence
    (intent_classifier.explicit_target_pair); neither is retrieved, derived
    from a benchmark, or filled in. The percentage in the caption is
    arithmetic on those two figures, which is why it can be stated as fact.
    """
    latest = evidence.observations[-1]
    measure_name = evidence.subject or (evidence.measures[0] if evidence.measures else "value")
    unit = evidence.units[0] if evidence.units else None
    target = evidence.target
    suffix = unit if unit == "%" else ((" " + unit) if unit else "")
    achieved = (latest.value / target * 100) if target else 0.0

    def _money(value: float) -> str:
        # Not "%g": it renders 8_200_000 as "8.2e+06", which is unreadable in
        # a sentence an accountant is meant to check at a glance.
        return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:g}"

    return VisualizationSpec(
        id=spec_id,
        type="GAUGE",
        family="KPI",
        renderer="ECHARTS",
        title=measure_name,
        label=measure_name,
        value=latest.value,
        target=target,
        target_label=evidence.target_label or "Target",
        unit=unit,
        summary=(
            f"{measure_name}: {_money(latest.value)}{suffix} against a target of "
            f"{_money(target)}{suffix} — {achieved:.1f}% of target. "
            "Both figures were supplied in the question."
        ),
        sources=evidence.sources,
    )


def _build_donut_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """Real, named shareholders and their declared ownership BAND
    (market_data.py's _find_ownership, Companies House persons-with-
    significant-control) — every slice value is a band midpoint, never an
    exact filed figure (DonutSlice.is_estimated)."""
    title = evidence.composition_subject or evidence.subject or "Ownership composition"
    slices = [
        DonutSlice(
            label=o.dimension, value=o.value,
            is_estimated=evidence.composition_is_estimated,
        )
        for o in evidence.composition
    ]
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


def _build_candlestick_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """Real OHLC trading bars (Polygon/Alpha Vantage, via market_data.py's
    fetch_market_sources()) — never a synthesized bar."""
    title = evidence.ohlc_subject or evidence.subject or "Price history"
    bars = evidence.ohlc
    first, last = bars[0], bars[-1]
    return VisualizationSpec(
        id=spec_id,
        type="CANDLESTICK",
        family="FINANCIAL",
        renderer="ECHARTS",
        title=title,
        summary=(
            f"{len(bars)} real trading bars for {title}, from {first.dimension} "
            f"(open {first.open:g}) to {last.dimension} (close {last.close:g})."
        ),
        candlestick=[
            OHLCSlice(dimension=b.dimension, open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume)
            for b in bars
        ],
        sources=evidence.sources,
    )


def _build_grouped_bar_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """GROUPED_BAR/STACKED_BAR (variant) reinterpret the SAME real,
    independently-fetched, period-aligned pair SCATTER already uses
    (dbnomics.py's _find_two_series) as two named bar series over the
    shared periods — not a new data source, a second honest way to look at
    data already fetched."""
    if is_chart_table(evidence) and evidence.dimensions[1] == "budget_actual":
        return build_chart_table_spec(evidence, spec_id)
    x_name = evidence.subject or "Series A"
    y_name = evidence.secondary_subject or "Series B"
    series = [
        NamedSeries(name=x_name, data=[VisualizationDataPoint(x=o.dimension, y=o.value) for o in evidence.observations]),
        NamedSeries(name=y_name, data=[VisualizationDataPoint(x=o.dimension, y=o.value) for o in evidence.secondary_observations]),
    ]
    return VisualizationSpec(
        id=spec_id,
        type="GROUPED_BAR",
        family="COMPARISON",
        renderer="RECHARTS",
        title=f"{x_name} vs {y_name}",
        summary=f"{len(evidence.observations)} real, period-aligned observations of {x_name} and {y_name}.",
        encoding=VisualizationEncoding(
            x=EncodingField(field="period", type="nominal"),
            y=EncodingField(field="value", type="quantitative"),
        ),
        series=series,
        sources=evidence.sources,
    )


def _summarize_series(name: str, evidence: EvidenceModel, unit: str | None) -> str:
    obs = _plot_points(evidence)
    if len(obs) < 2:
        return f"{name}: {obs[0].value:g}{(' ' + unit) if unit else ''}." if obs else ""
    first, last = obs[0], obs[-1]
    # Endpoint-only comparison can call a series "held steady" even when it
    # swung wildly in between (e.g. GDP growth cratering then rebounding) —
    # see service.py's _grounded_domain_fallback for the same fix and the
    # reasoning. Kept consistent here so the chart caption never contradicts
    # the prose answer shown above it.
    values = [o.value for o in obs]
    value_range = max(values) - min(values)
    net_change = last.value - first.value
    if value_range > 0 and abs(net_change) < 0.5 * value_range:
        direction = "fluctuated"
    else:
        direction = "increased" if last.value > first.value else ("decreased" if last.value < first.value else "held steady")
    return (
        f"{name} {direction} from {first.value:g} ({first.dimension}) to "
        f"{last.value:g} ({last.dimension}){(' ' + unit) if unit else ''}."
    )


def _build_evidence_graph_spec(
    evidence: EvidenceModel, spec_id: str, preferred_engine: str | None = None,
) -> VisualizationSpec:
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
        graph_engine=preferred_engine,
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


def _build_process_flow_spec(
    evidence: EvidenceModel,
    spec_id: str,
    explicit_interactive: bool = False,
    preferred_engine: str | None = None,
) -> VisualizationSpec:
    nodes = [GraphNode(id=e.id, label=e.name, type="stage") for e in evidence.entities]
    edges = [
        GraphEdge(source=r.source_id, target=r.target_id, type=r.type, directed=True)
        for r in evidence.relationships
    ]
    interactive = (
        preferred_engine == "x6"
        or (preferred_engine != "mermaid" and (explicit_interactive or len(nodes) >= _INTERACTIVE_STAGE_THRESHOLD))
    )
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
        flow_engine=preferred_engine,
        sources=evidence.sources,
    )


# Ordinary questions intentionally render one visual. Previously this helper
# added the same KPI tile to every chart/table and a graph to every heatmap.
# That made different answers look repetitive and duplicated the evidence.
# Every rule below is an *explicit*-ask trigger, never inferred from the
# primary type alone, and produces at most one companion (the `elif`-style
# early-return chain makes that true by construction, not convention).
# "One named chart means one chart" — but only for chart types the user did
# not ask for. A bare \btable\b fired on any sentence containing the word,
# so "a bar graph of the tax table" produced a second, unrequested visual,
# while "using a table and line chart" must still produce both because the
# user asked for both. The alternatives below are deliberate asks for a
# table; "the tax table" and "this rate table shows" are not.
_TABLE_COMPANION_TRIGGER = re.compile(
    r"\b(?:and|with|plus|also)\s+(?:the\s+|a\s+|an\s+)?"
    r"(?:underlying\s+|raw\s+|source\s+|data\s+|full\s+)?tables?\b"
    r"|\b(?:as|in)\s+(?:a\s+)?table\b"
    r"|\busing\s+(?:a\s+)?table\b"
    r"|\bshow\s+(?:the\s+|me\s+)?(?:underlying\s+|raw\s+|source\s+)?table\b"
    r"|\btables?\s+and\s+(?:a\s+|an\s+)?[\w-]+\s*(?:chart|graph|plot)\b",
    re.I,
)
_KPI_COMPANION_TRIGGER = re.compile(
    r"\b(kpi|latest value|current value|headline (?:number|figure)|single (?:number|figure))\b", re.I,
)
_GRAPH_COMPANION_TRIGGER = re.compile(r"\b(graph|network|node-link|relationship diagram)\b", re.I)


# Readable names for the chart the user asked for and the one actually drawn.
# Variants are unique per capability, so that half is derived; selected_type is
# shared by many capabilities (every line variant selects "LINE"), so a derived
# lookup would name it after whichever entry happened to come last — "Waterfall
# Chart" for a plain BAR. Spelled out instead.
_VARIANT_LABELS: dict[str, str] = {c.variant: c.name for c in ROUTABLE_CAPABILITIES}
# Chart names response_planner.py records but no capability can serve. Derived
# from the variant key they would otherwise read as "a parallel coordinates",
# so the few that do not become a natural noun phrase are spelled out.
_VARIANT_LABELS.update({
    "PARALLEL_COORDINATES": "parallel-coordinates chart",
    "CALENDAR_HEATMAP": "calendar heatmap",
    "CHOROPLETH_MAP": "choropleth map",
    "CHORD_DIAGRAM": "chord diagram",
    "WORD_CLOUD": "word cloud",
    "STREAMGRAPH": "streamgraph",
    "VIOLIN_PLOT": "violin plot",
})
_TYPE_LABELS: dict[str, str] = {
    "LINE": "line chart", "BAR": "bar chart", "HISTOGRAM": "histogram",
    "BOX": "box plot", "SCATTER": "scatter plot", "KPI": "KPI card",
    "TABLE": "table", "DONUT": "donut chart", "CANDLESTICK": "candlestick chart",
    "GROUPED_BAR": "grouped bar chart", "HEATMAP": "heatmap",
    "EVIDENCE_GRAPH": "evidence graph", "PROCESS_FLOW": "process flow",
}


def _note_substitution(spec: VisualizationSpec, requested_variant: str, delivered_type: str) -> None:
    """Say, on the chart itself, that a different type was drawn.

    Written into `summary` rather than a new field because that is the caption
    strip the frontend already renders beneath every chart — the note needs no
    frontend change and stays attached to the visual it explains instead of
    floating loose in the prose, where a reader scanning the picture would
    never see it.
    """
    asked = _VARIANT_LABELS.get(requested_variant, requested_variant.replace("_", " ")).lower()
    drawn = _TYPE_LABELS.get(delivered_type, delivered_type.replace("_", " ").lower())
    if asked == drawn:
        return
    note = f"A {asked} isn't available for this data; showing a {drawn} instead."
    spec.summary = f"{note} {spec.summary}" if spec.summary else note


def _build_complementary_specs(
    primary_type: str, evidence: EvidenceModel, spec_id: str, query: str = "",
) -> list[VisualizationSpec]:
    query = query or ""
    if primary_type != "TABLE" and _TABLE_COMPANION_TRIGGER.search(query):
        return [_build_table_spec(evidence, f"{spec_id}-table")]
    if primary_type in ("LINE", "BAR", "HISTOGRAM") and evidence.observations and _KPI_COMPANION_TRIGGER.search(query):
        try:
            return [_build_kpi_spec(evidence, f"{spec_id}-kpi")]
        except Exception:
            return []
    # Heatmap is the harder-to-read format for entity/relationship data — a
    # second, honest rendering of the SAME entities/relationships as an
    # evidence graph (see _build_heatmap_spec's docstring) is a genuinely
    # different lens, not a redundant alternate skin on the same data.
    if primary_type == "HEATMAP" and evidence.relationships and _GRAPH_COMPANION_TRIGGER.search(query):
        try:
            return [_build_evidence_graph_spec(evidence, f"{spec_id}-graph")]
        except Exception:
            return []
    return []


def _build_spec_for_type(
    selected_type: str, evidence: EvidenceModel, spec_id: str, plan: ResponsePlan,
) -> VisualizationSpec | None:
    try:
        if selected_type == "LINE":
            return _build_line_spec(evidence, spec_id)
        elif selected_type == "BAR":
            return _build_bar_spec(evidence, spec_id)
        elif selected_type == "HISTOGRAM":
            return _build_histogram_spec(evidence, spec_id)
        elif selected_type == "BOX":
            return _build_box_spec(evidence, spec_id)
        elif selected_type == "SCATTER":
            return _build_scatter_spec(evidence, spec_id)
        elif selected_type == "TABLE":
            if is_chart_table(evidence):
                return build_chart_table_spec(evidence, spec_id)
            return _build_table_spec(evidence, spec_id)
        elif selected_type == "KPI":
            return _build_kpi_spec(evidence, spec_id)
        elif selected_type == "GAUGE":
            return _build_gauge_spec(evidence, spec_id)
        elif selected_type == "EVIDENCE_GRAPH":
            return _build_evidence_graph_spec(evidence, spec_id, plan.preferred_graph_engine)
        elif selected_type == "HEATMAP":
            return _build_heatmap_spec(evidence, spec_id)
        elif selected_type == "PROCESS_FLOW":
            return _build_process_flow_spec(
                evidence,
                spec_id,
                explicit_interactive=plan.explicit_interactive_request,
                preferred_engine=plan.preferred_flow_engine,
            )
        elif selected_type == "DONUT":
            return _build_donut_spec(evidence, spec_id)
        elif selected_type == "CANDLESTICK":
            return _build_candlestick_spec(evidence, spec_id)
        elif selected_type == "GROUPED_BAR":
            return _build_grouped_bar_spec(evidence, spec_id)
        else:
            return None
    except Exception:
        # Building the spec must never raise into the caller — a failed
        # visual degrades to no visual, not a broken answer (spec §19/§29).
        return None


# Every variant drawn as GROUPED_BAR, read from the capability table rather
# than listed by hand. A hand-written pair (grouped + stacked) left the 100%
# and horizontal stacked variants routable but never scored, so asking for
# one drew nothing at all.
_GROUPED_BAR_VARIANTS = frozenset(
    capability.variant for capability in ROUTABLE_CAPABILITIES
    if capability.selected_type == "GROUPED_BAR"
)


class VisualizationOrchestrator:
    def decide(self, evidence: EvidenceModel, data_shape: str, plan: ResponsePlan, spec_id: str, query: str = "") -> OrchestratorResult:
        if not plan.visual_required or evidence.is_empty():
            return OrchestratorResult(visual_required=False)

        # Count the points that would actually be DRAWN, not just
        # evidence.observations. Market history carries zero observations and
        # all its values in evidence.ohlc, so the raw count was 0 and every
        # capability with a minimum (bar_chart needs 3) was filtered out on a
        # series of 400 real bars.
        plot_point_count = len(_plot_points(evidence))
        route = choose_visual_route(
            data_shape=data_shape,
            plan=plan,
            observation_count=plot_point_count,
            entity_count=len(evidence.entities),
            query=query,
        )
        if route is None:
            return OrchestratorResult(visual_required=False, family=plan.visual_family)

        ranked = score_candidates(
            data_shape,
            plot_point_count,
            plan.explicit_visual_request,
            entity_count=len(evidence.entities),
            edge_count=len(evidence.relationships),
            intent=plan.intent,
            explicit_heatmap_request=plan.explicit_heatmap_request,
            explicit_box_request=plan.requested_chart_variant == "BOX_PLOT",
            composition_count=len(evidence.composition),
            explicit_grouped_bar_request=plan.requested_chart_variant in _GROUPED_BAR_VARIANTS,
            ohlc_count=len(evidence.ohlc),
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
        requested_type = selected_type
        built_spec = _build_spec_for_type(selected_type, evidence, spec_id, plan)
        if built_spec is not None and not VisualizationValidator().validate(built_spec).passed:
            built_spec = None

        # Auto-fallback cascade: a spec that fails validation isn't the end
        # of the line — fallbacks_for() already tells us the next type in
        # the same family's degrade chain, and the builder to produce it
        # already exists. Try each real (non-"TEXT") candidate in order
        # until one both builds and validates. Bounded by construction: this
        # is a single pass over the fixed list fallbacks_for(requested_type)
        # returns, never a recursive chase of each candidate's own further
        # chain — `tried` is a defensive no-op today, not load-bearing.
        if built_spec is None:
            tried = {requested_type}
            for candidate in fallbacks_for(requested_type):
                if candidate == "TEXT" or candidate in tried:
                    continue
                tried.add(candidate)
                candidate_renderer = renderer_for(candidate)
                if candidate_renderer is None or not renderer_supports(candidate_renderer, candidate):
                    continue
                candidate_spec = _build_spec_for_type(candidate, evidence, spec_id, plan)
                if candidate_spec is not None and VisualizationValidator().validate(candidate_spec).passed:
                    built_spec = candidate_spec
                    selected_type = candidate
                    renderer = candidate_renderer
                    break

        fallback_order = fallbacks_for(selected_type)

        if built_spec:
            if selected_type == requested_type:
                built_spec.family = route.family
                built_spec.capability_id = route.capability_id
                built_spec.canonical = route.canonical
                built_spec.variant = route.variant
                if route.capability_id in KROKI_CAPABILITIES:
                    downgrade_if_unrenderable(built_spec)
            else:
                # A fallback substitution was never routed through a
                # capability decision — it's a plain type-level degrade, not
                # the originally-matched capability. Leave the builder's own
                # `family` untouched rather than mislabeling it with the
                # original route's family.
                built_spec.capability_id = None
                built_spec.canonical = None
                built_spec.variant = None
            built_spec.fallback_order = fallback_order
            built_spec.domain_context = DomainContext(
                domain=plan.domain, subdomain=plan.subdomain, intent=plan.intent,
            )
            # A named chart type that cannot be produced is still answered with
            # the nearest valid one — but silently swapping it is what made the
            # pipeline look broken ("I asked for a bar chart and got a line").
            # Degrade, never silently: the same rule the rest of the system
            # follows.
            #
            # Both ways of losing the request are caught here. The rarer one is
            # the validation cascade above. The common one happens earlier, in
            # the router: a variant whose capability needs a data shape this
            # question did not produce (a scatter plot wants XY_NUMERIC, a
            # stacked bar wants two series) never becomes a candidate at all,
            # and the shape's default capability wins uncontested — so
            # selected_type equals requested_type and only the VARIANT reveals
            # that the user's request was dropped.
            # base_variant, not variant: domain_variant() renames the latter
            # per domain (STANDARD_LINE becomes TAX_METRIC_TREND on a tax
            # question), which would report a substitution on a request that
            # was honoured exactly.
            delivered_variant = route.base_variant if selected_type == requested_type else None
            if plan.requested_chart_variant and delivered_variant != plan.requested_chart_variant:
                _note_substitution(built_spec, plan.requested_chart_variant, selected_type)

        secondary_specs = _build_complementary_specs(selected_type, evidence, spec_id, query) if built_spec else []

        return OrchestratorResult(
            visual_required=built_spec is not None,
            family=route.family,
            candidates=candidates,
            selected=selected_type if built_spec else None,
            requested_type=requested_type,
            capability_id=built_spec.capability_id if built_spec else None,
            canonical=built_spec.canonical if built_spec else None,
            variant=built_spec.variant if built_spec else None,
            renderer=renderer if built_spec else None,
            fallback_order=fallback_order,
            spec=built_spec,
            secondary_specs=secondary_specs,
        )
