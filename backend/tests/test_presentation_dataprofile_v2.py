"""Tests for Dynamic Visualization Selection v2 — the correlation and
financial_movement intents, and the eight chart types they map to.
"""
from app.orchestration.presentation import build_answer_presentation
from app.orchestration.presentation_dataprofile import (
    AnalyticalIntent,
    DataProfile,
    compute_correlation_matrix,
    compute_data_profile,
    detect_analytical_intent,
    select_chart_type,
)


# ── detect_analytical_intent ────────────────────────────────────────────

def test_heatmap_keyword_detected_as_correlation_intent():
    assert detect_analytical_intent("Show this as a heatmap by region and product.") == AnalyticalIntent.CORRELATION


def test_correlation_keyword_detected():
    assert detect_analytical_intent("Show the correlation between revenue and headcount.") == AnalyticalIntent.CORRELATION


def test_bridge_keyword_detected_as_financial_movement():
    assert detect_analytical_intent("Walk from revenue to net income.") == AnalyticalIntent.FINANCIAL_MOVEMENT


def test_movement_keyword_detected_as_financial_movement():
    # Real gap (2026-08-03): "Show the movement to ending cash" matched none
    # of bridge/waterfall/walk-from and fell through to COMPARISON — see
    # risk_classifier.py's sibling _VISUALIZATION_KEYWORDS fix for the same
    # live query, blocked one layer earlier at risk classification.
    assert detect_analytical_intent("Show the movement to ending cash.") == AnalyticalIntent.FINANCIAL_MOVEMENT


# ── compute_data_profile: v2 fields ─────────────────────────────────────

def test_contains_paired_measures_true_for_two_varying_numeric_columns():
    headers = ["Company", "Revenue", "Headcount"]
    rows = [["A", "100", "10"], ["B", "200", "20"], ["C", "150", "15"]]
    numeric_cells = {1: [("100", ""), ("200", ""), ("150", "")], 2: [("10", ""), ("20", ""), ("15", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_paired_measures is True


def test_contains_paired_measures_false_for_constant_column():
    headers = ["Company", "Revenue", "Headcount"]
    rows = [["A", "100", "10"], ["B", "100", "10"], ["C", "100", "10"]]
    numeric_cells = {1: [("100", ""), ("100", ""), ("100", "")], 2: [("10", ""), ("10", ""), ("10", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_paired_measures is False


def test_contains_paired_measures_false_for_identical_x_and_y():
    headers = ["Company", "Revenue", "AlsoRevenue"]
    rows = [["A", "100", "100"], ["B", "200", "200"], ["C", "150", "150"]]
    numeric_cells = {1: [("100", ""), ("200", ""), ("150", "")], 2: [("100", ""), ("200", ""), ("150", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_paired_measures is False


def test_contains_size_measure_and_non_negative_flag():
    headers = ["Company", "Revenue", "Headcount", "Employees"]
    rows = [["A", "100", "10", "5"], ["B", "200", "20", "8"]]
    numeric_cells = {
        1: [("100", ""), ("200", "")], 2: [("10", ""), ("20", "")], 3: [("5", ""), ("8", "")],
    }
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_size_measure is True
    assert profile.size_values_non_negative is True


def test_size_values_non_negative_false_when_third_measure_has_negatives():
    headers = ["Company", "Revenue", "Headcount", "NetChange"]
    rows = [["A", "100", "10", "-5"], ["B", "200", "20", "8"]]
    numeric_cells = {
        1: [("100", ""), ("200", "")], 2: [("10", ""), ("20", "")], 3: [("-5", ""), ("8", "")],
    }
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.size_values_non_negative is False


def test_contains_matrix_shape_for_multi_measure_multi_category_table():
    headers = ["Department", "Q1", "Q2"]
    rows = [["Payroll", "100", "110"], ["Tech", "60", "65"]]
    numeric_cells = {1: [("100", ""), ("60", "")], 2: [("110", ""), ("65", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_matrix_shape is True


def test_reconciling_bridge_flags_contains_signed_deltas():
    headers = ["Item", "Amount"]
    rows = [["Revenue", "500000"], ["COGS", "-320000"], ["Marketing", "-50000"], ["Net Income", "130000"]]
    numeric_cells = {1: [("500000", ""), ("-320000", ""), ("-50000", ""), ("130000", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_ordered_steps is True
    assert profile.contains_signed_deltas is True


def test_non_reconciling_bridge_does_not_flag_signed_deltas():
    headers = ["Item", "Amount"]
    rows = [["Revenue", "500000"], ["COGS", "-320000"], ["Marketing", "-50000"], ["Net Income", "999999"]]
    numeric_cells = {1: [("500000", ""), ("-320000", ""), ("-50000", ""), ("999999", "")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_ordered_steps is True
    assert profile.contains_signed_deltas is False


# ── compute_correlation_matrix ──────────────────────────────────────────

def test_correlation_matrix_diagonal_is_always_one():
    headers = ["Company", "Revenue", "Headcount", "Profit"]
    numeric_cells = {
        1: [("100", ""), ("200", ""), ("150", ""), ("300", "")],
        2: [("10", ""), ("20", ""), ("15", ""), ("30", "")],
        3: [("5", ""), ("15", ""), ("8", ""), ("25", "")],
    }
    labels, matrix = compute_correlation_matrix(headers, numeric_cells)
    assert labels == ["Revenue", "Headcount", "Profit"]
    for i in range(len(labels)):
        assert matrix[i][i] == "1.00"


def test_correlation_matrix_perfectly_correlated_columns_are_one():
    headers = ["Company", "Revenue", "DoubleRevenue"]
    numeric_cells = {
        1: [("100", ""), ("200", ""), ("300", "")],
        2: [("200", ""), ("400", ""), ("600", "")],
    }
    labels, matrix = compute_correlation_matrix(headers, numeric_cells)
    assert matrix[0][1] == "1.00"
    assert matrix[1][0] == "1.00"


def test_correlation_matrix_is_symmetric():
    headers = ["Company", "A", "B", "C"]
    numeric_cells = {
        1: [("10", ""), ("20", ""), ("5", ""), ("40", "")],
        2: [("5", ""), ("2", ""), ("9", ""), ("1", "")],
        3: [("7", ""), ("3", ""), ("8", ""), ("2", "")],
    }
    labels, matrix = compute_correlation_matrix(headers, numeric_cells)
    for i in range(len(labels)):
        for j in range(len(labels)):
            assert matrix[i][j] == matrix[j][i]


# ── select_chart_type: correlation ──────────────────────────────────────

def test_two_paired_measures_select_scatter():
    profile = DataProfile(
        dimensions=("Company",), measures=("Revenue", "Headcount"), category_count=6, measure_count=2,
        contains_paired_measures=True,
    )
    assert select_chart_type(AnalyticalIntent.CORRELATION, profile, "Show the correlation between revenue and headcount.") == "scatter"


def test_scatter_below_minimum_observations_falls_back_to_grouped_bar():
    profile = DataProfile(
        dimensions=("Company",), measures=("Revenue", "Headcount"), category_count=3, measure_count=2,
        contains_paired_measures=True,
    )
    assert select_chart_type(AnalyticalIntent.CORRELATION, profile, "correlation between revenue and headcount") == "grouped_bar"


def test_third_magnitude_measure_with_bubble_keyword_selects_bubble():
    profile = DataProfile(
        dimensions=("Company",), measures=("Revenue", "Headcount", "MarketCap"), category_count=6, measure_count=3,
        contains_paired_measures=True, contains_size_measure=True, size_values_non_negative=True,
    )
    query = "Show the correlation between revenue and headcount, bubble sized by market cap."
    assert select_chart_type(AnalyticalIntent.CORRELATION, profile, query) == "bubble"


def test_negative_bubble_sizes_fall_back_to_scatter():
    profile = DataProfile(
        dimensions=("Company",), measures=("Revenue", "Headcount", "NetChange"), category_count=6, measure_count=3,
        contains_paired_measures=True, contains_size_measure=True, size_values_non_negative=False,
    )
    query = "Show the correlation between revenue and headcount, bubble sized by net change."
    assert select_chart_type(AnalyticalIntent.CORRELATION, profile, query) == "scatter"


def test_heatmap_keyword_with_matrix_shape_selects_heatmap():
    profile = DataProfile(
        dimensions=("Department",), measures=("Q1", "Q2", "Q3"), category_count=5, measure_count=3,
        contains_matrix_shape=True,
    )
    assert select_chart_type(AnalyticalIntent.CORRELATION, profile, "Show this as a heatmap by department and quarter.") == "heatmap"


def test_three_measures_without_special_keywords_select_correlation_matrix():
    profile = DataProfile(
        dimensions=("Company",), measures=("Revenue", "Headcount", "Profit"), category_count=6, measure_count=3,
    )
    assert select_chart_type(AnalyticalIntent.CORRELATION, profile, "Show the correlation across revenue, headcount, and profit.") == "correlation_matrix"


def test_correlation_matrix_with_insufficient_observations_returns_none():
    profile = DataProfile(
        dimensions=("Company",), measures=("Revenue", "Headcount", "Profit"), category_count=3, measure_count=3,
    )
    assert select_chart_type(AnalyticalIntent.CORRELATION, profile, "correlation across revenue, headcount, and profit") is None


# ── select_chart_type: comparison (dumbbell / lollipop) ────────────────

def test_baseline_keyword_with_two_measures_selects_dumbbell():
    profile = DataProfile(dimensions=("Department",), measures=("Baseline", "Current"), category_count=5, measure_count=2)
    assert select_chart_type(AnalyticalIntent.COMPARISON, profile, "Compare the baseline versus current spend by department.") == "dumbbell"


def test_ranking_keyword_with_one_measure_selects_lollipop():
    profile = DataProfile(dimensions=("Department",), measures=("Spend",), category_count=5, measure_count=1)
    assert select_chart_type(AnalyticalIntent.COMPARISON, profile, "Compare and rank departments by spend, highest to lowest.") == "lollipop"


def test_comparison_without_ranking_language_still_defaults_to_bar_for_one_measure():
    profile = DataProfile(dimensions=("Department",), measures=("Spend",), category_count=5, measure_count=1)
    assert select_chart_type(AnalyticalIntent.COMPARISON, profile, "Compare department spend.") == "bar"


# ── select_chart_type: target_variance (bullet / dumbbell / diverging_bar) ──

def test_target_variance_with_target_selects_bullet():
    profile = DataProfile(
        dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2,
        contains_target=True,
    )
    assert select_chart_type(AnalyticalIntent.TARGET_VARIANCE, profile, "budget vs actual variance") == "bullet"


def test_target_variance_without_target_header_selects_diverging_bar():
    profile = DataProfile(
        dimensions=("Department",), measures=("Q1", "Q2"), category_count=5, measure_count=2,
        contains_target=False,
    )
    assert select_chart_type(AnalyticalIntent.TARGET_VARIANCE, profile, "Q1 vs Q2 variance") == "diverging_bar"


def test_bullet_never_requires_or_uses_a_third_threshold_measure():
    # Bullet's registry entry caps at exactly 2 measures — a 3rd/4th column
    # (which could tempt an "invented" good/acceptable/poor band) is never
    # consulted; bullet either works off actual+target or isn't selected.
    from app.orchestration.presentation_dataprofile import _SPEC_BY_TYPE
    bullet_spec = _SPEC_BY_TYPE["bullet"]
    assert bullet_spec.minimum_measures == 2
    assert bullet_spec.maximum_measures == 2


# ── select_chart_type: financial_movement (waterfall / dumbbell / bullet / diverging_bar / slope) ──

def test_ordered_additive_steps_select_waterfall():
    profile = DataProfile(
        dimensions=("Item",), measures=("Amount",), category_count=4, measure_count=1,
        contains_ordered_steps=True, contains_signed_deltas=True,
    )
    assert select_chart_type(AnalyticalIntent.FINANCIAL_MOVEMENT, profile, "Walk from revenue to net income.") == "waterfall"


def test_non_reconciling_waterfall_data_falls_back_to_bar():
    profile = DataProfile(
        dimensions=("Item",), measures=("Amount",), category_count=4, measure_count=1,
        contains_ordered_steps=True, contains_signed_deltas=False,
    )
    assert select_chart_type(AnalyticalIntent.FINANCIAL_MOVEMENT, profile, "Walk from revenue to net income.") == "bar"


def test_financial_movement_two_periods_with_period_language_falls_back_to_slope():
    profile = DataProfile(dimensions=("Region",), measures=("2025", "2026"), category_count=4, measure_count=2)
    assert select_chart_type(AnalyticalIntent.FINANCIAL_MOVEMENT, profile, "Walk from 2025 to 2026 revenue by region.") == "slope"


def test_financial_movement_two_periods_without_period_language_selects_dumbbell():
    profile = DataProfile(dimensions=("Region",), measures=("Baseline", "Current"), category_count=4, measure_count=2)
    assert select_chart_type(AnalyticalIntent.FINANCIAL_MOVEMENT, profile, "Show the bridge from baseline to current spend by region.") == "dumbbell"


def test_financial_movement_with_target_selects_bullet():
    profile = DataProfile(
        dimensions=("Region",), measures=("Budget", "Actual"), category_count=4, measure_count=2,
        contains_target=True,
    )
    assert select_chart_type(AnalyticalIntent.FINANCIAL_MOVEMENT, profile, "Show the bridge from budget to actual spend by region.") == "bullet"


# ── integration through build_answer_presentation ──────────────────────

def test_scatter_end_to_end():
    rows = "\n".join(f"| Company {i} | {100 + i * 10} | {10 + i} |" for i in range(1, 7))
    plan = build_answer_presentation(
        "Visualize the correlation between revenue and headcount.",
        f"| Company | Revenue | Headcount |\n|---|---:|---:|\n{rows}",
    )
    assert plan.charts[0].type == "scatter"
    assert len(plan.charts[0].series) == 2


def test_correlation_matrix_end_to_end_has_coefficients_for_every_measure():
    rows = "\n".join(f"| Company {i} | {100 + i * 10} | {10 + i} | {5 + i * 2} |" for i in range(1, 7))
    plan = build_answer_presentation(
        "Visualize the correlation across revenue, headcount, and profit.",
        f"| Company | Revenue | Headcount | Profit |\n|---|---:|---:|---:|\n{rows}",
    )
    chart = plan.charts[0]
    assert chart.type == "correlation_matrix"
    assert chart.categories == ["Revenue", "Headcount", "Profit"]
    assert len(chart.series) == 3
    assert chart.series[0].values[0] == "1.00"


def test_correlation_matrix_unit_is_never_the_source_measures_currency():
    # Live bug: the correlated measures ("Revenue", "Profit") are dollar
    # amounts, but a correlation coefficient is unitless — it must not
    # inherit "$" and render as "$0.87" in the accessible table.
    rows = "\n".join(f"| Company {i} | ${100 + i * 10} | {10 + i} | ${5 + i * 2} |" for i in range(1, 7))
    plan = build_answer_presentation(
        "Visualize the correlation across revenue, headcount, and profit.",
        f"| Company | Revenue | Headcount | Profit |\n|---|---:|---:|---:|\n{rows}",
    )
    chart = plan.charts[0]
    assert chart.type == "correlation_matrix"
    assert chart.unit == ""
    assert all(series.unit == "" for series in chart.series)


def test_waterfall_end_to_end_reconciling_bridge():
    plan = build_answer_presentation(
        "Visualize the walk from revenue to net income.",
        "| Item | Amount |\n|---|---:|\n"
        "| Revenue | 500000 |\n| COGS | -320000 |\n| Marketing | -50000 |\n| Net Income | 130000 |",
    )
    assert plan.charts[0].type == "waterfall"


def test_dumbbell_end_to_end():
    plan = build_answer_presentation(
        "Visualize a comparison of baseline versus current spend by department.",
        "| Department | Baseline | Current |\n|---|---:|---:|\n"
        "| Payroll | 150000 | 158000 |\n| Technology | 60000 | 72000 |\n| Marketing | 45000 | 39000 |",
    )
    assert plan.charts[0].type == "dumbbell"


def test_lollipop_end_to_end():
    plan = build_answer_presentation(
        "Visualize a comparison of departments by spend, ranked highest to lowest.",
        "| Department | Spend |\n|---|---:|\n| Payroll | 150000 |\n| Technology | 60000 |\n| Marketing | 45000 |",
    )
    assert plan.charts[0].type == "lollipop"


def test_bullet_end_to_end():
    plan = build_answer_presentation(
        "Visualize the budget vs actual variance by department.",
        "| Department | Budget | Actual |\n|---|---:|---:|\n"
        "| Payroll | 150000 | 158000 |\n| Technology | 60000 | 72000 |\n| Marketing | 45000 | 39000 |",
    )
    assert plan.charts[0].type == "bullet"


def test_existing_v1_and_original_chart_types_still_work_alongside_v2():
    # Regression check: v2's registry/priority changes didn't disturb the
    # already-shipped donut/grouped_bar paths.
    donut_plan = build_answer_presentation(
        "Visualize the tax expense breakdown by category.",
        "| Category | Amount |\n|---|---:|\n| Current tax | 80000 |\n| Deferred tax | 20000 |",
    )
    assert donut_plan.charts[0].type == "donut"
