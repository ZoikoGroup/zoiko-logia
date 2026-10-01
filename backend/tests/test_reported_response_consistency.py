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


def test_question_naming_its_own_countries_never_reuses_previous_evidence():
    # Reported live: a failed inflation lookup charted the previous turn's
    # India GDP series because "show it as a chart" read as a follow-up.
    assert not _should_reuse_previous_evidence(
        "Compare inflation in India, the US and the UK for the last 3 years, and show it as a chart."
    )


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


def test_dbnomics_source_carries_a_structured_observation_not_just_prose():
    """A single series has exactly one latest value, so it must be published as a
    LiveObservation rather than left to be re-parsed out of English.

    This was the last large live-data path shipping prose with
    observation=None. The failure is quiet rather than loud: the query resolved,
    the values were correct, the chart rendered - and nothing downstream could
    read the number, unit or period without parsing the snippet. Measured live
    before the fix, "Ireland unemployment rate" returned a source whose
    observation was None.
    """
    source = _build_source(SeriesMatch(
        series_name="Harmonised unemployment - monthly rates > Total > All persons",
        points=[("2023-11", 4.8), ("2023-12", 4.9)],
        url="https://example.test/series",
        provider_name="OECD",
        dataset_name="Labour Force Survey",
    ))
    observation = source.observation
    assert observation is not None, "single-series DBnomics results must be structured"
    assert observation.value == "4.9", "must be the LAST point, not the first"
    assert observation.period == "2023-12"
    assert observation.provider == "OECD"
    assert observation.source_url == source.url
    assert observation.freshness == source.freshness
    assert observation.observation_id.startswith("obs_")


def test_dbnomics_observation_discloses_rather_than_invents_a_unit():
    """SeriesMatch does not retain DBnomics' own unit metadata.

    Claiming "percent" for every series would be a fabricated label on GDP in
    dollars and levels; claiming nothing would hide the case where the series
    name does show one. The middle path, matching the WDI builder, is to claim
    percent only when the name itself shows a percent sign.
    """
    named_percent = _build_source(SeriesMatch(
        series_name="Monthly · Canada · CPI · Percentage change (%)",
        points=[("2025-01", 1.9)],
        url="https://example.test/series",
        provider_name="IMF",
        dataset_name="CPI",
    ))
    assert named_percent.observation.unit == "percent"

    plain = _build_source(SeriesMatch(
        series_name="Monthly · Japan · GDP in current prices",
        points=[("2024", 4210.5)],
        url="https://example.test/series",
        provider_name="IMF",
        dataset_name="WEO",
    ))
    assert plain.observation.unit == "provider-defined"


def test_dbnomics_match_with_no_points_publishes_no_observation_instead_of_raising():
    """An empty match still describes itself and must stay renderable.

    Publishing `points[-1]` unconditionally turned a previously harmless empty
    series into an IndexError, which would have crashed the whole live-data call
    rather than returning a weaker answer.
    """
    source = _build_source(SeriesMatch(
        series_name="Monthly · Some Publisher · A series that returned nothing",
        points=[],
        url="https://example.test/series",
        provider_name="OECD",
        dataset_name="Empty",
    ))
    assert source.observation is None
    assert source.series == []


def test_dbnomics_observation_never_disagrees_with_the_series_it_attaches():
    """Prose, series and observation are built from one SeriesMatch, so the
    reported value must be exactly the series tail - not a separately computed
    or rounded copy."""
    points = [("2026-01", 3.5), ("2026-02", 4.25), ("2026-03", 4.75)]
    source = _build_source(SeriesMatch(
        series_name="Monthly · Ireland · Harmonised unemployment (%)",
        points=points,
        url="https://example.test/series",
        provider_name="OECD",
        dataset_name="LFS",
    ))
    assert source.series == points
    assert source.observation.period == points[-1][0]
    assert source.observation.value == str(points[-1][1])
    assert f"{points[-1][0]}" in source.snippet


def test_correlated_pair_sources_stay_prose_only_and_are_not_given_an_observation():
    """Two series over one axis have no single value per period, so a pair must
    not claim one. This is the deliberate exception to the rule above and is
    pinned so a future "add provenance everywhere" pass does not invent a
    misleading observation here.
    """
    from app.orchestration.dbnomics import _build_pair_source

    pair = _build_pair_source(
        SeriesMatch(
            series_name="A", points=[("2025-01", 1.0)],
            url="https://example.test/a", provider_name="OECD", dataset_name="A",
        ),
        SeriesMatch(
            series_name="B", points=[("2025-01", 2.0)],
            url="https://example.test/b", provider_name="OECD", dataset_name="B",
        ),
    )
    assert pair.observation is None
    assert not pair.series, "a pair must not publish a single plotted series"


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


def test_change_that_chart_followup_keeps_previous_context():
    from app.orchestration.service import _with_previous_context

    query = "“Change that to a line chart.”"
    previous = "Revenue is ₹850,000 and expenses are ₹637,500. Calculate profit and profit margin."
    assert _should_reuse_previous_evidence(query)
    assert previous in _with_previous_context(query, previous)
    assert not _should_reuse_previous_evidence("Change that to a line chart for Japan unemployment")
