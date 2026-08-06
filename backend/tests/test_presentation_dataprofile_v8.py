"""Dynamic Visualization Selection v8 preference ranking guarantees."""
from app.orchestration.presentation_dataprofile import AnalyticalIntent, DataProfile, select_chart_with_alternatives


def _comparison_profile() -> DataProfile:
    return DataProfile(
        dimensions=("Entity",), measures=("Plan", "Actual"), category_count=5,
        measure_count=2, observation_count=10, numeric_measure_count=2,
        contains_paired_measures=True,
    )


def test_no_preference_preserves_v7_selection_exactly():
    profile = _comparison_profile()
    before = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare plan and actual")
    after = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare plan and actual", preferred_chart_type=None)
    assert before == after


def test_compatible_saved_preference_promotes_registry_candidate():
    selection = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, _comparison_profile(), "compare plan and actual",
        preferred_chart_type="dumbbell",
    )
    assert selection.chart_type == "dumbbell"


def test_incompatible_saved_preference_is_ignored():
    baseline = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, _comparison_profile(), "compare plan and actual")
    preferred = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, _comparison_profile(), "compare plan and actual",
        preferred_chart_type="radar",
    )
    assert preferred.chart_type == baseline.chart_type


def test_explicit_compatible_request_overrides_saved_preference():
    selection = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, _comparison_profile(), "show a grouped bar chart",
        preferred_chart_type="dumbbell",
    )
    assert selection.chart_type == "grouped_bar"
    assert selection.selection_source.value == "explicit_user_request"
