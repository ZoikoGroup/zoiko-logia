"""
Regression suite for BOX (box-and-whisker plot) — real min/Q1/median/Q3/max
computed from the SAME observation values HISTOGRAM bins, routed only when
explicitly requested ("box plot", "box-and-whisker", "whisker plot").
"""
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.response_planner import plan_response, detect_requested_chart_variant
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization.registry import renderer_for, fallbacks_for
from app.orchestration.visualization.rules import score_candidates


def _evidence(values):
    return EvidenceModel(
        subject="India CPI",
        observations=[Observation(dimension=f"P{i}", value=float(v)) for i, v in enumerate(values)],
        units=["index"],
        sources=["dbnomics"],
    )


# ── explicit-request detection ───────────────────────────────────────────

def test_box_plot_phrasing_detected_as_requested_variant():
    assert detect_requested_chart_variant("Show me a box plot of India CPI") == "BOX_PLOT"


def test_box_and_whisker_phrasing_detected():
    assert detect_requested_chart_variant("Give me a box-and-whisker chart of the values") == "BOX_PLOT"


def test_whisker_plot_phrasing_detected():
    assert detect_requested_chart_variant("whisker plot of UK inflation please") == "BOX_PLOT"


def test_plain_trend_query_has_no_requested_variant():
    assert detect_requested_chart_variant("Show me India CPI over the last 10 years") is None


# ── rules.py scoring ──────────────────────────────────────────────────────

def test_box_only_scores_when_explicitly_requested():
    ranked_without = dict(score_candidates("TIME_SERIES", 10, False, explicit_box_request=False))
    ranked_with = dict(score_candidates("TIME_SERIES", 10, False, explicit_box_request=True))
    assert "BOX" not in ranked_without
    assert ranked_with["BOX"] == 0.95


def test_box_requires_minimum_points():
    ranked = dict(score_candidates("TIME_SERIES", 3, False, explicit_box_request=True))
    assert "BOX" not in ranked


# ── end-to-end orchestrator routing ──────────────────────────────────────

def test_box_plot_query_routes_to_box_with_real_quartiles():
    q = "Show me a box plot of India CPI over the last 10 years"
    evidence = _evidence([100, 103, 106, 109, 112, 115, 118, 121, 124, 127])
    plan = plan_response(q, "TREND", "TIME_SERIES")
    assert plan.requested_chart_variant == "BOX_PLOT"

    result = VisualizationOrchestrator().decide(evidence, "TIME_SERIES", plan, "spec-box-1", query=q)
    assert result.selected == "BOX"
    assert result.spec is not None
    assert result.spec.type == "BOX"
    box = result.spec.box
    assert box is not None
    assert box.minimum == 100.0
    assert box.maximum == 127.0
    assert box.minimum <= box.q1 <= box.median <= box.q3 <= box.maximum


def test_box_plot_query_without_box_wording_does_not_route_to_box():
    q = "Show me India CPI over the last 10 years"
    evidence = _evidence([100, 103, 106, 109, 112, 115, 118, 121, 124, 127])
    plan = plan_response(q, "TREND", "TIME_SERIES")
    result = VisualizationOrchestrator().decide(evidence, "TIME_SERIES", plan, "spec-box-2", query=q)
    assert result.selected != "BOX"


def test_box_spec_passes_validator():
    q = "box plot of India CPI"
    evidence = _evidence([100, 103, 106, 109, 112, 115, 118, 121, 124, 127])
    plan = plan_response(q, "TREND", "TIME_SERIES")
    result = VisualizationOrchestrator().decide(evidence, "TIME_SERIES", plan, "spec-box-3", query=q)
    outcome = VisualizationValidator().validate(result.spec)
    assert outcome.passed
    assert outcome.failures == []


def test_box_detects_real_outliers_via_iqr_rule():
    q = "box plot of these values"
    evidence = _evidence([10, 11, 12, 11, 10, 12, 11, 200])  # 200 is a genuine outlier
    plan = plan_response(q, "TREND", "TIME_SERIES")
    result = VisualizationOrchestrator().decide(evidence, "TIME_SERIES", plan, "spec-box-4", query=q)
    assert result.spec is not None
    assert 200.0 in result.spec.box.outliers


# ── registry ──────────────────────────────────────────────────────────────

def test_box_registered_with_echarts_renderer():
    assert renderer_for("BOX") == "ECHARTS"


def test_box_fallback_order_prefers_histogram_then_table():
    assert fallbacks_for("BOX") == ["HISTOGRAM", "TABLE", "TEXT"]
