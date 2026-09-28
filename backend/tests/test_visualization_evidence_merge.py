"""The merge service.py performs before the visualization runs.

Earlier tests called extract_user_visual_evidence() and the orchestrator
directly, and both were correct — but between them sits a merge step that
copies supplied evidence onto the live evidence field by field. It copied the
observation and left the target behind, so classify_data_shape saw a lone
SCALAR, the gauge capability (SCALAR_TARGET only) was never a candidate, and
the chart vanished while the answer text still described a comparison against
a target.

These tests exercise that merge with the same field assignments the service
uses, so a field added to one side and not the other fails here rather than in
the browser.
"""
from __future__ import annotations

from app.orchestration.data_shape import SCALAR_TARGET, classify_data_shape
from app.orchestration.evidence import EvidenceModel
from app.orchestration.extraction import extract_user_visual_evidence
from app.orchestration.intent_classifier import classify_intent
from app.orchestration.response_planner import plan_response
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator


def _merge_as_service_does(query: str) -> EvidenceModel:
    """Mirror of service.py's viz_evidence assembly for an empty live result."""
    intent = classify_intent(query)
    live = EvidenceModel()
    viz = live.model_copy(deep=True)
    supplied = extract_user_visual_evidence(query, intent)
    if supplied.observations and not viz.observations:
        viz.observations = supplied.observations
        viz.subject = supplied.subject
        viz.dimensions = supplied.dimensions
        viz.measures = supplied.measures
        viz.units = supplied.units
        viz.target = supplied.target
        viz.target_label = supplied.target_label
        viz.user_supplied = supplied.user_supplied
    if supplied.composition and not viz.composition:
        viz.composition = supplied.composition
        viz.composition_subject = supplied.composition_subject
        viz.composition_caveat = supplied.composition_caveat
        viz.composition_is_estimated = supplied.composition_is_estimated
        viz.user_supplied = supplied.user_supplied
    return viz


def test_the_target_survives_the_merge():
    viz = _merge_as_service_does("revenue 8.2m against a target of 10m")
    assert viz.observations, "the figure was lost"
    assert viz.target == 10_000_000, "the target was dropped, so no gauge can be selected"
    assert viz.user_supplied is True


def test_the_merged_evidence_still_draws_a_gauge():
    query = "revenue 8.2m against a target of 10m"
    viz = _merge_as_service_does(query)
    intent = classify_intent(query)
    shape = classify_data_shape(viz, intent)
    assert shape == SCALAR_TARGET
    plan = plan_response(query, intent, shape)
    result = VisualizationOrchestrator().decide(viz, shape, plan, "spec", query)
    assert result.selected == "GAUGE"
    assert result.spec is not None
    assert result.spec.target == 10_000_000


def test_every_field_the_extractor_sets_is_carried_over():
    """The guard against the next field being forgotten.

    Any attribute the extractor populates must arrive intact; a new one added
    to extraction.py without a matching line in the merge fails here.
    """
    query = "revenue 8.2m against a target of 10m"
    supplied = extract_user_visual_evidence(query, classify_intent(query)).model_dump()
    merged = _merge_as_service_does(query).model_dump()
    for field, value in supplied.items():
        if not value:
            continue
        assert merged[field] == value, f"{field!r} was lost in the merge"


def test_a_supplied_composition_keeps_its_provenance_flag():
    """Without user_supplied the narration calls a user's own percentages
    "named holders on file" — a statutory filing they are not."""
    merged = _merge_as_service_does("create a pie chart: payroll 45%, rent 30%, other 25%")
    assert merged.composition
    assert merged.user_supplied is True
