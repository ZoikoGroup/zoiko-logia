"""
Regression suite for two bugs found via live testing after the TREND-intent
chart-variant fix (test_chart_variant_trend_intent.py):

  1. rules.py never scored a "BAR" candidate for plain time-series data — the
     router correctly selected canonical=BAR/variant=BAR_CHART for "as a bar
     chart"/"as a column chart" requests, but the orchestrator then filtered
     candidates down to an empty list and dropped the chart entirely.

  2. _grounded_domain_fallback() only checked intent_classifier.py's
     trend/distribution wordlists, so a chart-variant phrase not paired with
     trend wording (e.g. "box-and-whisker chart of UK inflation" with no
     "over time"/"last N years") kept the model's raw off-domain refusal even
     though real DBnomics observations were found.
"""
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.response_planner import plan_response
from app.orchestration.intent_classifier import classify_intent
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.rules import score_candidates
from app.orchestration.service import _grounded_domain_fallback


def _series_evidence(n=12) -> EvidenceModel:
    return EvidenceModel(
        subject="UK CPI",
        observations=[Observation(dimension=f"202{i}", value=float(3 + i * 0.1)) for i in range(n)],
        sources=["https://dbnomics.example/series"],
    )


# ── BAR scoring gap ───────────────────────────────────────────────────────

def test_bar_is_scored_for_plain_time_series():
    ranked = dict(score_candidates("TIME_SERIES", 12, False))
    assert ranked.get("BAR") == 0.70


def test_column_chart_request_actually_builds_a_bar_spec():
    q = "Give me UK inflation as a column chart"
    evidence = _series_evidence()
    plan = plan_response(q, classify_intent(q), "TIME_SERIES")
    result = VisualizationOrchestrator().decide(evidence, "TIME_SERIES", plan, "spec-bar-gap", query=q)
    assert result.selected == "BAR"
    assert result.spec is not None
    assert result.spec.type == "BAR"


def test_bar_chart_request_actually_builds_a_bar_spec():
    q = "Show India's CPI as a bar chart"
    evidence = _series_evidence()
    plan = plan_response(q, classify_intent(q), "TIME_SERIES")
    result = VisualizationOrchestrator().decide(evidence, "TIME_SERIES", plan, "spec-bar-gap-2", query=q)
    assert result.selected == "BAR"
    assert result.spec is not None


# ── _grounded_domain_fallback chart-variant gap ──────────────────────────

def test_box_and_whisker_without_trend_wording_still_corrects_refusal():
    q = "Give me a box-and-whisker chart of UK inflation"
    text = _grounded_domain_fallback(q, _series_evidence())
    assert text is not None
    assert "I'm designed to answer" not in text


def test_column_chart_without_trend_wording_still_corrects_refusal():
    q = "UK inflation as a column chart"
    text = _grounded_domain_fallback(q, _series_evidence())
    assert text is not None


def test_fallback_still_none_without_real_evidence_even_with_chart_wording():
    empty = EvidenceModel(subject=None, observations=[], sources=[])
    assert _grounded_domain_fallback("box plot of nonexistent data", empty) is None


def test_fallback_still_none_for_ordinary_fact_question_with_no_chart_wording():
    # Guard: a plain non-chart FACT question over real evidence should not be
    # force-corrected by the chart-variant branch just because evidence exists.
    q = "What does CPI stand for?"
    assert _grounded_domain_fallback(q, _series_evidence()) is None
