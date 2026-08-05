"""Tests for Dynamic Visualization Selection v1
(app/orchestration/presentation_dataprofile.py) — unit tests for
DataProfile/AnalyticalIntent/the compatibility registry, plus integration
tests through build_answer_presentation's chart selection.
"""
from app.orchestration.presentation import build_answer_presentation
from app.orchestration.presentation_dataprofile import (
    AnalyticalIntent,
    DataProfile,
    compute_data_profile,
    detect_analytical_intent,
    select_chart_type,
)


# ── detect_analytical_intent ────────────────────────────────────────────

def test_target_variance_wins_over_generic_comparison_when_both_signals_present():
    assert detect_analytical_intent("Show budget vs actual variance by department.") == AnalyticalIntent.TARGET_VARIANCE


def test_distribution_intent_detected():
    assert detect_analytical_intent("Show the distribution of invoice amounts.") == AnalyticalIntent.DISTRIBUTION


def test_composition_intent_detected():
    assert detect_analytical_intent("Show the breakdown of expenses by category.") == AnalyticalIntent.COMPOSITION


def test_flow_intent_detected_for_funnel_phrasing():
    assert detect_analytical_intent("Show the ordered stages of our sales funnel.") == AnalyticalIntent.FLOW


def test_trend_intent_detected_for_slope_phrasing():
    assert detect_analytical_intent("Compare the change between two periods for each region.") == AnalyticalIntent.TREND


def test_unrelated_query_is_text_only_not_none():
    # detect_analytical_intent is total now — never returns None, so callers
    # never need an Optional check to know a query wasn't analytical.
    assert detect_analytical_intent("What is accrual accounting?") == AnalyticalIntent.TEXT_ONLY


# ── compute_data_profile ────────────────────────────────────────────────

def test_data_profile_flags_negative_values_and_invalidates_part_to_whole():
    headers = ["Product", "Revenue", "Profit"]
    rows = [["A", "100000", "40000"], ["B", "80000", "-5000"]]
    numeric_cells = {1: [("100000", ""), ("80000", "")], 2: [("40000", ""), ("-5000", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_negative_values is True
    assert profile.part_to_whole_valid is False


def test_data_profile_rejects_part_to_whole_above_the_cardinality_cap():
    headers = ["Category", "Amount"]
    rows = [[f"C{i}", str(i)] for i in range(9)]
    numeric_cells = {1: [(str(i), "") for i in range(9)]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.category_count == 9
    assert profile.part_to_whole_valid is False


def test_data_profile_accepts_part_to_whole_within_cap_and_no_negatives():
    headers = ["Category", "Amount"]
    rows = [["A", "100"], ["B", "200"]]
    numeric_cells = {1: [("100", ""), ("200", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.part_to_whole_valid is True


def test_data_profile_detects_target_header():
    headers = ["Department", "Budget", "Actual"]
    rows = [["Payroll", "150000", "158000"]]
    numeric_cells = {1: [("150000", "")], 2: [("158000", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_target is True


def test_data_profile_flags_contains_flow_for_monotonically_decreasing_single_measure():
    headers = ["Stage", "Count"]
    rows = [["Leads", "1000"], ["Qualified", "400"], ["Proposal", "150"], ["Won", "60"]]
    numeric_cells = {1: [("1000", ""), ("400", ""), ("150", ""), ("60", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_flow is True


def test_data_profile_rejects_contains_flow_when_values_increase():
    headers = ["Stage", "Count"]
    rows = [["Leads", "100"], ["Qualified", "400"], ["Proposal", "150"]]
    numeric_cells = {1: [("100", ""), ("400", ""), ("150", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_flow is False


def test_data_profile_contains_time_from_first_header():
    headers = ["Quarter", "Revenue"]
    rows = [["Q1", "100000"]]
    numeric_cells = {1: [("100000", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_time is True


# ── select_chart_type: comparison ───────────────────────────────────────

def test_comparison_two_measures_selects_grouped_bar():
    profile = DataProfile(dimensions=("Department",), measures=("Budget", "Actual"), category_count=3, measure_count=2)
    assert select_chart_type(AnalyticalIntent.COMPARISON, profile) == "grouped_bar"


def test_comparison_three_measures_within_limits_selects_radar():
    profile = DataProfile(dimensions=("Company",), measures=("A", "B", "C"), category_count=3, measure_count=3)
    assert select_chart_type(AnalyticalIntent.COMPARISON, profile) == "radar"


def test_comparison_too_many_radar_dimensions_falls_back_to_grouped_bar():
    profile = DataProfile(dimensions=("Company",), measures=tuple(f"M{i}" for i in range(7)), category_count=3, measure_count=7)
    assert select_chart_type(AnalyticalIntent.COMPARISON, profile) == "grouped_bar"


def test_comparison_too_many_radar_entities_falls_back_to_grouped_bar():
    profile = DataProfile(dimensions=("Company",), measures=("A", "B", "C"), category_count=6, measure_count=3)
    assert select_chart_type(AnalyticalIntent.COMPARISON, profile) == "grouped_bar"


# ── select_chart_type: composition ──────────────────────────────────────

def test_composition_within_limits_selects_percentage_stacked_bar():
    profile = DataProfile(
        dimensions=("Product",), measures=("Revenue", "Cost"), category_count=3, measure_count=2,
        part_to_whole_valid=True,
    )
    assert select_chart_type(AnalyticalIntent.COMPOSITION, profile) == "percentage_stacked_bar"


def test_composition_above_cardinality_cap_falls_back_to_stacked_bar():
    profile = DataProfile(
        dimensions=("Product",), measures=("Revenue", "Cost"), category_count=9, measure_count=2,
        part_to_whole_valid=False,
    )
    assert select_chart_type(AnalyticalIntent.COMPOSITION, profile) == "stacked_bar"


def test_composition_with_negative_values_and_no_target_falls_back_to_grouped_bar():
    profile = DataProfile(
        dimensions=("Product",), measures=("Revenue", "Profit"), category_count=3, measure_count=2,
        contains_negative_values=True, part_to_whole_valid=False,
    )
    assert select_chart_type(AnalyticalIntent.COMPOSITION, profile) == "grouped_bar"


def test_composition_with_negative_values_and_target_selects_diverging_bar():
    profile = DataProfile(
        dimensions=("Department",), measures=("Budget", "Actual"), category_count=3, measure_count=2,
        contains_negative_values=True, contains_target=True, part_to_whole_valid=False,
    )
    assert select_chart_type(AnalyticalIntent.COMPOSITION, profile) == "diverging_bar"


# ── select_chart_type: distribution ─────────────────────────────────────

def test_distribution_many_single_measure_observations_selects_histogram():
    profile = DataProfile(
        dimensions=("Invoice",), measures=("Amount",), category_count=8, measure_count=1,
        contains_distribution=True,
    )
    assert select_chart_type(AnalyticalIntent.DISTRIBUTION, profile) == "histogram"


def test_distribution_few_single_measure_observations_selects_box_plot():
    profile = DataProfile(
        dimensions=("Invoice",), measures=("Amount",), category_count=3, measure_count=1,
        contains_distribution=True,
    )
    assert select_chart_type(AnalyticalIntent.DISTRIBUTION, profile) == "box_plot"


def test_distribution_multi_measure_groups_selects_box_plot_regardless_of_row_count():
    # "Compare distributions across groups" — multiple measure columns each
    # contribute their own box, so box_plot (not histogram) is preferred
    # even with plenty of rows.
    profile = DataProfile(
        dimensions=("Invoice",), measures=("Region A", "Region B", "Region C"), category_count=20, measure_count=3,
        contains_distribution=True,
    )
    assert select_chart_type(AnalyticalIntent.DISTRIBUTION, profile) == "box_plot"


def test_histogram_without_enough_observations_falls_back_to_bar():
    profile = DataProfile(
        dimensions=("Invoice",), measures=("Amount",), category_count=2, measure_count=1,
        contains_distribution=False,
    )
    # measure_count==1 but category_count(2) < 5 -> box_plot preferred first,
    # box_plot also fails (contains_distribution False) -> falls to bar.
    assert select_chart_type(AnalyticalIntent.DISTRIBUTION, profile) == "bar"


def test_box_plot_without_sufficient_distribution_data_falls_back_to_bar():
    profile = DataProfile(
        dimensions=("Invoice",), measures=("Amount",), category_count=1, measure_count=1,
        contains_distribution=False,
    )
    assert select_chart_type(AnalyticalIntent.DISTRIBUTION, profile) == "bar"


# ── select_chart_type: flow / funnel ────────────────────────────────────

def test_flow_with_ordered_stages_selects_funnel():
    profile = DataProfile(
        dimensions=("Stage",), measures=("Count",), category_count=4, measure_count=1,
        contains_flow=True,
    )
    assert select_chart_type(AnalyticalIntent.FLOW, profile) == "funnel"


def test_flow_without_ordered_stages_falls_back_to_bar():
    profile = DataProfile(
        dimensions=("Stage",), measures=("Count",), category_count=4, measure_count=1,
        contains_flow=False,
    )
    assert select_chart_type(AnalyticalIntent.FLOW, profile) == "bar"


# ── select_chart_type: trend / slope ────────────────────────────────────

def test_trend_with_two_measures_selects_slope():
    profile = DataProfile(
        dimensions=("Region",), measures=("2025", "2026"), category_count=4, measure_count=2,
    )
    assert select_chart_type(AnalyticalIntent.TREND, profile) == "slope"


def test_trend_with_one_measure_falls_back_to_bar():
    # slope requires exactly 2 measures; its fallback grouped_bar also needs
    # >=2 and itself falls back to a plain bar of the one measure present —
    # a reasonable, non-misleading result rather than no chart at all.
    profile = DataProfile(dimensions=("Region",), measures=("Value",), category_count=4, measure_count=1)
    assert select_chart_type(AnalyticalIntent.TREND, profile) == "bar"


# ── select_chart_type: unmapped intents ─────────────────────────────────
# correlation and financial_movement are mapped as of v2 (see
# test_presentation_dataprofile_v2.py) — text_only is the only intent that
# always returns None.

def test_text_only_intent_returns_none():
    profile = DataProfile(dimensions=("X",), measures=("Y",), category_count=3, measure_count=1)
    assert select_chart_type(AnalyticalIntent.TEXT_ONLY, profile) is None


# ── integration through build_answer_presentation ──────────────────────

def test_comparison_with_two_measures_selects_grouped_bar_end_to_end():
    plan = build_answer_presentation(
        "Visualize a comparison of budget and actual expenses by department.",
        "| Department | Budget | Actual |\n|---|---:|---:|\n"
        "| Payroll | $150000 | $158000 |\n| Technology | $60000 | $72000 |\n| Marketing | $45000 | $39000 |",
    )
    assert plan.charts[0].type == "grouped_bar"


def test_comparison_with_three_measures_selects_radar_end_to_end():
    plan = build_answer_presentation(
        "Visualize a comparison of current ratio, quick ratio, and debt to equity across companies.",
        "| Company | Current Ratio | Quick Ratio | Debt To Equity |\n|---|---:|---:|---:|\n"
        "| A | 1.5 | 1.1 | 0.8 |\n| B | 2.0 | 1.6 | 0.5 |",
    )
    assert plan.charts[0].type == "radar"


def test_target_variance_with_a_target_header_selects_bullet_end_to_end():
    # v2: bullet is preferred over diverging_bar once a target-like column
    # ("Budget") is actually present — see test_presentation_dataprofile_v2.py.
    plan = build_answer_presentation(
        "Visualize the budget vs actual variance by department.",
        "| Department | Budget | Actual |\n|---|---:|---:|\n"
        "| Payroll | $150000 | $158000 |\n| Technology | $60000 | $72000 |\n| Marketing | $45000 | $39000 |",
    )
    assert plan.charts[0].type == "bullet"


def test_distribution_with_few_points_selects_box_plot_end_to_end():
    plan = build_answer_presentation(
        "Visualize the distribution of invoice amounts.",
        "| Invoice | Amount |\n|---|---:|\n| INV-1 | 1000 |\n| INV-2 | 1200 |\n| INV-3 | 900 |",
    )
    assert plan.charts[0].type == "box_plot"


def test_distribution_with_many_points_selects_histogram_end_to_end():
    rows = "\n".join(f"| INV-{i} | {900 + i * 20} |" for i in range(1, 9))
    plan = build_answer_presentation(
        "Visualize the distribution of invoice amounts.",
        f"| Invoice | Amount |\n|---|---:|\n{rows}",
    )
    assert plan.charts[0].type == "histogram"


def test_temporal_data_still_prefers_the_existing_trend_chart_over_the_new_engine():
    plan = build_answer_presentation(
        "Visualize quarterly revenue.",
        "| Period | Revenue |\n|---|---:|\n| Q1 | 100000 |\n| Q2 | 120000 |\n| Q3 | 115000 |\n| Q4 | 140000 |",
    )
    assert plan.charts[0].type == "area"


def test_existing_single_series_donut_path_is_unchanged_within_limits():
    plan = build_answer_presentation(
        "Visualize the tax expense breakdown by category.",
        "| Category | Amount |\n|---|---:|\n| Current tax | 80000 |\n| Deferred tax | 20000 |",
    )
    assert plan.charts[0].type == "donut"


def test_high_cardinality_single_series_composition_rejects_donut():
    rows = "\n".join(f"| Category {i} | {1000 * i} |" for i in range(1, 10))
    plan = build_answer_presentation(
        "Visualize the expense breakdown by category.",
        f"| Category | Amount |\n|---|---:|\n{rows}",
    )
    assert plan.charts[0].type == "bar"


def test_ordered_stage_reduction_selects_funnel_end_to_end():
    plan = build_answer_presentation(
        "Visualize the ordered stages of our sales funnel.",
        "| Stage | Count |\n|---|---:|\n| Leads | 1000 |\n| Qualified | 400 |\n| Proposal | 150 |\n| Won | 60 |",
    )
    assert plan.charts[0].type == "funnel"


def test_unordered_stages_falls_back_to_bar_end_to_end():
    plan = build_answer_presentation(
        "Visualize the ordered stages of our sales funnel.",
        "| Stage | Count |\n|---|---:|\n| Leads | 100 |\n| Qualified | 400 |\n| Proposal | 150 |\n| Won | 60 |",
    )
    assert plan.charts[0].type == "bar"


def test_two_period_entity_change_selects_slope_end_to_end():
    plan = build_answer_presentation(
        "Visualize the change between two periods for each region.",
        "| Region | 2025 | 2026 |\n|---|---:|---:|\n"
        "| North | 100000 | 130000 |\n| South | 80000 | 75000 |\n| East | 60000 | 90000 |",
    )
    assert plan.charts[0].type == "slope"


def test_different_questions_over_identical_data_select_different_visualizations():
    table = (
        "| Department | Budget | Actual |\n|---|---:|---:|\n"
        "| Payroll | $150000 | $158000 |\n| Technology | $60000 | $72000 |\n| Marketing | $45000 | $39000 |"
    )
    comparison = build_answer_presentation("Visualize a comparison of budget and actual expenses by department.", table)
    variance = build_answer_presentation("Visualize the budget vs actual variance by department.", table)
    assert comparison.charts[0].type == "grouped_bar"
    assert variance.charts[0].type == "bullet"
    assert comparison.charts[0].type != variance.charts[0].type
