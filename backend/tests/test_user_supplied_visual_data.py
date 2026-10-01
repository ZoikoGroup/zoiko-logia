"""Regression tests for deterministic visualization data supplied in queries."""

from app.orchestration.data_shape import PART_TO_WHOLE, TIME_SERIES, classify_data_shape
from app.orchestration.extraction import extract_user_visual_evidence
from app.orchestration.intent_classifier import COMPOSITION, DISTRIBUTION, classify_intent
from app.orchestration.response_planner import plan_response
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator


def _visual(query: str):
    intent = classify_intent(query)
    evidence = extract_user_visual_evidence(query, intent)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    return intent, evidence, shape, VisualizationOrchestrator().decide(
        evidence, shape, plan, spec_id="viz-user-data", query=query,
    )


def test_user_supplied_ownership_percentages_build_exact_donut():
    query = "Create a donut chart of ownership: Founder 45%, Investors 30%, Employees 15%, and Other 10%."
    intent, evidence, shape, result = _visual(query)

    assert intent == COMPOSITION
    assert shape == PART_TO_WHOLE
    assert [item.dimension for item in evidence.composition] == ["Founder", "Investors", "Employees", "Other"]
    assert [item.value for item in evidence.composition] == [45.0, 30.0, 15.0, 10.0]
    assert result.spec is not None
    assert result.spec.type == "DONUT"
    assert all(not item.is_estimated for item in result.spec.donut)
    assert VisualizationValidator().validate(result.spec).passed


def test_doughnut_wording_is_also_composition():
    query = "Show this as a doughnut chart: Product A: 60%; Product B: 40%"
    intent, _, shape, result = _visual(query)
    assert intent == COMPOSITION
    assert shape == PART_TO_WHOLE
    assert result.spec is not None


def test_user_supplied_numeric_sample_builds_histogram():
    query = "Create a histogram for these invoice-processing times in days: 1, 2, 2, 3, 3, 3, 4, 5, 5, 7, 8, 8, 10, 12."
    intent, evidence, shape, result = _visual(query)

    assert intent == DISTRIBUTION
    assert shape == TIME_SERIES
    assert [item.value for item in evidence.observations] == [1, 2, 2, 3, 3, 3, 4, 5, 5, 7, 8, 8, 10, 12]
    assert result.spec is not None
    assert result.spec.type == "HISTOGRAM"
    assert sum(point.y for point in result.spec.data) == 14
    assert VisualizationValidator().validate(result.spec).passed


def test_ordinary_numbers_without_visual_intent_are_not_extracted():
    query = "Explain why invoice 12 was paid 30 days late: it needed approval."
    evidence = extract_user_visual_evidence(query, classify_intent(query))
    assert evidence.is_empty()


def test_invalid_composition_over_one_hundred_is_rejected():
    query = "Create a pie chart: Founder 80%, Investors 40%"
    intent = classify_intent(query)
    assert intent == COMPOSITION
    assert extract_user_visual_evidence(query, intent).is_empty()


def test_duplicate_composition_labels_are_rejected():
    query = "Create a donut chart: Founder 50%, founder 50%"
    intent = classify_intent(query)
    assert extract_user_visual_evidence(query, intent).is_empty()
