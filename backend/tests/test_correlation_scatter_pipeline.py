"""
Regression suite for SCATTER + CORRELATION — the first real second-numeric-
series capability in the pipeline. Data comes from dbnomics.py's
_find_two_series, which independently fetches TWO named subjects and
realigns them to only their common periods before pairing — never an
interpolated or fabricated pairing. Everything downstream (intent, data
shape, routing, spec, validator) is exercised here with real, honestly
correlated/uncorrelated synthetic evidence, mirroring the style of the
other visualization-type regression suites in this directory.
"""
import random

from app.orchestration.dbnomics import _split_correlation_subjects
from app.orchestration.intent_classifier import classify_intent, CORRELATION, RELATIONSHIP
from app.orchestration.data_shape import classify_data_shape, XY_NUMERIC, TIME_SERIES
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.response_planner import plan_response, TEXT_CHART
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization.registry import renderer_for, fallbacks_for
from app.orchestration.visualization.rules import score_candidates


def _paired_evidence(n=12, correlated=True):
    if correlated:
        obs = [Observation(dimension=f"2020-{i:02d}", value=100.0 + i * 2) for i in range(n)]
        sec = [Observation(dimension=f"2020-{i:02d}", value=3.0 + i * 0.15) for i in range(n)]
    else:
        rng = random.Random(7)
        obs = [Observation(dimension=f"2020-{i:02d}", value=rng.uniform(0, 100)) for i in range(n)]
        sec = [Observation(dimension=f"2020-{i:02d}", value=rng.uniform(0, 100)) for i in range(n)]
    return EvidenceModel(
        subject="India CPI", secondary_subject="UK inflation",
        observations=obs, secondary_observations=sec,
        sources=["dbnomics-a", "dbnomics-b"],
    )


# ── dbnomics.py subject splitting ────────────────────────────────────────

def test_correlation_between_phrasing_splits_subjects():
    assert _split_correlation_subjects("What is the correlation between India CPI and UK inflation?") == (
        "India CPI", "UK inflation",
    )


def test_correlated_with_phrasing_splits_subjects():
    assert _split_correlation_subjects("Is India CPI correlated with UK unemployment?") == (
        "India CPI", "UK unemployment",
    )


def test_non_correlation_query_does_not_split():
    assert _split_correlation_subjects("Show India CPI over the last 10 years") is None


# ── intent classification: CORRELATION vs RELATIONSHIP disjointness ─────

def test_correlation_phrasing_classified_as_correlation():
    assert classify_intent("What is the correlation between India CPI and UK inflation?") == CORRELATION


def test_relationship_phrasing_still_classified_as_relationship():
    # Guard: the new CORRELATION intent must not swallow the existing
    # entity-relationship-graph phrasing ("relationship between" for graphs).
    assert classify_intent("Show the relationship between Company A and Company B") == RELATIONSHIP


# ── data shape ────────────────────────────────────────────────────────────

def test_paired_series_classified_as_xy_numeric():
    ev = _paired_evidence()
    assert classify_data_shape(ev, CORRELATION) == XY_NUMERIC


def test_single_series_with_correlation_intent_stays_time_series():
    # Guard: without a real secondary series, a correlation-intent query
    # must NOT be misread as XY_NUMERIC — that would imply paired data that
    # was never actually fetched.
    ev = EvidenceModel(
        subject="India CPI",
        observations=[Observation(dimension=f"2020-{i:02d}", value=100.0 + i) for i in range(12)],
        sources=["dbnomics-a"],
    )
    assert classify_data_shape(ev, CORRELATION) == TIME_SERIES


# ── response planner ──────────────────────────────────────────────────────

def test_plan_response_routes_correlation_to_text_chart():
    ev = _paired_evidence()
    plan = plan_response("correlation between India CPI and UK inflation", CORRELATION, XY_NUMERIC)
    assert plan.response_mode == TEXT_CHART
    assert plan.visual_required is True


# ── rules.py scoring ──────────────────────────────────────────────────────

def test_scatter_only_scored_for_xy_numeric_and_correlation_intent():
    ranked_ok = dict(score_candidates(XY_NUMERIC, 12, False, intent=CORRELATION))
    ranked_wrong_intent = dict(score_candidates(XY_NUMERIC, 12, False, intent="TREND"))
    ranked_wrong_shape = dict(score_candidates(TIME_SERIES, 12, False, intent=CORRELATION))
    assert ranked_ok.get("SCATTER") == 0.90
    assert "SCATTER" not in ranked_wrong_intent
    assert "SCATTER" not in ranked_wrong_shape


# ── end-to-end orchestrator routing ──────────────────────────────────────

def test_correlation_query_routes_to_scatter_with_real_pearson_r():
    q = "What is the correlation between India CPI and UK inflation?"
    ev = _paired_evidence(correlated=True)
    plan = plan_response(q, classify_intent(q), classify_data_shape(ev, classify_intent(q)))
    result = VisualizationOrchestrator().decide(ev, XY_NUMERIC, plan, "spec-scatter-e2e", query=q)
    assert result.selected == "SCATTER"
    assert result.spec is not None
    assert len(result.spec.scatter) == 12
    assert result.spec.correlation_coefficient == 1.0  # exactly linear synthetic data


def test_uncorrelated_data_yields_low_real_r_not_fabricated():
    q = "Is India CPI correlated with UK inflation?"
    ev = _paired_evidence(correlated=False)
    plan = plan_response(q, classify_intent(q), classify_data_shape(ev, classify_intent(q)))
    result = VisualizationOrchestrator().decide(ev, XY_NUMERIC, plan, "spec-scatter-uncorr", query=q)
    assert result.selected == "SCATTER"
    assert -1.0 <= result.spec.correlation_coefficient <= 1.0
    assert abs(result.spec.correlation_coefficient) < 0.9  # genuinely weak, not overstated


def test_scatter_spec_passes_validator():
    q = "correlation between India CPI and UK inflation"
    ev = _paired_evidence()
    plan = plan_response(q, classify_intent(q), classify_data_shape(ev, classify_intent(q)))
    result = VisualizationOrchestrator().decide(ev, XY_NUMERIC, plan, "spec-scatter-valid", query=q)
    outcome = VisualizationValidator().validate(result.spec)
    assert outcome.passed
    assert outcome.failures == []


def test_below_minimum_points_does_not_route_to_scatter():
    q = "correlation between India CPI and UK inflation"
    ev = _paired_evidence(n=2)
    plan = plan_response(q, classify_intent(q), TIME_SERIES)
    result = VisualizationOrchestrator().decide(ev, XY_NUMERIC, plan, "spec-scatter-min", query=q)
    assert result.selected != "SCATTER"


# ── registry ──────────────────────────────────────────────────────────────

def test_scatter_registered_with_echarts_renderer():
    assert renderer_for("SCATTER") == "ECHARTS"


def test_scatter_fallback_order_is_table_then_text():
    assert fallbacks_for("SCATTER") == ["TABLE", "TEXT"]
