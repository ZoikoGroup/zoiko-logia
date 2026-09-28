"""Named chart types the pipeline cannot draw — orchestration/response_planner.py.

The substitution note added earlier only fires for a chart name the planner
RECOGNISES. Any other name left requested_chart_variant at None, the data
shape's default capability won uncontested, and someone who asked for a funnel
received a line chart with no explanation — precisely the silent swap the note
exists to prevent, reappearing for every chart name not in the table.

Listing these names does not make them drawable. It makes the refusal
explicit, which is the honest half of the guarantee.
"""
from __future__ import annotations

import pytest

from app.orchestration.data_shape import TIME_SERIES, classify_data_shape
from app.orchestration.evidence import Entity, EvidenceModel, Observation, Relationship
from app.orchestration.extraction import extract_graph
from app.orchestration.intent_classifier import GRAPH_INTENTS, PROCESS, classify_intent
from app.orchestration.response_planner import (
    ResponsePlan,
    detect_requested_chart_variant,
    plan_response,
)
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator

SERIES = EvidenceModel(
    observations=[
        Observation(dimension=f"20{year:02d}", value=100.0 + year * 3, measure="UK GDP")
        for year in range(10, 20)
    ]
)


def _decide(query: str):
    variant = detect_requested_chart_variant(query)
    plan = ResponsePlan(
        intent="TREND", response_mode="NARRATIVE", visual_required=True,
        visual_family="STATISTICAL", explicit_visual_request=True,
        confidence=0.9, requested_chart_variant=variant,
    )
    return variant, VisualizationOrchestrator().decide(
        SERIES, TIME_SERIES, plan, "spec", query,
    )


@pytest.mark.parametrize(
    "query, wording",
    [
        ("show uk gdp as a funnel chart", "funnel chart"),
        # "gauge" rather than "gauge chart": a gauge capability now exists, so
        # the label comes from the capability's own name. The refusal is still
        # right — a gauge needs a stated target, which a GDP series has not
        # got — it is simply worded from the real chart rather than the
        # generic fallback.
        ("show uk gdp as a gauge", "gauge"),
        ("show uk gdp as a sankey diagram", "sankey chart"),
        ("show uk gdp as a calendar heatmap", "calendar heatmap"),
        ("show uk gdp as a sunburst chart", "sunburst chart"),
        ("show uk gdp as a gantt chart", "gantt chart"),
        ("show uk gdp as a bubble chart", "bubble chart"),
        ("show uk gdp as a violin plot", "violin plot"),
        ("show uk gdp as a pareto chart", "pareto chart"),
        ("show uk gdp as parallel coordinates", "parallel-coordinates chart"),
        ("show uk gdp as a streamgraph", "streamgraph"),
        ("show uk gdp as a choropleth map", "choropleth map"),
    ],
)
def test_an_undrawable_chart_is_named_and_refused(query, wording):
    variant, result = _decide(query)
    assert variant is not None, "the chart name was not recognised at all"
    assert result.spec is not None
    summary = result.spec.summary or ""
    assert "isn't available" in summary
    assert wording in summary, f"the refusal should name the chart asked for: {summary}"


@pytest.mark.parametrize(
    "query, expected_type",
    [
        ("show uk gdp as a waterfall chart", "BAR"),
        ("show uk gdp as a bar chart", "BAR"),
        ("show uk gdp as a line chart", "LINE"),
        ("show uk gdp as an area chart", "LINE"),
    ],
)
def test_drawable_charts_still_draw_without_a_refusal(query, expected_type):
    _variant, result = _decide(query)
    assert result.selected == expected_type
    assert "isn't available" not in (result.spec.summary or "")


@pytest.mark.parametrize(
    "query, expected_variant",
    [
        ("show the ownership breakdown as a pie chart: Founder 55%, Investors 30%, Staff 15%",
         "PIE_CHART"),
        ("show the ownership breakdown as a donut chart: Founder 55%, Investors 30%, Staff 15%",
         "DONUT_CHART"),
        ("create a doughnut chart: payroll 45%, rent 30%, other 25%", "DONUT_CHART"),
        ("show the split as a ring chart: payroll 45%, rent 30%, other 25%", "DONUT_CHART"),
    ],
)
def test_a_pie_and_a_donut_are_different_requests(query, expected_variant):
    """Both words mapped to DONUT_CHART, so asking for a pie produced a ring
    — and the substitution reporter could not see it, because the delivered
    variant WAS the one requested. They share the DONUT type and differ only
    by the radius the renderer uses."""
    from app.orchestration.data_shape import classify_data_shape
    from app.orchestration.extraction import extract_user_visual_evidence
    from app.orchestration.intent_classifier import classify_intent

    intent = classify_intent(query)
    evidence = extract_user_visual_evidence(query, intent)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    result = VisualizationOrchestrator().decide(evidence, shape, plan, "spec", query)
    assert result.selected == "DONUT"
    assert result.variant == expected_variant


@pytest.mark.parametrize(
    "query, expected_type",
    [
        ("draw the audit process as a flow diagram: planning -> fieldwork -> review",
         "PROCESS_FLOW"),
        ("show as a heatmap: Control A audits Risk One; Control B audits Risk Two",
         "HEATMAP"),
    ],
)
def test_flow_and_heatmap_wording_is_not_hijacked(query, expected_type):
    """"flow diagram" belongs to PROCESS_FLOW and bare "heatmap" to the
    adjacency heatmap. Claiming either for a refusal would turn a chart that
    draws perfectly well into an apology."""
    intent = classify_intent(query)
    evidence = EvidenceModel()
    graph = extract_graph(query)
    if graph and (intent in GRAPH_INTENTS or intent == PROCESS):
        evidence.entities = [Entity(id=node, name=node) for node in graph.nodes]
        evidence.relationships = [
            Relationship(source_id=edge.source, target_id=edge.target, type=edge.type)
            for edge in graph.edges
        ]
        evidence.subject = query[:80]
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    result = VisualizationOrchestrator().decide(evidence, shape, plan, "spec", query)
    assert result.selected == expected_type
