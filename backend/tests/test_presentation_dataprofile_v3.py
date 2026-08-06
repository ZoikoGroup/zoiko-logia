"""Tests for Dynamic Visualization Selection v3 — candidate generation,
deterministic scoring/ranking, explicit chart requests, and the
select_chart_with_alternatives contract used for "Try another view".
"""
from app.orchestration.presentation import build_answer_presentation
from app.orchestration.presentation_dataprofile import (
    AnalyticalIntent,
    DataProfile,
    generate_candidates,
    select_chart_type,
    select_chart_with_alternatives,
)


# ── generate_candidates ─────────────────────────────────────────────────

def test_candidate_generation_excludes_incompatible_chart_types():
    # radar needs >=3 measures; with only 2, it must never appear even
    # though it's in COMPARISON's preference list.
    profile = DataProfile(dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2)
    candidates = generate_candidates(AnalyticalIntent.COMPARISON, profile)
    assert "radar" not in candidates
    assert "grouped_bar" in candidates


def test_candidate_generation_never_returns_a_type_without_a_registry_entry():
    profile = DataProfile(dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2)
    for intent in AnalyticalIntent:
        for chart_type in generate_candidates(intent, profile):
            from app.orchestration.presentation_dataprofile import _SPEC_BY_TYPE, _is_compatible
            spec = _SPEC_BY_TYPE[chart_type]
            assert _is_compatible(spec, profile)


# ── ranking ──────────────────────────────────────────────────────────────

def test_target_versus_actual_ranks_bullet_above_unrelated_charts():
    profile = DataProfile(
        dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2,
        contains_target=True,
    )
    selection = select_chart_with_alternatives(AnalyticalIntent.TARGET_VARIANCE, profile, "budget vs actual variance")
    assert selection.chart_type == "bullet"
    ranked_types = [c.chart_type for c in selection.candidates]
    assert ranked_types.index("bullet") < ranked_types.index("grouped_bar")


def test_ranked_single_measure_comparison_ranks_lollipop_appropriately():
    profile = DataProfile(dimensions=("Department",), measures=("Spend",), category_count=5, measure_count=1)
    # lollipop isn't in COMPARISON's candidate pool unless measure_count==1
    # AND it's structurally compatible — confirm it's actually offered.
    candidates = generate_candidates(AnalyticalIntent.COMPARISON, profile)
    assert "lollipop" in candidates


def test_financial_bridge_data_ranks_waterfall_first():
    profile = DataProfile(
        dimensions=("Item",), measures=("Amount",), category_count=4, measure_count=1,
        contains_ordered_steps=True, contains_signed_deltas=True,
    )
    selection = select_chart_with_alternatives(AnalyticalIntent.FINANCIAL_MOVEMENT, profile, "walk from revenue to net income")
    assert selection.chart_type == "waterfall"
    assert selection.candidates[0].chart_type == "waterfall"


def test_two_period_comparison_can_rank_slope():
    profile = DataProfile(dimensions=("Region",), measures=("2025", "2026"), category_count=4, measure_count=2)
    selection = select_chart_with_alternatives(AnalyticalIntent.TREND, profile, "change between two periods")
    assert selection.chart_type == "slope"


def test_correlation_with_two_measures_ranks_scatter():
    profile = DataProfile(
        dimensions=("Company",), measures=("Revenue", "Headcount"), category_count=6, measure_count=2,
        contains_paired_measures=True,
    )
    selection = select_chart_with_alternatives(AnalyticalIntent.CORRELATION, profile, "correlation between revenue and headcount")
    assert selection.chart_type == "scatter"


def test_correlation_with_valid_size_measure_can_rank_bubble():
    profile = DataProfile(
        dimensions=("Company",), measures=("Revenue", "Headcount", "MarketCap"), category_count=6, measure_count=3,
        contains_paired_measures=True, contains_size_measure=True, size_values_non_negative=True,
    )
    candidates = generate_candidates(AnalyticalIntent.CORRELATION, profile)
    assert "bubble" in candidates
    selection = select_chart_with_alternatives(
        AnalyticalIntent.CORRELATION, profile, "correlation between revenue and headcount, bubble sized by market cap",
    )
    assert selection.chart_type == "bubble"


# ── explicit requests ────────────────────────────────────────────────────

def test_explicit_compatible_chart_request_wins():
    profile = DataProfile(dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2)
    selection = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare budget and actual as a dumbbell chart")
    assert selection.chart_type == "dumbbell"
    assert selection.explicit_request_invalid is False
    # The default pick is demoted into alternatives, not discarded.
    assert "grouped_bar" in selection.alternatives


def test_explicit_incompatible_request_falls_back_safely():
    profile = DataProfile(dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2)
    selection = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare budget and actual as a radar chart")
    # radar needs >=3 measures — request is incompatible, falls back to the
    # ordinary default rather than an error or a guessed chart.
    assert selection.chart_type == select_chart_type(AnalyticalIntent.COMPARISON, profile, "compare budget and actual as a radar chart")
    assert selection.explicit_request_invalid is True
    assert selection.requested_chart_type == "radar"


# ── tie-breaking ─────────────────────────────────────────────────────────

def test_tie_breaking_is_deterministic_across_repeated_calls():
    profile = DataProfile(
        dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2,
        contains_target=True,
    )
    first = select_chart_with_alternatives(AnalyticalIntent.TARGET_VARIANCE, profile, "budget vs actual variance")
    second = select_chart_with_alternatives(AnalyticalIntent.TARGET_VARIANCE, profile, "budget vs actual variance")
    assert first.chart_type == second.chart_type
    assert first.alternatives == second.alternatives
    assert [c.chart_type for c in first.candidates] == [c.chart_type for c in second.candidates]


# ── repetition penalty ───────────────────────────────────────────────────

def test_repetition_penalty_never_selects_an_incompatible_chart():
    profile = DataProfile(dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2)
    # Heavily repeat a type that ISN'T even a candidate here (radar needs
    # >=3 measures) — repetition can only affect already-compatible
    # candidates, never introduce an incompatible one.
    selection = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, profile, "compare budget and actual",
        recent_chart_types=("radar", "radar", "radar", "radar", "radar"),
    )
    assert selection.chart_type in generate_candidates(AnalyticalIntent.COMPARISON, profile)
    assert "radar" not in [c.chart_type for c in selection.candidates]


def test_repetition_penalty_is_capped_small_enough_to_never_flip_the_default_pick():
    profile = DataProfile(
        dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2,
        contains_target=True,
    )
    baseline = select_chart_with_alternatives(AnalyticalIntent.TARGET_VARIANCE, profile, "budget vs actual variance")
    repeated = select_chart_with_alternatives(
        AnalyticalIntent.TARGET_VARIANCE, profile, "budget vs actual variance",
        recent_chart_types=("bullet",) * 10,
    )
    # Even with the primary pick repeated many times, correctness (it's
    # still the single best-fit chart for target-variance-with-a-target)
    # wins — repetition nudges score, never flips the winner outright here.
    assert repeated.chart_type == baseline.chart_type


# ── alternatives count / validity ───────────────────────────────────────

def test_no_more_than_three_alternatives_are_returned():
    profile = DataProfile(dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2)
    selection = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare budget and actual")
    assert len(selection.alternatives) <= 3


def test_every_alternative_passes_registry_validation():
    from app.orchestration.presentation_dataprofile import _SPEC_BY_TYPE, _is_compatible
    profile = DataProfile(dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2)
    selection = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare budget and actual")
    for alt in selection.alternatives:
        assert _is_compatible(_SPEC_BY_TYPE[alt], profile)


def test_alternatives_are_restricted_to_the_same_chart_family():
    # Correlation with 3+ measures selects correlation_matrix (matrix
    # family) — scatter/bubble (paired_numeric family) need a different raw
    # payload shape and must never show up as an alternative.
    profile = DataProfile(
        dimensions=("Company",), measures=("Revenue", "Headcount", "Profit"), category_count=6, measure_count=3,
    )
    selection = select_chart_with_alternatives(AnalyticalIntent.CORRELATION, profile, "correlation across revenue, headcount, and profit")
    assert selection.chart_type == "correlation_matrix"
    assert "scatter" not in selection.alternatives
    assert "bubble" not in selection.alternatives
    assert selection.alternatives == ("heatmap",) or selection.alternatives == ()


def test_no_candidates_returns_none_chart_type_and_no_alternatives():
    profile = DataProfile(dimensions=("X",), measures=("Y",), category_count=1, measure_count=1)
    selection = select_chart_with_alternatives(AnalyticalIntent.TEXT_ONLY, profile, "what is accrual accounting")
    assert selection.chart_type is None
    assert selection.alternatives == ()


# ── integration through build_answer_presentation ──────────────────────

def test_end_to_end_chart_carries_alternatives_and_original_chart_type():
    plan = build_answer_presentation(
        "Visualize a comparison of budget and actual expenses by department.",
        "| Department | Budget | Actual |\n|---|---:|---:|\n"
        "| Payroll | $150000 | $158000 |\n| Technology | $60000 | $72000 |\n| Marketing | $45000 | $39000 |",
    )
    chart = plan.charts[0]
    assert chart.type == "grouped_bar"
    assert chart.original_chart_type == "grouped_bar"
    assert isinstance(chart.alternatives, list)
    assert len(chart.alternatives) <= 3
    assert chart.fallback_note is None


def test_end_to_end_explicit_request_produces_fallback_note_when_invalid():
    plan = build_answer_presentation(
        "Visualize a comparison of budget and actual expenses by department as a radar chart.",
        "| Department | Budget | Actual |\n|---|---:|---:|\n"
        "| Payroll | $150000 | $158000 |\n| Technology | $60000 | $72000 |\n| Marketing | $45000 | $39000 |",
    )
    chart = plan.charts[0]
    assert chart.type == "grouped_bar"
    assert chart.fallback_note is not None
    assert "radar" in chart.fallback_note


def test_temporal_charts_now_carry_alternatives_as_of_v5():
    # v3's boundary ("temporal charts get no alternatives at all") is
    # exactly what Dynamic Visualization Selection v5 removes — see
    # presentation_dataprofile.py's select_family_alternatives. The DEFAULT
    # pick itself is unchanged ("area", bit-for-bit as v1-v3); only the
    # alternatives/original_chart_type fields are new.
    plan = build_answer_presentation(
        "Visualize quarterly revenue.",
        "| Period | Revenue |\n|---|---:|\n| Q1 | 100000 |\n| Q2 | 120000 |\n| Q3 | 115000 |\n| Q4 | 140000 |",
    )
    chart = plan.charts[0]
    assert chart.type == "area"
    assert chart.alternatives == ["line"]
    assert chart.original_chart_type == "area"


def test_existing_donut_composition_regression_remains_fixed():
    # v5: the default itself ("donut") is still exactly what v1-v3
    # produced; it now also carries composition_bar as an alternative.
    plan = build_answer_presentation(
        "Visualize the tax expense breakdown by category.",
        "| Category | Amount |\n|---|---:|\n| Current tax | 80000 |\n| Deferred tax | 20000 |",
    )
    assert plan.charts[0].type == "donut"
    assert plan.charts[0].alternatives == ["composition_bar"]


def test_default_selection_is_bit_for_bit_unchanged_from_select_chart_type():
    # v3 must never move the DEFAULT (non-explicit) pick away from what
    # select_chart_type alone already returns.
    scenarios = [
        (AnalyticalIntent.COMPARISON, DataProfile(dimensions=("D",), measures=("A", "B"), category_count=5, measure_count=2), "compare a and b"),
        (AnalyticalIntent.COMPARISON, DataProfile(dimensions=("D",), measures=("A", "B", "C"), category_count=3, measure_count=3), "compare a, b, and c"),
        (AnalyticalIntent.DISTRIBUTION, DataProfile(dimensions=("D",), measures=("A",), category_count=3, measure_count=1, contains_distribution=True), "distribution of a"),
        (AnalyticalIntent.FLOW, DataProfile(dimensions=("D",), measures=("A",), category_count=4, measure_count=1, contains_flow=True), "ordered stages"),
    ]
    for intent, profile, query in scenarios:
        assert select_chart_with_alternatives(intent, profile, query).chart_type == select_chart_type(intent, profile, query)
