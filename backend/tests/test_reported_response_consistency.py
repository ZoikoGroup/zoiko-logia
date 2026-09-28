from app.orchestration.data_shape import TIME_SERIES, XY_NUMERIC, classify_data_shape
from app.orchestration.dbnomics import SeriesMatch, _build_source, _split_correlation_subjects, countries_in_query
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.intent_classifier import CORRELATION, TREND, classify_intent
from app.orchestration.response_planner import plan_response
from app.orchestration.service import _grounded_domain_fallback, _should_reuse_previous_evidence
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator


def _paired_evidence() -> EvidenceModel:
    periods = ["2025-01", "2025-02", "2025-03"]
    return EvidenceModel(
        subject="Germany inflation",
        secondary_subject="France inflation",
        observations=[Observation(dimension=p, value=v) for p, v in zip(periods, [2.3, 2.2, 2.1])],
        secondary_observations=[Observation(dimension=p, value=v) for p, v in zip(periods, [1.6, 0.8, 0.7])],
        sources=["source-a", "source-b"],
    )


def test_previous_evidence_reuse_requires_an_explicit_same_data_reference():
    assert _should_reuse_previous_evidence("Show the same data as a bar chart.")
    assert _should_reuse_previous_evidence("Render it as a horizontal bar chart.")
    assert not _should_reuse_previous_evidence("Show US GDP as a line chart.")


def test_standard_scatter_comparison_is_in_domain_and_splits_both_series():
    query = "Create a scatter plot comparing UK inflation and US inflation."
    assert classify_intent(query) == CORRELATION
    assert _split_correlation_subjects(query) == ("UK inflation", "US inflation")


def test_country_metadata_preserves_comparison_order():
    assert countries_in_query("Compare Germany and France inflation") == ["Germany", "France"]
    assert countries_in_query("Show Canada inflation") == ["Canada"]


def test_dbnomics_source_records_retrieval_provenance():
    source = _build_source(SeriesMatch(
        series_name="Monthly · Canada · CPI · Percentage change",
        points=[("2025-01", 1.9)],
        url="https://example.test/series",
        provider_name="International Monetary Fund",
        dataset_name="CPI",
    ))
    assert source.provider == "International Monetary Fund"
    assert source.freshness == "historical"
    assert source.fetched_at is not None


def test_live_chart_narrative_uses_latest_and_correct_direction():
    evidence = EvidenceModel(
        subject="Canada inflation",
        observations=[
            Observation(dimension="2024-07", value=2.53),
            Observation(dimension="2024-12", value=1.83),
            Observation(dimension="2025-06", value=1.859),
        ],
    )
    text = _grounded_domain_fallback("Show Canada inflation as a line chart", evidence)
    assert text is not None
    assert "decreased from 2.53 in 2024-07 to 1.859 in 2025-06" in text
    assert "minimum was 1.83 in 2024-12" in text


def test_comparison_line_keeps_both_series_and_adds_requested_table():
    query = "Compare Germany and France inflation using a table and line chart."
    evidence = _paired_evidence()
    intent = classify_intent(query)
    assert intent == TREND
    shape = classify_data_shape(evidence, intent)
    assert shape == TIME_SERIES
    result = VisualizationOrchestrator().decide(
        evidence, shape, plan_response(query, intent, shape), "comparison-line", query=query,
    )
    assert result.spec is not None
    assert result.spec.type == "LINE"
    assert [series.name for series in result.spec.series] == ["Germany inflation", "France inflation"]
    assert VisualizationValidator().validate(result.spec).passed
    assert len(result.secondary_specs) == 1
    assert result.secondary_specs[0].type == "TABLE"
    assert result.secondary_specs[0].columns == ["Period", "Germany inflation", "France inflation"]


def test_standard_scatter_routes_with_real_paired_evidence():
    query = "Create a scatter plot comparing UK inflation and US inflation."
    evidence = _paired_evidence()
    intent = classify_intent(query)
    shape = classify_data_shape(evidence, intent)
    assert shape == XY_NUMERIC
    result = VisualizationOrchestrator().decide(
        evidence, shape, plan_response(query, intent, shape), "comparison-scatter", query=query,
    )
    assert result.spec is not None
    assert result.spec.type == "SCATTER"
