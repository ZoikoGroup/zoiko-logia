"""
Regression suite for GROUPED_BAR/STACKED_BAR — NOT a new data source: it
reinterprets the SAME real, independently-fetched, period-aligned pair
SCATTER already uses (dbnomics.py's _find_two_series), only when explicitly
requested as a bar chart rather than a scatter plot. Same precedent as
BOX vs HISTOGRAM (explicit-request-gated, scored above the default). Mirrors
the style of test_correlation_scatter_pipeline.py.
"""
from app.orchestration.data_shape import classify_data_shape, XY_NUMERIC
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.intent_classifier import classify_intent, CORRELATION
from app.orchestration.response_planner import (
    plan_response, detect_requested_chart_variant, TEXT_CHART,
)
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization.rules import score_candidates


def _paired_evidence(n=5):
    obs = [Observation(dimension=f"2024-{i:02d}", value=3.0 + i * 0.1) for i in range(1, n + 1)]
    sec = [Observation(dimension=f"2024-{i:02d}", value=2.5 + i * 0.15) for i in range(1, n + 1)]
    return EvidenceModel(
        subject="UK inflation", secondary_subject="US inflation",
        observations=obs, secondary_observations=sec,
        sources=["https://example.com/uk", "https://example.com/us"],
    )


# ── chart-variant phrasing (ordering guard against "bar chart" matching first) ──

def test_grouped_bar_chart_phrase_detected():
    q = "Show the correlation between UK inflation and US inflation as a grouped bar chart"
    assert detect_requested_chart_variant(q) == "GROUPED_BAR_CHART"


def test_stacked_bar_chart_phrase_detected():
    q = "Show the correlation between UK inflation and US inflation as a stacked bar chart"
    assert detect_requested_chart_variant(q) == "STACKED_BAR_CHART"


def test_plain_bar_chart_phrase_still_detected():
    assert detect_requested_chart_variant("Show UK CPI as a bar chart") == "BAR_CHART"


# ── rules.py scoring precedence (explicit request only) ──────────────────

def test_grouped_bar_scored_when_explicitly_requested():
    ranked = dict(score_candidates(
        XY_NUMERIC, observation_count=5, explicit_visual_request=False,
        intent=CORRELATION, explicit_grouped_bar_request=True,
    ))
    assert "GROUPED_BAR" in ranked
    assert ranked["GROUPED_BAR"] > ranked.get("SCATTER", 0)


def test_grouped_bar_not_scored_without_explicit_request():
    ranked = dict(score_candidates(
        XY_NUMERIC, observation_count=5, explicit_visual_request=False,
        intent=CORRELATION, explicit_grouped_bar_request=False,
    ))
    assert "GROUPED_BAR" not in ranked
    assert "SCATTER" in ranked


# ── full orchestrator pipeline ───────────────────────────────────────────

def test_orchestrator_builds_grouped_bar_spec_when_explicitly_requested():
    query = "Show the correlation between UK inflation and US inflation as a grouped bar chart"
    evidence = _paired_evidence()
    intent = classify_intent(query)
    assert intent == CORRELATION
    shape = classify_data_shape(evidence, intent)
    assert shape == XY_NUMERIC
    plan = plan_response(query, intent, shape)
    assert plan.requested_chart_variant == "GROUPED_BAR_CHART"

    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="viz-gb-1", query=query)

    assert result.visual_required is True
    assert result.selected == "GROUPED_BAR"
    assert result.renderer == "RECHARTS"
    assert result.spec is not None
    assert result.spec.type == "GROUPED_BAR"
    assert result.spec.variant == "GROUPED_BAR_CHART"
    assert len(result.spec.series) == 2
    assert {s.name for s in result.spec.series} == {"UK inflation", "US inflation"}
    assert all(len(s.data) == 5 for s in result.spec.series)


def test_orchestrator_builds_stacked_bar_variant():
    query = "Show the correlation between UK inflation and US inflation as a stacked bar chart"
    evidence = _paired_evidence()
    intent = classify_intent(query)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)

    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="viz-gb-2", query=query)
    assert result.spec.type == "GROUPED_BAR"
    assert result.spec.variant == "STACKED_BAR_CHART"


def test_plain_correlation_query_still_defaults_to_scatter():
    # Guard: adding GROUPED_BAR must not change the un-requested default.
    query = "What is the correlation between UK inflation and US inflation?"
    evidence = _paired_evidence()
    intent = classify_intent(query)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    assert plan.requested_chart_variant is None

    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="viz-gb-3", query=query)
    assert result.selected == "SCATTER"


# ── validator ─────────────────────────────────────────────────────────────

def _build_grouped_bar_result():
    query = "Show the correlation between UK inflation and US inflation as a grouped bar chart"
    evidence = _paired_evidence()
    intent = classify_intent(query)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    return VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="viz-gb-4", query=query)


def test_valid_grouped_bar_passes_validation():
    result = _build_grouped_bar_result()
    validation = VisualizationValidator().validate(result.spec)
    assert validation.passed
    assert validation.failures == []


def test_grouped_bar_with_only_one_series_fails_validation():
    from app.orchestration.visualization.spec import VisualizationSpec, NamedSeries, VisualizationDataPoint

    spec = VisualizationSpec(
        id="viz-bad-gb-1", type="GROUPED_BAR", family="COMPARISON", renderer="ECHARTS",
        series=[NamedSeries(name="A", data=[VisualizationDataPoint(x="2024-01", y=1.0), VisualizationDataPoint(x="2024-02", y=2.0)])],
    )
    validation = VisualizationValidator().validate(spec)
    assert not validation.passed
    assert any("at least 2 series" in f for f in validation.failures)


def test_grouped_bar_with_mismatched_category_labels_fails_validation():
    from app.orchestration.visualization.spec import VisualizationSpec, NamedSeries, VisualizationDataPoint

    spec = VisualizationSpec(
        id="viz-bad-gb-2", type="GROUPED_BAR", family="COMPARISON", renderer="ECHARTS",
        series=[
            NamedSeries(name="A", data=[VisualizationDataPoint(x="2024-01", y=1.0), VisualizationDataPoint(x="2024-02", y=2.0)]),
            NamedSeries(name="B", data=[VisualizationDataPoint(x="2024-01", y=1.5), VisualizationDataPoint(x="2024-03", y=2.5)]),
        ],
    )
    validation = VisualizationValidator().validate(spec)
    assert not validation.passed
    assert any("same category labels" in f for f in validation.failures)
