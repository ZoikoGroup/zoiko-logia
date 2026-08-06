from types import SimpleNamespace

from app.orchestration.visualization_gaps import (
    DataShapeClass, EnvironmentMarker, EvidenceStatus, VisualizationGapType,
    aggregate_gaps, classify_data_shape, evidence_status, shape_valid_for_requested_chart,
)
from app.orchestration.presentation import build_answer_presentation


def test_minimum_sample_statuses_are_exact():
    assert evidence_status(29) == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert evidence_status(30) == EvidenceStatus.DIRECTIONAL_SIGNAL
    assert evidence_status(99) == EvidenceStatus.DIRECTIONAL_SIGNAL
    assert evidence_status(100) == EvidenceStatus.ELIGIBLE_FOR_REVIEW


def test_data_shape_classification_is_deterministic():
    profile = SimpleNamespace(contains_flow=False, contains_matrix_shape=False, contains_distribution=False,
        contains_signed_deltas=False, contains_ordered_steps=False, contains_time=True, measure_count=2,
        part_to_whole_valid=False, contains_paired_measures=False, category_count=6)
    assert classify_data_shape(profile) == DataShapeClass.TEMPORAL_MULTI_SERIES


def test_shape_requirements_control_valid_evidence():
    assert shape_valid_for_requested_chart("treemap", DataShapeClass.PART_TO_WHOLE)
    assert not shape_valid_for_requested_chart("treemap", DataShapeClass.TEMPORAL_SINGLE_SERIES)


def test_aggregate_exposes_counts_only_and_low_samples_never_recommend_chart():
    events = [SimpleNamespace(valid_evidence=True, analytical_intent="composition", requested_chart_type="treemap",
        requested_visualization_family="composition", data_shape_class="part_to_whole", fallback_chart_type="donut",
        fallback_output_type="chart", gap_type=VisualizationGapType.UNSUPPORTED_PRODUCT_CAPABILITY.value,
        conversation_id=f"c{i%3}", actor_id=f"a{i%2}", environment=EnvironmentMarker.PRODUCTION.value) for i in range(10)]
    report = aggregate_gaps(events)
    assert report.rows[0].distinct_conversations == 3
    assert report.rows[0].distinct_actors == 2
    assert report.rows[0].recommended_issue_classification == "insufficient_evidence"


def test_unsupported_explicit_chart_creates_safe_gap_without_raw_content():
    collected = []
    build_answer_presentation("show this as a treemap", "| Segment | Share |\n|---|---:|\n| A | 60% |\n| B | 40% |", gap_collector=collected)
    assert collected and collected[0]["requested_chart_type"] == "treemap"
    assert collected[0]["gap_type"] == VisualizationGapType.UNSUPPORTED_PRODUCT_CAPABILITY
    assert not ({"query", "answer_text", "values", "labels", "error"} & set(collected[0]))
