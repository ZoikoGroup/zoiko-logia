"""Tests for Dynamic Visualization Selection v5 — bringing temporal
(line/area) and composition (donut/composition_bar, stacked_bar/
percentage_stacked_bar) charts into the deterministic candidate and "Try
another view" system without changing any existing default selection.

Organized in four layers, narrowest to broadest:
  A. DataProfile — the 9 new v5 fields, computed from raw table cells.
  B. Registry compatibility — VisualizationSpec / _is_compatible directly,
     via hand-constructed DataProfiles (matches the existing v1-v4 style in
     test_presentation_dataprofile.py).
  C. select_family_alternatives — the v5 equivalent of
     select_chart_with_alternatives, unit-tested directly.
  D. build_answer_presentation — full pipeline, end-to-end.
  E. Telemetry chart_family plumbing.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select as sa_select

from app.core.database import AsyncSessionLocal
from app.orchestration.models import VisualizationTelemetryEvent
from app.orchestration.presentation import build_answer_presentation
from app.orchestration.presentation_dataprofile import (
    SINGLE_TOTAL_COMPOSITION_PREFERENCE,
    TEMPORAL_PREFERENCE,
    AnalyticalIntent,
    DataProfile,
    _compatible_candidates,
    _is_compatible,
    _SPEC_BY_TYPE,
    chart_family,
    compute_data_profile,
    select_family_alternatives,
)
from app.orchestration.schemas import PresentationChart, VisualizationTelemetryRequest
from app.orchestration.visualization_telemetry import record_visualization_event


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ── A. DataProfile — v5 field computation ───────────────────────────────

def test_quarter_sequence_recognized_as_ordered_and_gapless():
    headers = ["Quarter", "Revenue", "Expenses"]
    rows = [["Q1", "120000", "90000"], ["Q2", "135000", "92000"]]
    numeric_cells = {1: [("120000", "$"), ("135000", "$")], 2: [("90000", "$"), ("92000", "$")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.time_point_count == 2
    assert profile.temporal_series_count == 2
    assert profile.time_interval_consistent is True
    assert profile.contains_missing_periods is False
    assert profile.series_are_additive is True


def test_gapped_quarter_sequence_flagged_as_missing_periods_not_consistent():
    headers = ["Quarter", "Revenue"]
    rows = [["Q1", "100"], ["Q3", "120"]]
    numeric_cells = {1: [("100", "$"), ("120", "$")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.time_interval_consistent is False
    assert profile.contains_missing_periods is True


def test_unordered_recognized_labels_claim_neither_consistent_nor_gapped():
    # A conservative "don't invent facts" default: an unordered sequence
    # can't honestly be called consistent OR described by a specific gap
    # pattern, so both flags stay False rather than guessing.
    headers = ["Quarter", "Revenue"]
    rows = [["Q2", "100"], ["Q1", "120"]]
    numeric_cells = {1: [("100", "$"), ("120", "$")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.time_interval_consistent is False
    assert profile.contains_missing_periods is False


def test_unrecognized_temporal_labels_never_claim_ordering():
    headers = ["Period", "Revenue"]
    rows = [["FY24-Q1 (Jan-Mar)", "100"], ["FY24-Q2 (Apr-Jun)", "120"]]
    numeric_cells = {1: [("100", "$"), ("120", "$")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.time_interval_consistent is False
    assert profile.contains_missing_periods is False


def test_mixed_unit_series_are_not_additive():
    headers = ["Quarter", "Revenue", "Headcount"]
    rows = [["Q1", "120000", "42"], ["Q2", "135000", "45"]]
    numeric_cells = {1: [("120000", "$"), ("135000", "$")], 2: [("42", "people"), ("45", "people")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.series_are_additive is False


def test_single_measure_positive_total_forms_a_meaningful_whole():
    headers = ["Category", "Amount"]
    rows = [["Payroll", "150000"], ["Tech", "60000"], ["Rent", "30000"]]
    numeric_cells = {1: [("150000", "$"), ("60000", "$"), ("30000", "$")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.categories_form_meaningful_whole is True
    assert profile.contains_zero_total_group == False


def test_zero_total_group_flagged_and_excluded_from_meaningful_whole():
    headers = ["Category", "A", "B"]
    rows = [["X", "10", "5"], ["Y", "0", "0"]]
    numeric_cells = {1: [("10", "$"), ("0", "$")], 2: [("5", "$"), ("0", "$")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.contains_zero_total_group is True
    assert profile.group_totals_positive is False


def test_multi_measure_composition_group_count_matches_measure_count():
    headers = ["Product", "Q1", "Q2"]
    rows = [["Widgets", "10", "20"]]
    numeric_cells = {1: [("10", "$")], 2: [("20", "$")]}
    profile = compute_data_profile(headers, rows, numeric_cells)
    assert profile.composition_group_count == 2


# ── B. Registry compatibility ────────────────────────────────────────────

def test_line_compatible_with_ordered_temporal_two_points():
    profile = DataProfile(
        dimensions=("Quarter",), measures=("Revenue",), category_count=2, measure_count=1,
        contains_time=True, time_point_count=2, time_interval_consistent=True,
    )
    assert _is_compatible(_SPEC_BY_TYPE["line"], profile) is True


def test_line_incompatible_with_a_single_time_point():
    profile = DataProfile(
        dimensions=("Quarter",), measures=("Revenue",), category_count=1, measure_count=1,
        contains_time=True, time_point_count=1, time_interval_consistent=False,
    )
    assert _is_compatible(_SPEC_BY_TYPE["line"], profile) is False


def test_line_incompatible_when_temporal_ordering_was_never_verified():
    profile = DataProfile(
        dimensions=("Period",), measures=("Revenue",), category_count=3, measure_count=1,
        contains_time=True, time_point_count=3, time_interval_consistent=False, contains_missing_periods=False,
    )
    assert _is_compatible(_SPEC_BY_TYPE["line"], profile) is False


def test_area_requires_additive_or_single_series():
    non_additive = DataProfile(
        dimensions=("Quarter",), measures=("Revenue", "Headcount"), category_count=3, measure_count=2,
        contains_time=True, time_point_count=3, time_interval_consistent=True, series_are_additive=False,
    )
    assert _is_compatible(_SPEC_BY_TYPE["area"], non_additive) is False
    # ... but line has no such requirement — the whole point of offering it
    # as the safer alternative for exactly this shape.
    assert _is_compatible(_SPEC_BY_TYPE["line"], non_additive) is True


def test_area_compatible_with_single_series_regardless_of_additivity_flag():
    profile = DataProfile(
        dimensions=("Year",), measures=("GDP growth",), category_count=5, measure_count=1,
        contains_time=True, time_point_count=5, time_interval_consistent=True,
    )
    assert _is_compatible(_SPEC_BY_TYPE["area"], profile) is True


def test_donut_requires_a_meaningful_whole():
    profile = DataProfile(
        dimensions=("Category",), measures=("Amount",), category_count=3, measure_count=1,
        categories_form_meaningful_whole=False,
    )
    assert _is_compatible(_SPEC_BY_TYPE["donut"], profile) is False


def test_donut_rejects_high_cardinality_same_as_existing_part_to_whole_cap():
    profile = DataProfile(
        dimensions=("Category",), measures=("Amount",), category_count=9, measure_count=1,
        categories_form_meaningful_whole=True,
    )
    assert _is_compatible(_SPEC_BY_TYPE["donut"], profile) is False


def test_composition_bar_tolerates_higher_cardinality_than_donut():
    profile = DataProfile(
        dimensions=("Category",), measures=("Amount",), category_count=9, measure_count=1,
        categories_form_meaningful_whole=True,
    )
    assert _is_compatible(_SPEC_BY_TYPE["composition_bar"], profile) is True


def test_percentage_stacked_bar_rejects_zero_total_group():
    profile = DataProfile(
        dimensions=("Product",), measures=("Revenue", "Cost"), category_count=3, measure_count=2,
        part_to_whole_valid=True, contains_zero_total_group=True,
    )
    assert _is_compatible(_SPEC_BY_TYPE["percentage_stacked_bar"], profile) is False


def test_percentage_stacked_bar_still_rejects_negative_values():
    profile = DataProfile(
        dimensions=("Product",), measures=("Revenue", "Cost"), category_count=3, measure_count=2,
        part_to_whole_valid=False, contains_negative_values=True,
    )
    assert _is_compatible(_SPEC_BY_TYPE["percentage_stacked_bar"], profile) is False


def test_percentage_stacked_bar_still_compatible_when_positive_and_within_limits():
    # Regression: adding requires_positive_group_totals must not disturb the
    # pre-existing, already-passing compatibility path (a hand-built
    # DataProfile that never sets contains_zero_total_group explicitly).
    profile = DataProfile(
        dimensions=("Product",), measures=("Revenue", "Cost"), category_count=3, measure_count=2,
        part_to_whole_valid=True,
    )
    assert _is_compatible(_SPEC_BY_TYPE["percentage_stacked_bar"], profile) is True


def test_stacked_bar_is_unaffected_by_zero_total_group():
    # Only percentage_stacked_bar normalizes to 100% (where a zero-total
    # group is genuinely undefined); plain stacked_bar preserves absolute
    # totals and has no such rejection.
    profile = DataProfile(
        dimensions=("Product",), measures=("Revenue", "Cost"), category_count=3, measure_count=2,
        contains_zero_total_group=True,
    )
    assert _is_compatible(_SPEC_BY_TYPE["stacked_bar"], profile) is True


# ── C. select_family_alternatives ────────────────────────────────────────

def test_default_is_returned_verbatim_even_when_not_itself_compatible():
    profile = DataProfile(
        dimensions=("Period",), measures=("Revenue",), category_count=3, measure_count=1,
        contains_time=True, time_point_count=3, time_interval_consistent=False,
    )
    selection = select_family_alternatives("area", TEMPORAL_PREFERENCE, AnalyticalIntent.TREND, profile)
    assert selection.chart_type == "area"
    assert selection.alternatives == ()


def test_compatible_temporal_default_offers_the_other_family_member():
    profile = DataProfile(
        dimensions=("Quarter",), measures=("Revenue",), category_count=4, measure_count=1,
        contains_time=True, time_point_count=4, time_interval_consistent=True,
    )
    selection = select_family_alternatives("area", TEMPORAL_PREFERENCE, AnalyticalIntent.TREND, profile)
    assert selection.chart_type == "area"
    assert selection.alternatives == ("line",)


def test_explicit_compatible_line_request_overrides_the_area_default():
    profile = DataProfile(
        dimensions=("Quarter",), measures=("Revenue",), category_count=4, measure_count=1,
        contains_time=True, time_point_count=4, time_interval_consistent=True,
    )
    selection = select_family_alternatives(
        "area", TEMPORAL_PREFERENCE, AnalyticalIntent.TREND, profile, query="Show this as a line chart",
    )
    assert selection.chart_type == "line"
    assert selection.alternatives == ("area",)
    assert selection.explicit_request_invalid is False


def test_explicit_incompatible_request_keeps_the_safe_default_with_a_flag():
    profile = DataProfile(
        dimensions=("Period",), measures=("Revenue",), category_count=3, measure_count=1,
        contains_time=True, time_point_count=3, time_interval_consistent=False,
    )
    selection = select_family_alternatives(
        "area", TEMPORAL_PREFERENCE, AnalyticalIntent.TREND, profile, query="Show this as a line chart",
    )
    assert selection.chart_type == "area"
    assert selection.explicit_request_invalid is True
    assert selection.requested_chart_type == "line"


def test_non_additive_multi_series_excludes_area_but_keeps_line_reachable():
    profile = DataProfile(
        dimensions=("Quarter",), measures=("Revenue", "Headcount"), category_count=3, measure_count=2,
        contains_time=True, time_point_count=3, time_interval_consistent=True, series_are_additive=False,
    )
    candidates = _compatible_candidates(TEMPORAL_PREFERENCE, profile)
    assert candidates == ("line",)
    selection = select_family_alternatives(
        "area", TEMPORAL_PREFERENCE, AnalyticalIntent.TREND, profile, query="Show this as a line chart",
    )
    assert selection.chart_type == "line"


def test_donut_default_offers_composition_bar_alternative():
    profile = DataProfile(
        dimensions=("Category",), measures=("Amount",), category_count=3, measure_count=1,
        part_to_whole_valid=True, categories_form_meaningful_whole=True,
    )
    selection = select_family_alternatives(
        "donut", SINGLE_TOTAL_COMPOSITION_PREFERENCE, AnalyticalIntent.COMPOSITION, profile,
    )
    assert selection.chart_type == "donut"
    assert selection.alternatives == ("composition_bar",)


def test_explicit_composition_bar_request_overrides_donut_default():
    profile = DataProfile(
        dimensions=("Category",), measures=("Amount",), category_count=3, measure_count=1,
        part_to_whole_valid=True, categories_form_meaningful_whole=True,
    )
    selection = select_family_alternatives(
        "donut", SINGLE_TOTAL_COMPOSITION_PREFERENCE, AnalyticalIntent.COMPOSITION, profile,
        query="Show this as a composition bar",
    )
    assert selection.chart_type == "composition_bar"
    assert selection.alternatives == ("donut",)


# ── D. build_answer_presentation — full pipeline ─────────────────────────

def test_existing_temporal_defaults_are_bit_for_bit_unchanged():
    plan = build_answer_presentation(
        "Show revenue by quarter",
        "| Quarter | Revenue | Expenses |\n|---|---:|---:|\n"
        "| Q1 | $120,000 [REF-1] | $90,000 [REF-1] |\n| Q2 | $135,000 [REF-1] | $92,000 [REF-1] |",
    )
    assert plan.charts[0].type == "area"
    assert plan.charts[0].alternatives == ["line"]


def test_explicit_line_chart_request_selects_line_with_area_as_alternative():
    plan = build_answer_presentation(
        "Show revenue by quarter as a line chart",
        "| Quarter | Revenue |\n|---|---:|\n| Q1 | $120,000 [REF-1] |\n| Q2 | $135,000 [REF-1] |\n"
        "| Q3 | $128,000 [REF-1] |",
    )
    chart = plan.charts[0]
    assert chart.type == "line"
    assert chart.original_chart_type == "line"
    assert chart.alternatives == ["area"]
    assert chart.fallback_note is None


def test_unrecognized_temporal_labels_fall_back_safely_with_no_alternatives():
    plan = build_answer_presentation(
        "Show revenue by period",
        "| Period | Revenue |\n|---|---:|\n"
        "| FY24-P1 | $120,000 [REF-1] |\n| FY24-P2 | $128,000 [REF-1] |",
    )
    chart = plan.charts[0]
    assert chart.type == "area"
    assert chart.alternatives == []


def test_dual_axis_temporal_answers_still_have_no_alternatives():
    plan = build_answer_presentation(
        "Show revenue and margin by quarter",
        "| Quarter | Revenue | Margin |\n|---|---:|---:|\n"
        "| Q1 | $120,000 [REF-1] | 12% [REF-1] |\n| Q2 | $135,000 [REF-1] | 14% [REF-1] |",
    )
    chart = plan.charts[0]
    assert chart.type == "dual_axis"
    assert chart.alternatives == []


def test_existing_donut_default_unchanged_and_offers_composition_bar():
    plan = build_answer_presentation(
        "Visualize the tax expense breakdown by category.",
        "| Category | Amount |\n|---|---:|\n| Current tax | 80000 |\n| Deferred tax | 20000 |",
    )
    chart = plan.charts[0]
    assert chart.type == "donut"
    assert chart.alternatives == ["composition_bar"]


def test_explicit_composition_bar_request_selects_it_with_donut_as_alternative():
    plan = build_answer_presentation(
        "Visualize the tax expense breakdown by category as a composition bar.",
        "| Category | Amount |\n|---|---:|\n| Current tax | 80000 |\n| Deferred tax | 20000 |",
    )
    chart = plan.charts[0]
    assert chart.type == "composition_bar"
    assert chart.alternatives == ["donut"]


def test_zero_total_composition_group_rejects_donut_and_falls_back_to_bar():
    plan = build_answer_presentation(
        "Visualize the tax expense breakdown by category.",
        "| Category | Amount |\n|---|---:|\n| Current tax | 80000 |\n| Deferred tax | 0 |",
    )
    chart = plan.charts[0]
    assert chart.type == "bar"
    assert chart.alternatives == []


def test_high_cardinality_composition_still_falls_back_to_plain_bar_with_no_alternatives():
    rows = "\n".join(f"| Category {i} | {1000 + i} |" for i in range(9))
    plan = build_answer_presentation(
        "Visualize the expense breakdown by category.",
        f"| Category | Amount |\n|---|---:|\n{rows}",
    )
    chart = plan.charts[0]
    assert chart.type == "bar"
    assert chart.alternatives == []


def test_grouped_composition_still_offers_stacked_alternatives_after_family_reclassification():
    plan = build_answer_presentation(
        "Visualize the revenue and cost composition by product.",
        "| Product | Revenue | Cost |\n|---|---:|---:|\n"
        "| Widgets | 100000 | 60000 |\n| Gadgets | 80000 | 50000 |\n| Gizmos | 60000 | 40000 |",
    )
    chart = plan.charts[0]
    assert chart.type == "percentage_stacked_bar"
    assert chart.alternatives == ["stacked_bar"]


# ── E. Telemetry chart_family plumbing ───────────────────────────────────

def test_chart_family_helper_covers_all_v5_types():
    assert chart_family("line") == "temporal_series"
    assert chart_family("area") == "temporal_series"
    assert chart_family("donut") == "single_total_composition"
    assert chart_family("composition_bar") == "single_total_composition"
    assert chart_family("stacked_bar") == "multi_group_composition"
    assert chart_family("percentage_stacked_bar") == "multi_group_composition"
    assert chart_family("dual_axis") is None
    assert chart_family(None) is None


def test_telemetry_request_schema_accepts_chart_family():
    request = VisualizationTelemetryRequest(event_name="alternative_view_selected", chart_family="temporal_series")
    assert request.chart_family == "temporal_series"


def test_legacy_telemetry_payload_without_chart_family_still_validates():
    request = VisualizationTelemetryRequest(event_name="visualization_saved")
    assert request.chart_family is None


def test_composition_bar_is_a_valid_presentation_chart_type():
    chart = PresentationChart(
        chart_id="c1", title="Breakdown", type="composition_bar",
        categories=["A", "B"], series=[{"name": "Amount", "values": ["10", "20"], "unit": "$"}],
    )
    assert chart.type == "composition_bar"


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_telemetry_persists_chart_family_for_a_temporal_selection(db):
    conversation_id = _unique("conv")
    await record_visualization_event(
        db, event_name="visualization_selected", tenant_id=_unique("tenant"), actor_id=_unique("user"),
        conversation_id=conversation_id, query_id="q1", analytical_intent="trend",
        original_chart_type="area", active_chart_type="area", alternative_count=1,
        selection_source="deterministic_default", renderer="recharts", schema_version="1.0",
        chart_family=chart_family("area"),
    )
    result = await db.execute(
        sa_select(VisualizationTelemetryEvent).where(VisualizationTelemetryEvent.conversation_id == conversation_id)
    )
    row = result.scalar_one()
    assert row.chart_family == "temporal_series"


@pytest.mark.asyncio
async def test_telemetry_payload_never_carries_chart_values_or_query_text(db):
    # Structural privacy check, same posture as v4's own signature test —
    # chart_family is a category label ("temporal_series"), never raw data.
    import inspect
    parameters = set(inspect.signature(record_visualization_event).parameters)
    assert "chart_family" in parameters
    forbidden = {"query", "answer", "categories", "series", "chart_values"}
    assert parameters.isdisjoint(forbidden)
