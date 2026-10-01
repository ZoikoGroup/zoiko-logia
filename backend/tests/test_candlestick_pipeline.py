"""
Regression suite for CANDLESTICK/OHLC — backed by real trading bars already
fetched by market_data.py's fetch_market_sources() for a history-shaped
market-data question (Polygon/Alpha Vantage's get_history()), previously
only ever surfaced as a text citation and never turned into a chart. Mirrors
the style of test_donut_ownership_pipeline.py: every layer is exercised with
real, honestly-shaped synthetic OHLC evidence, never a fabricated bar.
"""
from app.orchestration.data_shape import classify_data_shape, OHLC, NONE
from app.orchestration.evidence import EvidenceModel, OHLCBar
from app.orchestration.intent_classifier import classify_intent, TREND
from app.orchestration.response_planner import plan_response, TEXT_CHART
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization.registry import renderer_for, fallbacks_for
from app.orchestration.visualization.rules import score_candidates


def _bars(n=5):
    return [
        OHLCBar(dimension=f"2024-08-{i:02d}", open=100 + i, high=105 + i, low=99 + i, close=103 + i, volume=1000 + i * 10)
        for i in range(1, n + 1)
    ]


def _ohlc_evidence(n=5):
    return EvidenceModel(
        ohlc_subject="AAPL", ohlc=_bars(n),
        sources=["https://example.com/aapl-history"],
    )


# ── intent classification (history-shaped phrasing already exists) ───────

def test_history_query_classified_as_trend():
    assert classify_intent("Show Apple's share price history over the last 30 days") == TREND


# ── data shape ────────────────────────────────────────────────────────────

def test_ohlc_evidence_classified_as_ohlc_shape():
    assert classify_data_shape(_ohlc_evidence(), TREND) == OHLC


def test_single_bar_is_not_enough_for_ohlc_shape():
    one_bar = EvidenceModel(ohlc=_bars(1))
    assert classify_data_shape(one_bar, TREND) != OHLC


def test_no_evidence_at_all_is_none_shape():
    assert classify_data_shape(EvidenceModel(), TREND) == NONE


# ── response planning ────────────────────────────────────────────────────

def test_plan_response_requires_visual_for_ohlc():
    plan = plan_response("Show Apple's price history over the last 30 days", TREND, OHLC)
    assert plan.response_mode == TEXT_CHART
    assert plan.visual_required is True
    assert plan.visual_family == "FINANCIAL"


# ── rules.py scoring ──────────────────────────────────────────────────────

def test_candlestick_scored_for_ohlc_shape():
    ranked = dict(score_candidates(OHLC, observation_count=0, explicit_visual_request=False, ohlc_count=5))
    assert "CANDLESTICK" in ranked


def test_candlestick_not_scored_with_too_few_bars():
    ranked = dict(score_candidates(OHLC, observation_count=0, explicit_visual_request=False, ohlc_count=1))
    assert "CANDLESTICK" not in ranked


# ── registry ──────────────────────────────────────────────────────────────

def test_candlestick_renderer_is_echarts():
    assert renderer_for("CANDLESTICK") == "ECHARTS"


def test_candlestick_fallback_order():
    assert fallbacks_for("CANDLESTICK") == ["TABLE", "TEXT"]


# ── full orchestrator pipeline ───────────────────────────────────────────

def test_orchestrator_builds_candlestick_spec_end_to_end():
    query = "Show Apple's share price history over the last 30 days"
    evidence = _ohlc_evidence()
    intent = classify_intent(query)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)

    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="viz-cs-1", query=query)

    assert result.visual_required is True
    assert result.selected == "CANDLESTICK"
    assert result.renderer == "ECHARTS"
    assert result.fallback_order == ["TABLE", "TEXT"]
    assert result.spec is not None
    assert result.spec.type == "CANDLESTICK"
    assert result.spec.family == "FINANCIAL"
    assert len(result.spec.candlestick) == 5
    assert result.spec.sources == evidence.sources


def test_orchestrator_no_visual_without_visual_required():
    plan = plan_response("What is depreciation?", "FACT", NONE)
    result = VisualizationOrchestrator().decide(EvidenceModel(), NONE, plan, spec_id="viz-cs-2", query="What is depreciation?")
    assert result.visual_required is False
    assert result.spec is None


# ── validator ─────────────────────────────────────────────────────────────

def _build_candlestick_result(bars):
    evidence = EvidenceModel(ohlc_subject="AAPL", ohlc=bars, sources=["https://example.com/aapl-history"])
    query = "Show Apple's share price history over the last 30 days"
    shape = classify_data_shape(evidence, TREND)
    plan = plan_response(query, TREND, shape)
    return VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="viz-cs-3", query=query)


def test_valid_candlestick_passes_validation():
    result = _build_candlestick_result(_bars(4))
    validation = VisualizationValidator().validate(result.spec)
    assert validation.passed
    assert validation.failures == []


def test_candlestick_with_open_outside_low_high_fails_validation():
    from app.orchestration.visualization.spec import VisualizationSpec, OHLCSlice

    spec = VisualizationSpec(
        id="viz-bad-cs-1", type="CANDLESTICK", family="FINANCIAL", renderer="ECHARTS",
        candlestick=[
            OHLCSlice(dimension="2024-08-01", open=200, high=105, low=99, close=103),
            OHLCSlice(dimension="2024-08-02", open=103, high=108, low=102, close=107),
        ],
    )
    validation = VisualizationValidator().validate(spec)
    assert not validation.passed
    assert any("open outside" in f for f in validation.failures)


def test_candlestick_with_fewer_than_two_bars_fails_validation():
    from app.orchestration.visualization.spec import VisualizationSpec, OHLCSlice

    spec = VisualizationSpec(
        id="viz-bad-cs-2", type="CANDLESTICK", family="FINANCIAL", renderer="ECHARTS",
        candlestick=[OHLCSlice(dimension="2024-08-01", open=100, high=105, low=99, close=103)],
    )
    validation = VisualizationValidator().validate(spec)
    assert not validation.passed
    assert any("at least 2 bars" in f for f in validation.failures)
