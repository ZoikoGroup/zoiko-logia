"""
Regression suite for:
  - frankfurter.py's dead FX_HINTS cleanup (still matches "how much is X in Y")
  - DISTRIBUTION intent -> HISTOGRAM (binned from real DBnomics values)
  - HEATMAP (adjacency matrix from user-supplied relationship graph)
"""
import asyncio
from unittest.mock import AsyncMock, patch

from app.orchestration.frankfurter import _find_rate
from app.orchestration.intent_classifier import classify_intent, DISTRIBUTION, RELATIONSHIP
from app.orchestration.extraction import extract_graph
from app.orchestration.data_shape import classify_data_shape, TIME_SERIES, NODES_EDGES
from app.orchestration.evidence import EvidenceModel, Observation, Entity, Relationship
from app.orchestration.response_planner import plan_response, TEXT_CHART, TEXT_GRAPH
from app.orchestration.visualization.registry import renderer_for
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization.spec import VisualizationSpec, VisualizationDataPoint, HeatmapCell
from app.orchestration.service import _grounded_domain_fallback


# ── Frankfurter "how much is X in Y" phrasing ────────────────────────────────

def test_frankfurter_matches_how_much_is_phrasing():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"rates": {"USD": 1.25}, "date": "2026-08-20"}

    # This is a deterministic parser regression test, not a live-network
    # smoke test. Mocking the transport keeps CI independent of Frankfurter.
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=Response()):
        match = asyncio.run(_find_rate("Exactly how much is 250 GBP in USD right now?"))
    assert match is not None
    assert match.base_cur == "GBP"
    assert match.quote_cur == "USD"
    assert match.amount == 250
    assert match.converted == 312.5


# ── DISTRIBUTION intent ──────────────────────────────────────────────────────

def test_intent_distribution():
    assert classify_intent("What is the distribution of India's CPI values?") == DISTRIBUTION


def test_data_shape_time_series_regardless_of_intent():
    ev = EvidenceModel(observations=[Observation(dimension=f"P{i}", value=float(i)) for i in range(10)])
    assert classify_data_shape(ev, DISTRIBUTION) == TIME_SERIES


def test_plan_text_chart_for_distribution_intent():
    plan = plan_response("Show the distribution of these values.", DISTRIBUTION, TIME_SERIES)
    assert plan.response_mode == TEXT_CHART
    assert plan.visual_required is True


# ── HISTOGRAM ─────────────────────────────────────────────────────────────────

def _long_series_evidence(n=12) -> EvidenceModel:
    return EvidenceModel(
        subject="India CPI",
        observations=[Observation(dimension=f"2020-{i:02d}", value=100.0 + i * 1.5) for i in range(n)],
        sources=["https://example.com/series"],
    )


def test_registry_maps_histogram_to_echarts():
    assert renderer_for("HISTOGRAM") == "RECHARTS"


def test_orchestrator_builds_histogram_from_real_values():
    evidence = _long_series_evidence(12)
    plan = plan_response("What is the distribution of these values?", DISTRIBUTION, TIME_SERIES)
    result = VisualizationOrchestrator().decide(evidence, TIME_SERIES, plan, spec_id="hist-1")

    assert result.selected == "HISTOGRAM"
    assert result.renderer == "RECHARTS"
    # Every real observation must land in exactly one bin — total count
    # across all bins must equal the number of real values, nothing lost.
    assert sum(p.y for p in result.spec.data) == len(evidence.observations)


def test_histogram_not_chosen_below_minimum_points():
    evidence = _long_series_evidence(4)  # below _MIN_HISTOGRAM_POINTS
    plan = plan_response("What is the distribution of these values?", DISTRIBUTION, TIME_SERIES)
    result = VisualizationOrchestrator().decide(evidence, TIME_SERIES, plan, spec_id="hist-2")
    # Falls back to LINE (or whatever the deterministic rule supports at 4
    # points) rather than a meaningless few-bin histogram.
    assert result.selected != "HISTOGRAM"


def test_validator_accepts_well_formed_histogram():
    spec = VisualizationSpec(
        id="h1", type="HISTOGRAM", family="STATISTICAL", renderer="RECHARTS",
        data=[VisualizationDataPoint(x="100-105", y=3), VisualizationDataPoint(x="105-110", y=5)],
    )
    result = VisualizationValidator().validate(spec)
    assert result.passed


def test_validator_rejects_histogram_with_all_zero_bins():
    spec = VisualizationSpec(
        id="h2", type="HISTOGRAM", family="STATISTICAL", renderer="RECHARTS",
        data=[VisualizationDataPoint(x="100-105", y=0)],
    )
    result = VisualizationValidator().validate(spec)
    assert not result.passed


# ── HEATMAP ───────────────────────────────────────────────────────────────────

def _relationship_evidence() -> EvidenceModel:
    return EvidenceModel(
        entities=[Entity(id="Acme Corp", name="Acme Corp"), Entity(id="Beta Ltd", name="Beta Ltd"), Entity(id="Gamma Inc", name="Gamma Inc")],
        relationships=[
            Relationship(source_id="Acme Corp", target_id="Beta Ltd", type="owns"),
            Relationship(source_id="Beta Ltd", target_id="Gamma Inc", type="invoices"),
        ],
    )


def test_registry_maps_heatmap_to_echarts():
    assert renderer_for("HEATMAP") == "ECHARTS"


def test_orchestrator_prefers_evidence_graph_without_explicit_heatmap_request():
    evidence = _relationship_evidence()
    plan = plan_response("How are these companies connected? Acme Corp owns Beta Ltd; Beta Ltd invoices Gamma Inc.", RELATIONSHIP, NODES_EDGES)
    result = VisualizationOrchestrator().decide(evidence, NODES_EDGES, plan, spec_id="hm-1")
    assert result.selected == "EVIDENCE_GRAPH"


def test_intent_relationship_from_heatmap_phrasing_without_connected_wording():
    # Regression: "show this as a heatmap: X owns Y" has no "connected"/
    # "related" wording, so it must still classify as relationship-shaped
    # intent purely from the explicit render-format request — this was a
    # real bug caught by live end-to-end testing (intent fell through to
    # FACT, so the whole graph pipeline never engaged despite extraction.py
    # correctly finding the relationship).
    assert classify_intent("Show this as a heatmap: Acme Corp owns Beta Ltd.") == RELATIONSHIP


def test_natural_relationship_graph_and_adjacency_matrix_phrasings_route_structurally():
    questions = [
        "Show this relationship graph: Company A owns Company B. Company B owns Company C.",
        "Create an adjacency matrix: Customer pays Company. Company pays Supplier. Supplier invoices Company.",
    ]
    for query in questions:
        assert classify_intent(query) == RELATIONSHIP
        assert extract_graph(query) is not None

    graph_plan = plan_response(questions[0], RELATIONSHIP, NODES_EDGES)
    matrix_plan = plan_response(questions[1], RELATIONSHIP, NODES_EDGES)
    assert graph_plan.visual_required is True
    assert matrix_plan.explicit_heatmap_request is True


def test_orchestrator_builds_heatmap_when_explicitly_requested():
    evidence = _relationship_evidence()
    q = "Show this as a heatmap: Acme Corp owns Beta Ltd; Beta Ltd invoices Gamma Inc."
    plan = plan_response(q, RELATIONSHIP, NODES_EDGES)
    assert plan.explicit_heatmap_request is True
    result = VisualizationOrchestrator().decide(evidence, NODES_EDGES, plan, spec_id="hm-2")

    assert result.selected == "HEATMAP"
    assert result.renderer == "ECHARTS"
    assert len(result.spec.cells) == 2
    assert {(c.x, c.y) for c in result.spec.cells} == {("Acme Corp", "Beta Ltd"), ("Beta Ltd", "Gamma Inc")}


def test_validator_accepts_well_formed_heatmap():
    spec = VisualizationSpec(
        id="hm3", type="HEATMAP", family="RELATIONSHIP", renderer="ECHARTS",
        cells=[HeatmapCell(x="A", y="B", value=1.0)],
    )
    result = VisualizationValidator().validate(spec)
    assert result.passed


def test_validator_rejects_empty_heatmap():
    spec = VisualizationSpec(id="hm4", type="HEATMAP", family="RELATIONSHIP", renderer="ECHARTS", cells=[])
    result = VisualizationValidator().validate(spec)
    assert not result.passed


# ── Live-testing regressions: bare "matrix view", "ownership structure",
# and "depends on" as an extraction verb (all found via manual end-to-end
# testing — the code paths existed but had gaps that silently produced no
# visualization instead of an error, so nothing failed loudly). ────────────

def test_intent_relationship_from_bare_matrix_view_phrasing():
    # Regression: response_planner.py's explicit-heatmap regex already
    # matched bare "matrix view" (no "as a" prefix), but intent_classifier.py
    # didn't — so a query recognised as an explicit heatmap request never
    # reached the graph pipeline at all because intent stayed FACT.
    q = "Give me a matrix view: Parent Holdings owns Sub One; Sub One controls Sub Two."
    assert classify_intent(q) == RELATIONSHIP


def test_intent_relationship_from_ownership_structure_phrasing():
    q = "Show the related-party ownership structure for consolidation: Acme Corp owns Beta Ltd."
    assert classify_intent(q) == RELATIONSHIP


def test_extraction_recognises_depends_on_as_a_relation_verb():
    # Regression: DEPENDENCY intent's own hint pattern matches "depends on",
    # but extraction.py's verb vocabulary didn't include it — so a DEPENDENCY-
    # intent query could never actually produce graph data to visualize.
    q = "Module A depends on Module B; Module B depends on Module C."
    graph = extract_graph(q)
    assert graph is not None
    assert graph.edges[0].type == "depends_on"


def test_matrix_view_and_ownership_structure_end_to_end_produce_a_visualization():
    for q in [
        "Give me a matrix view: Parent Holdings owns Sub One; Sub One controls Sub Two.",
        "Show the related-party ownership structure for consolidation: Acme Corp owns Beta Ltd.",
        "Give me a matrix view: Module A depends on Module B; Module B depends on Module C.",
    ]:
        intent = classify_intent(q)
        graph = extract_graph(q)
        assert graph is not None, q
        ev = EvidenceModel(
            entities=[Entity(id=n, name=n) for n in graph.nodes],
            relationships=[Relationship(source_id=e.source, target_id=e.target, type=e.type) for e in graph.edges],
        )
        shape = classify_data_shape(ev, intent)
        plan = plan_response(q, intent, shape)
        result = VisualizationOrchestrator().decide(ev, shape, plan, spec_id="regression")
        assert result.spec is not None, q
        assert VisualizationValidator().validate(result.spec).passed, q


def test_grounded_domain_fallback_accepts_financial_statistics():
    evidence = _long_series_evidence(12)
    text = _grounded_domain_fallback("Show the spread of UK inflation figures as a histogram.", evidence)
    assert text is not None
    assert "12 source-grounded observations" in text


def test_grounded_domain_fallback_accepts_accounting_relationships_only():
    accounting = _grounded_domain_fallback(
        "Show this as a heatmap: Acme Corp owns Beta Ltd; Beta Ltd invoices Gamma Inc.",
        EvidenceModel(),
    )
    programming = _grounded_domain_fallback(
        "Show the dependency graph: Module A depends on Module B.",
        EvidenceModel(),
    )
    assert accounting is not None
    assert programming is None
