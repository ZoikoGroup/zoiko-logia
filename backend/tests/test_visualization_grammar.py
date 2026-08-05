import pytest
from pydantic import ValidationError

from app.domains.reference_data.user_provided_data import compose_user_provided_results
from app.orchestration.presentation import build_answer_presentation
from app.orchestration.schemas import VisualizationGrammar, VisualizationLayer


def _chart(query: str):
    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None
    presentation = build_answer_presentation(query, answer)
    assert presentation.charts
    return presentation.charts[0]


def test_layered_query_builds_reference_only_governed_grammar():
    chart = _chart(
        "Show a combined bar and line chart: North: revenue $1000, margin 20%; "
        "South: revenue $1200, margin 22%; West: revenue $900, margin 18%."
    )
    assert chart.grammar is not None
    assert chart.grammar.composition == "layer"
    assert [layer.mark for layer in chart.grammar.layers] == ["bar", "line"]
    assert [layer.axis for layer in chart.grammar.layers] == ["primary", "secondary"]
    assert chart.grammar.fallback_chart_type == chart.type
    payload = chart.grammar.model_dump()
    assert "values" not in payload and "code" not in payload


def test_small_multiples_query_builds_facets_from_validated_series():
    chart = _chart(
        "Compare as small multiples: North: quality 80, speed 70, reliability 90; "
        "South: quality 75, speed 85, reliability 80; West: quality 90, speed 65, reliability 85."
    )
    assert chart.grammar is not None
    assert chart.grammar.composition == "facet"
    assert len(chart.grammar.layers) == 3
    assert chart.grammar.facet_columns == 2


def test_grammar_rejects_unknown_marks_and_out_of_range_references():
    with pytest.raises(ValidationError):
        VisualizationLayer(mark="script", series_index=0)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        VisualizationGrammar(
            composition="layer",
            layers=[VisualizationLayer(mark="bar", series_index=16)],
        )


def test_ordinary_chart_keeps_legacy_renderer_contract():
    chart = _chart("Show a bar chart: North $100; South $120; West $90.")
    assert chart.grammar is None


def test_year_named_measures_are_preserved_for_slope_selection():
    chart = _chart(
        "Show a slope chart: Product A: 2025 100, 2026 125; "
        "Product B: 2025 90, 2026 82; Product C: 2025 70, 2026 95."
    )
    assert chart.type == "slope"
    assert [series.name for series in chart.series] == ["2025", "2026"]


def test_negative_bubble_size_is_retained_then_rejected_by_profile():
    answer = compose_user_provided_results(
        "Show a bubble chart: A: price 10, sales 50, size -2; "
        "B: price 20, sales 70, size 5; C: price 30, sales 90, size 8.",
        "REF-1",
    )
    assert answer is not None and "-2" in answer
    presentation = build_answer_presentation("Show a bubble chart with this data", answer)
    assert presentation.charts
    assert presentation.charts[0].type != "bubble"


def test_ranking_language_selects_lollipop_instead_of_generic_bar():
    chart = _chart(
        "Rank product sales from highest to lowest: Alpha 820, Beta 1,150, "
        "Gamma 740, Delta 1,320 and Epsilon 960."
    )
    assert chart.type == "lollipop"
