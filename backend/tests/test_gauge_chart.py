"""Gauge — a stated figure against the target it is measured by.

The first chart type reachable from a question that supplies its own numbers
without a colon-delimited payload. Both figures come from the user's sentence;
nothing is retrieved, and no benchmark is ever assumed. The guards below are
the point of the feature as much as the chart is: a gauge over a lone number
would imply a target nobody stated, which is exactly the kind of invented
comparison ZL-T0-04 forbids.
"""
from __future__ import annotations

import pytest

from app.orchestration.data_shape import SCALAR, SCALAR_TARGET, classify_data_shape
from app.orchestration.extraction import extract_user_visual_evidence
from app.orchestration.intent_classifier import classify_intent, explicit_target_pair
from app.orchestration.response_planner import plan_response
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.spec import VisualizationSpec
from app.orchestration.visualization.validator import VisualizationValidator


def _decide(query: str):
    intent = classify_intent(query)
    evidence = extract_user_visual_evidence(query, intent)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    return shape, VisualizationOrchestrator().decide(evidence, shape, plan, "spec", query)


@pytest.mark.parametrize(
    "query, actual, target, unit",
    [
        ("revenue 8.2m against a target of 10m", 8_200_000, 10_000_000, ""),
        ("Q3 revenue was $8,200,000 against a budget of $10,000,000", 8_200_000, 10_000_000, ""),
        ("collections 78% against a target of 90%", 78.0, 90.0, "%"),
        ("headcount 245 against a plan of 260", 245.0, 260.0, ""),
        ("show revenue 8.2m vs a target of 10m as a gauge", 8_200_000, 10_000_000, ""),
    ],
)
def test_the_pair_is_read_from_an_ordinary_sentence(query, actual, target, unit):
    pair = explicit_target_pair(query)
    assert pair is not None
    _label, got_actual, got_target, got_unit = pair
    assert got_actual == actual
    assert got_target == target
    assert got_unit == unit


def test_scaling_does_not_leave_a_floating_point_artefact():
    """8.2 * 1e6 is 8199999.999999999 in binary floating point, and that
    figure is shown to the reader verbatim."""
    _label, actual, _target, _unit = explicit_target_pair("revenue 8.2m against a target of 10m")
    assert actual == 8_200_000


@pytest.mark.parametrize(
    "query",
    [
        "revenue 8.2m against a target of 10m",
        "collections 78% against a target of 90%",
        "headcount 245 against a plan of 260",
    ],
)
def test_the_pipeline_draws_a_gauge(query):
    shape, result = _decide(query)
    assert shape == SCALAR_TARGET
    assert result.selected == "GAUGE"
    assert result.spec is not None
    assert VisualizationValidator().validate(result.spec).passed


def test_the_caption_reads_as_money_not_scientific_notation():
    _shape, result = _decide("revenue 8.2m against a target of 10m")
    summary = result.spec.summary or ""
    assert "8,200,000" in summary
    assert "e+" not in summary, f"scientific notation leaked into the caption: {summary}"
    assert "82.0% of target" in summary
    assert "supplied in the question" in summary


@pytest.mark.parametrize(
    "query",
    [
        "revenue was 8.2m",                        # a figure, but no target
        "what is the latest US CPI value",
        "we processed 1200 invoices in 30 days",   # two numbers, no target
        "set a target revenue for next year",      # the word, but no pair
    ],
)
def test_without_a_stated_target_no_gauge_is_drawn(query):
    """The guard that matters. A gauge needs a benchmark, and inventing one
    is precisely the failure the shape exists to prevent."""
    _shape, result = _decide(query)
    assert result.selected != "GAUGE"


def test_a_non_positive_target_is_refused():
    """A gauge is the ratio to its target; zero has no meaningful reading."""
    assert explicit_target_pair("revenue 8.2m against a target of 0") is None


def test_the_validator_rejects_a_gauge_with_no_target():
    """Belt and braces: even if a builder ever produced one, it must not pass.
    The fallback chain then degrades to a KPI tile, which shows the figure
    without implying a benchmark."""
    spec = VisualizationSpec(
        id="s", type="GAUGE", family="KPI", renderer="ECHARTS", value=10.0,
    )
    result = VisualizationValidator().validate(spec)
    assert not result.passed
    assert any("target" in failure for failure in result.failures)


def test_a_plain_scalar_still_classifies_as_scalar():
    """Adding SCALAR_TARGET must not steal the shape from ordinary single
    figures."""
    from app.orchestration.evidence import EvidenceModel, Observation

    evidence = EvidenceModel(observations=[Observation(dimension="2026", value=42.0)])
    assert classify_data_shape(evidence, "CURRENT_METRIC") == SCALAR
