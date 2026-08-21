"""Regression tests for the single-purpose-visual default."""
from app.orchestration.evidence import EvidenceModel, Observation, Entity, Relationship
from app.orchestration.intent_classifier import classify_intent
from app.orchestration.data_shape import classify_data_shape
from app.orchestration.response_planner import plan_response
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator, _build_complementary_specs


def _line_evidence(n=6) -> EvidenceModel:
    return EvidenceModel(
        subject="India CPI",
        observations=[Observation(dimension=f"2020-{i:02d}", value=100.0 + i * 1.5) for i in range(n)],
        sources=["x"],
    )


def _graph_evidence() -> EvidenceModel:
    return EvidenceModel(
        entities=[Entity(id="Acme Corp", name="Acme Corp"), Entity(id="Beta Ltd", name="Beta Ltd")],
        relationships=[Relationship(source_id="Acme Corp", target_id="Beta Ltd", type="owns")],
    )


def test_line_primary_does_not_get_repeated_kpi_secondary():
    q = "Show India CPI inflation over the last few quarters."
    ev = _line_evidence()
    intent = classify_intent(q)
    shape = classify_data_shape(ev, intent)
    plan = plan_response(q, intent, shape)
    result = VisualizationOrchestrator().decide(ev, shape, plan, spec_id="mv-1")

    assert result.selected == "LINE"
    assert result.secondary_specs == []


def test_line_has_no_implicit_complementary_visual():
    ev = _line_evidence()
    specs = _build_complementary_specs("LINE", ev, "primary-id")
    assert specs == []


def test_heatmap_primary_does_not_duplicate_as_evidence_graph():
    q = "Show this as a heatmap: Acme Corp owns Beta Ltd."
    ev = _graph_evidence()
    intent = classify_intent(q)
    shape = classify_data_shape(ev, intent)
    plan = plan_response(q, intent, shape)
    result = VisualizationOrchestrator().decide(ev, shape, plan, spec_id="mv-2")

    assert result.selected == "HEATMAP"
    assert result.secondary_specs == []


def test_evidence_graph_primary_gets_no_secondary():
    # EVIDENCE_GRAPH itself is not in the allowlist as a primary that gains a
    # companion — only HEATMAP (the harder-to-read format) gets one.
    q = "How are these companies connected? Acme Corp owns Beta Ltd."
    ev = _graph_evidence()
    intent = classify_intent(q)
    shape = classify_data_shape(ev, intent)
    plan = plan_response(q, intent, shape)
    result = VisualizationOrchestrator().decide(ev, shape, plan, spec_id="mv-3")

    assert result.selected == "EVIDENCE_GRAPH"
    assert result.secondary_specs == []


def test_process_flow_primary_gets_no_secondary():
    ev = EvidenceModel(
        entities=[Entity(id="A", name="A"), Entity(id="B", name="B")],
        relationships=[Relationship(source_id="A", target_id="B", type="next")],
    )
    specs = _build_complementary_specs("PROCESS_FLOW", ev, "flow-id")
    assert specs == []


def test_kpi_primary_gets_no_kpi_secondary():
    # Never duplicate KPI+KPI — the allowlist only offers KPI as a companion
    # to LINE/BAR/HISTOGRAM, not to itself.
    ev = EvidenceModel(observations=[Observation(dimension="2024-06-01", value=83.42)])
    specs = _build_complementary_specs("KPI", ev, "kpi-id")
    assert specs == []


def test_never_offers_redundant_alternate_chart_types():
    # The classic anti-pattern the spec calls out: LINE should never gain a
    # BAR/AREA/DONUT companion — same data, same question, different skin.
    ev = _line_evidence()
    specs = _build_complementary_specs("LINE", ev, "x")
    assert all(s.type != "BAR" for s in specs)


# ── Real companions: explicit ask, genuinely different lens ─────────────────

def test_line_primary_gets_kpi_companion_on_explicit_request():
    q = "Show India CPI inflation over the last few quarters, and give me the latest value too."
    ev = _line_evidence()
    specs = _build_complementary_specs("LINE", ev, "mv-x", query=q)
    assert len(specs) == 1
    assert specs[0].type == "KPI"
    assert specs[0].id == "mv-x-kpi"


def test_bar_primary_gets_kpi_companion_on_explicit_request():
    q = "Compare CPI across periods as a bar chart, and what's the current value?"
    ev = _line_evidence()
    specs = _build_complementary_specs("BAR", ev, "mv-y", query=q)
    assert len(specs) == 1
    assert specs[0].type == "KPI"


def test_kpi_companion_not_added_when_observations_empty():
    specs = _build_complementary_specs("LINE", EvidenceModel(), "x", query="show the kpi too")
    assert specs == []


def test_heatmap_primary_gets_evidence_graph_companion_on_explicit_request():
    q = "Show this as a heatmap and also as a network graph: Acme Corp owns Beta Ltd."
    ev = _graph_evidence()
    specs = _build_complementary_specs("HEATMAP", ev, "mv-z", query=q)
    assert len(specs) == 1
    assert specs[0].type == "EVIDENCE_GRAPH"
    assert specs[0].id == "mv-z-graph"


def test_heatmap_companion_not_added_when_relationships_empty():
    specs = _build_complementary_specs("HEATMAP", EvidenceModel(), "x", query="also show a network graph")
    assert specs == []


def test_table_trigger_still_takes_priority_over_kpi_trigger():
    q = "Show CPI over time as a table, and give me the latest value too."
    ev = _line_evidence()
    specs = _build_complementary_specs("LINE", ev, "mv-w", query=q)
    assert len(specs) == 1
    assert specs[0].type == "TABLE"
