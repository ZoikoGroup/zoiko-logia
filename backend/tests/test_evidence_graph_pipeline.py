"""
Regression suite for the evidence-graph / process-flow extension:
extraction.py, the new intent_classifier.py graph intents, data_shape.py's
NODES_EDGES/DIRECTED_STAGES, ava_advisor.py, and the orchestrator/validator
EVIDENCE_GRAPH/PROCESS_FLOW/BAR paths.
"""
from app.orchestration.extraction import extract_arrow_chain, extract_relation_clauses, extract_graph, extract_stage_list
from app.orchestration.intent_classifier import (
    classify_intent, EVIDENCE_ANALYSIS, RELATIONSHIP, DEPENDENCY, LINEAGE, PROCESS, FACT, GRAPH_INTENTS,
)
from app.orchestration.data_shape import classify_data_shape, NODES_EDGES, DIRECTED_STAGES, TIME_SERIES
from app.orchestration.evidence import EvidenceModel, Entity, Relationship, Observation
from app.orchestration.response_planner import plan_response, TEXT_GRAPH, TEXT_FLOWCHART
from app.orchestration.visualization import ava_advisor
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization.spec import VisualizationSpec, GraphNode, GraphEdge


# ── extraction.py ─────────────────────────────────────────────────────────────

def test_extract_arrow_chain_finds_ordered_stages():
    graph = extract_arrow_chain("Explain the invoice approval process: Invoice -> Review -> Approval.")
    assert graph.nodes == ["Invoice", "Review", "Approval"]
    assert [(e.source, e.target) for e in graph.edges] == [("Invoice", "Review"), ("Review", "Approval")]


def test_extract_arrow_chain_returns_none_without_a_chain():
    assert extract_arrow_chain("What is accrual accounting?") is None


def test_extract_relation_clauses_finds_typed_edges():
    graph = extract_relation_clauses("Acme Corp owns Beta Ltd. Beta Ltd invoices Gamma Inc.")
    assert set(graph.nodes) == {"Acme Corp", "Beta Ltd", "Gamma Inc"}
    types = {(e.source, e.target): e.type for e in graph.edges}
    assert types[("Acme Corp", "Beta Ltd")] == "owns"
    assert types[("Beta Ltd", "Gamma Inc")] == "invoices"


def test_extract_relation_clauses_avoids_false_positive_prose():
    assert extract_relation_clauses("He owns a small business.") is None


def test_extract_graph_prefers_typed_relation_clauses_over_arrow_chain():
    graph = extract_graph("Acme Corp owns Beta Ltd.")
    assert graph.edges[0].type == "owns"


def test_extracts_comma_stages_only_for_an_explicit_flow_request():
    query = "Show a Mermaid flowchart: Invoice received, invoice checked, payment approved, payment released."
    graph = extract_stage_list(query)
    assert graph is not None
    assert graph.nodes == ["Invoice received", "invoice checked", "payment approved", "payment released"]
    assert len(graph.edges) == 3
    assert extract_stage_list("Common accounting items: cash, inventory, receivables") is None


def test_comma_stage_mermaid_request_builds_valid_process_flow():
    query = "Show a Mermaid flowchart: Invoice received, invoice checked, payment approved, payment released."
    intent = classify_intent(query)
    graph = extract_graph(query)
    evidence = EvidenceModel(
        entities=[Entity(id=node, name=node) for node in graph.nodes],
        relationships=[Relationship(source_id=edge.source, target_id=edge.target, type=edge.type) for edge in graph.edges],
    )
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="comma-flow", query=query)
    assert intent == PROCESS
    assert shape == DIRECTED_STAGES
    assert result.spec.flow_engine == "mermaid"
    assert VisualizationValidator().validate(result.spec).passed


# ── intent_classifier.py graph intents ──────────────────────────────────────

def test_intent_evidence_analysis():
    assert classify_intent("Visualize every supplied entity and relationship as an evidence graph.") == EVIDENCE_ANALYSIS


def test_intent_relationship():
    assert classify_intent("How are these companies connected?") == RELATIONSHIP


def test_intent_dependency():
    assert classify_intent("Show the dependency map for these modules.") == DEPENDENCY


def test_intent_lineage():
    assert classify_intent("Show the data lineage of this figure.") == LINEAGE


def test_graph_intents_frozenset_contains_evidence_analysis():
    assert EVIDENCE_ANALYSIS in GRAPH_INTENTS
    assert FACT not in GRAPH_INTENTS


# ── data_shape.py graph/flow shapes ─────────────────────────────────────────

def _graph_evidence() -> EvidenceModel:
    return EvidenceModel(
        entities=[Entity(id="Acme Corp", name="Acme Corp"), Entity(id="Beta Ltd", name="Beta Ltd")],
        relationships=[Relationship(source_id="Acme Corp", target_id="Beta Ltd", type="owns")],
    )


def test_data_shape_nodes_edges_for_graph_intent():
    assert classify_data_shape(_graph_evidence(), RELATIONSHIP) == NODES_EDGES


def test_data_shape_directed_stages_for_process_intent():
    assert classify_data_shape(_graph_evidence(), PROCESS) == DIRECTED_STAGES


def test_data_shape_falls_through_when_intent_does_not_ask_for_a_visual():
    # Entities/relationships exist but intent is FACT — don't force a shape.
    ev = _graph_evidence()
    assert classify_data_shape(ev, FACT) != NODES_EDGES
    assert classify_data_shape(ev, FACT) != DIRECTED_STAGES


# ── response_planner.py graph/flow modes ────────────────────────────────────

def test_plan_text_graph_for_evidence_analysis_with_nodes_edges():
    plan = plan_response("Visualize the evidence graph.", EVIDENCE_ANALYSIS, NODES_EDGES)
    assert plan.response_mode == TEXT_GRAPH
    assert plan.visual_required is True


def test_plan_text_flowchart_for_process_with_directed_stages():
    plan = plan_response("Explain the invoice approval process.", PROCESS, DIRECTED_STAGES)
    assert plan.response_mode == TEXT_FLOWCHART
    assert plan.visual_required is True


# ── ava_advisor.py ───────────────────────────────────────────────────────────

def test_ava_recommends_bar_for_short_time_series():
    result = ava_advisor.recommend(TIME_SERIES, observation_count=4)
    assert result == ("BAR", 0.55)


def test_ava_recommends_nothing_for_long_time_series():
    assert ava_advisor.recommend(TIME_SERIES, observation_count=12) is None


def test_ava_recommends_nothing_outside_time_series():
    assert ava_advisor.recommend(NODES_EDGES, observation_count=4) is None


# ── VisualizationOrchestrator: EVIDENCE_GRAPH / PROCESS_FLOW ────────────────

def test_orchestrator_builds_evidence_graph_from_supplied_entities():
    evidence = _graph_evidence()
    plan = plan_response("How are these companies connected? Acme Corp owns Beta Ltd.", RELATIONSHIP, NODES_EDGES)
    result = VisualizationOrchestrator().decide(evidence, NODES_EDGES, plan, spec_id="viz-graph-1")

    assert result.selected == "EVIDENCE_GRAPH"
    assert result.renderer == "GRAPH_ADAPTER"
    assert len(result.spec.nodes) == 2
    assert len(result.spec.edges) == 1
    assert result.spec.edges[0].type == "owns"


def test_named_graph_engines_are_carried_to_the_frontend_adapter():
    evidence = _graph_evidence()
    for engine, query in (
        ("g6", "Show this as a G6 graph: Acme Corp owns Beta Ltd."),
        ("cytoscape", "Show this as a Cytoscape graph: Acme Corp owns Beta Ltd."),
        ("cytoscape", "Show a Cytoscape relationship graph: Acme Corp owns Beta Ltd."),
        ("cytoscape", "Use Cytoscape to show: Acme Corp owns Beta Ltd."),
    ):
        intent = classify_intent(query)
        plan = plan_response(query, intent, NODES_EDGES)
        result = VisualizationOrchestrator().decide(
            evidence, NODES_EDGES, plan, spec_id=f"viz-{engine}", query=query,
        )
        assert intent == RELATIONSHIP
        assert plan.explicit_visual_request is True
        assert result.spec.graph_engine == engine


def test_orchestrator_builds_process_flow_from_supplied_stages():
    evidence = EvidenceModel(
        entities=[Entity(id="Invoice", name="Invoice"), Entity(id="Review", name="Review"), Entity(id="Approval", name="Approval")],
        relationships=[
            Relationship(source_id="Invoice", target_id="Review", type="next"),
            Relationship(source_id="Review", target_id="Approval", type="next"),
        ],
    )
    plan = plan_response("Explain the invoice approval process: Invoice -> Review -> Approval.", PROCESS, DIRECTED_STAGES)
    result = VisualizationOrchestrator().decide(evidence, DIRECTED_STAGES, plan, spec_id="viz-flow-1")

    assert result.selected == "PROCESS_FLOW"
    assert result.renderer == "FLOW_ADAPTER"
    assert len(result.spec.nodes) == 3
    assert len(result.spec.edges) == 2


def test_orchestrator_never_fabricates_entities_not_supplied():
    # Only 1 entity, 0 relationships — graph rule requires >=2 entities and
    # >=1 edge, so no EVIDENCE_GRAPH should be built from this alone.
    evidence = EvidenceModel(entities=[Entity(id="Acme Corp", name="Acme Corp")])
    plan = plan_response("How are these connected?", RELATIONSHIP, NODES_EDGES)
    result = VisualizationOrchestrator().decide(evidence, NODES_EDGES, plan, spec_id="viz-graph-2")
    assert result.visual_required is False


# ── VisualizationValidator: graph / flow ─────────────────────────────────────

def test_validator_accepts_well_formed_evidence_graph():
    spec = VisualizationSpec(
        id="v1", type="EVIDENCE_GRAPH", family="RELATIONSHIP", renderer="GRAPH_ADAPTER",
        nodes=[GraphNode(id="A", label="A"), GraphNode(id="B", label="B")],
        edges=[GraphEdge(source="A", target="B", type="owns")],
    )
    result = VisualizationValidator().validate(spec)
    assert result.passed


def test_validator_rejects_evidence_graph_with_dangling_edge():
    spec = VisualizationSpec(
        id="v2", type="EVIDENCE_GRAPH", family="RELATIONSHIP", renderer="GRAPH_ADAPTER",
        nodes=[GraphNode(id="A", label="A")],
        edges=[GraphEdge(source="A", target="MISSING", type="owns")],
    )
    result = VisualizationValidator().validate(spec)
    assert not result.passed
    assert any("no matching node" in f for f in result.failures)


def test_validator_rejects_evidence_graph_with_duplicate_node_ids():
    spec = VisualizationSpec(
        id="v3", type="EVIDENCE_GRAPH", family="RELATIONSHIP", renderer="GRAPH_ADAPTER",
        nodes=[GraphNode(id="A", label="A"), GraphNode(id="A", label="A duplicate")],
        edges=[],
    )
    result = VisualizationValidator().validate(spec)
    assert not result.passed
    assert any("unique node IDs" in f for f in result.failures)


def test_validator_accepts_well_formed_process_flow():
    spec = VisualizationSpec(
        id="v4", type="PROCESS_FLOW", family="PROCESS", renderer="FLOW_ADAPTER",
        nodes=[GraphNode(id="Invoice", label="Invoice"), GraphNode(id="Review", label="Review")],
        edges=[GraphEdge(source="Invoice", target="Review", type="next")],
    )
    result = VisualizationValidator().validate(spec)
    assert result.passed


def test_validator_rejects_process_flow_with_no_start_stage():
    # A cycle: every stage is also a destination — no clear entry point.
    spec = VisualizationSpec(
        id="v5", type="PROCESS_FLOW", family="PROCESS", renderer="FLOW_ADAPTER",
        nodes=[GraphNode(id="A", label="A"), GraphNode(id="B", label="B")],
        edges=[GraphEdge(source="A", target="B", type="next"), GraphEdge(source="B", target="A", type="next")],
    )
    result = VisualizationValidator().validate(spec)
    assert not result.passed
    assert any("start stage" in f for f in result.failures)


def test_validator_rejects_bar_with_too_few_points():
    spec = VisualizationSpec(id="v6", type="BAR", family="STATISTICAL", renderer="ECHARTS", data=[])
    result = VisualizationValidator().validate(spec)
    assert not result.passed
