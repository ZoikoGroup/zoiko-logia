"""Tests for Dynamic Visualization Selection v4 — real recent_chart_types
wired into ranking, and the safety guarantees around it: repetition can
only ever move ranked alternatives or break a genuine near-tie, never the
deterministic default, an explicit compatible request, or an incompatible
candidate.
"""
from app.orchestration.presentation import build_answer_presentation
from app.orchestration.schemas import PresentationChart
from app.orchestration.presentation_dataprofile import (
    AnalyticalIntent,
    DataProfile,
    ScoredCandidate,
    SelectionSource,
    _make_candidate_sort_key,
    chart_renderer,
    generate_candidates,
    select_chart_type,
    select_chart_with_alternatives,
)


# ── selection_source ─────────────────────────────────────────────────────

def test_deterministic_default_selection_source():
    profile = DataProfile(dimensions=("D",), measures=("A", "B"), category_count=5, measure_count=2)
    selection = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare a and b")
    assert selection.selection_source == SelectionSource.DETERMINISTIC_DEFAULT


def test_explicit_user_request_selection_source():
    profile = DataProfile(dimensions=("D",), measures=("A", "B"), category_count=5, measure_count=2)
    selection = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare a and b as a dumbbell chart")
    assert selection.selection_source == SelectionSource.EXPLICIT_USER_REQUEST


def test_safe_fallback_selection_source():
    profile = DataProfile(dimensions=("D",), measures=("A", "B"), category_count=5, measure_count=2)
    selection = select_chart_with_alternatives(AnalyticalIntent.COMPARISON, profile, "compare a and b as a radar chart")
    assert selection.selection_source == SelectionSource.SAFE_FALLBACK


def test_chart_renderer_mapping():
    assert chart_renderer("grouped_bar") == "recharts"
    assert chart_renderer("heatmap") == "echarts"
    assert chart_renderer("box_plot") == "echarts"
    assert chart_renderer("histogram") == "recharts"
    assert chart_renderer(None) is None


# ── real recent_chart_types wired end-to-end ────────────────────────────

def test_same_query_with_no_history_retains_the_v3_result_exactly():
    profile = DataProfile(
        dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2,
        contains_target=True,
    )
    without_history = select_chart_with_alternatives(AnalyticalIntent.TARGET_VARIANCE, profile, "budget vs actual variance")
    with_empty_history = select_chart_with_alternatives(
        AnalyticalIntent.TARGET_VARIANCE, profile, "budget vs actual variance", recent_chart_types=(),
    )
    assert without_history.chart_type == with_empty_history.chart_type
    assert without_history.alternatives == with_empty_history.alternatives


def test_repetition_history_does_not_override_an_explicit_compatible_request():
    profile = DataProfile(dimensions=("D",), measures=("A", "B"), category_count=5, measure_count=2)
    selection = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, profile, "compare a and b as a dumbbell chart",
        recent_chart_types=("dumbbell",) * 10,
    )
    # Even with dumbbell heavily repeated, the explicit request for it still
    # wins — repetition penalizes ranking, it never revokes an explicit ask.
    assert selection.chart_type == "dumbbell"
    assert selection.selection_source == SelectionSource.EXPLICIT_USER_REQUEST


def test_repetition_history_never_makes_an_incompatible_candidate_valid():
    # radar needs >=3 measures; repeating every OTHER candidate can't make
    # radar (never a candidate here at all) selectable.
    profile = DataProfile(dimensions=("D",), measures=("A", "B"), category_count=5, measure_count=2)
    selection = select_chart_with_alternatives(
        AnalyticalIntent.COMPARISON, profile, "compare a and b",
        recent_chart_types=("grouped_bar", "dumbbell", "diverging_bar") * 5,
    )
    assert selection.chart_type in generate_candidates(AnalyticalIntent.COMPARISON, profile)
    assert "radar" not in [c.chart_type for c in selection.candidates]


def test_end_to_end_recent_chart_types_never_change_the_default_pick():
    table = (
        "| Department | Budget | Actual |\n|---|---:|---:|\n"
        "| Payroll | $150000 | $158000 |\n| Technology | $60000 | $72000 |\n| Marketing | $45000 | $39000 |"
    )
    query = "Visualize a comparison of budget and actual expenses by department."
    no_history = build_answer_presentation(query, table)
    with_history = build_answer_presentation(query, table, recent_chart_types=("grouped_bar",) * 5)
    assert no_history.charts[0].type == with_history.charts[0].type == "grouped_bar"


# ── near-tie tie-breaking mechanism ─────────────────────────────────────
# No two currently-registered real chart types are naturally close enough
# in score (checked empirically: the closest real pair, target_variance's
# dumbbell vs diverging_bar, differs by ~0.042 — more than double
# recent_repetition_penalty's max possible swing of ~0.018) for repetition
# alone to flip their relative order today. That headroom is intentional
# (requirement: penalties must never override a real readability/fit
# difference) — so this tests the tie-break MECHANISM directly, on a
# constructed near-tie, rather than asserting behavior no real registry
# entry pair currently exhibits.

def test_near_tie_is_broken_in_favor_of_the_less_recently_shown_chart():
    intent = AnalyticalIntent.COMPARISON
    candidates = ("chart_a", "chart_b")
    sort_key = _make_candidate_sort_key(intent, requested=None, candidates=candidates)

    # Equal on every dimension that matters to the tie-break chain (same
    # intent fit — neither name is in any real preference list, so both
    # score 0.0 there — and equal complexity via the same unregistered-type
    # 0.5 default); only recent_repetition_penalty differs, mirroring what
    # _score_candidate would compute for two near-identical real types.
    fresher = ScoredCandidate(chart_type="chart_a", score=0.500, breakdown={})
    recently_shown = ScoredCandidate(chart_type="chart_b", score=0.490, breakdown={})

    ranked = sorted([recently_shown, fresher], key=sort_key)
    assert ranked[0].chart_type == "chart_a"


def test_tie_break_chain_falls_through_to_registry_order_when_fully_tied():
    intent = AnalyticalIntent.COMPARISON
    candidates = ("chart_a", "chart_b")
    sort_key = _make_candidate_sort_key(intent, requested=None, candidates=candidates)
    a = ScoredCandidate(chart_type="chart_a", score=0.5, breakdown={})
    b = ScoredCandidate(chart_type="chart_b", score=0.5, breakdown={})
    ranked = sorted([b, a], key=sort_key)
    # Fully tied on score/fit/complexity — falls back to the stable
    # candidates-tuple order (chart_a listed first), never arbitrary.
    assert ranked[0].chart_type == "chart_a"


def test_tie_breaking_is_deterministic_across_repeated_calls_with_real_history():
    profile = DataProfile(
        dimensions=("Department",), measures=("Budget", "Actual"), category_count=5, measure_count=2,
        contains_target=True,
    )
    history = ("bullet", "dumbbell", "diverging_bar")
    first = select_chart_with_alternatives(AnalyticalIntent.TARGET_VARIANCE, profile, "budget vs actual variance", history)
    second = select_chart_with_alternatives(AnalyticalIntent.TARGET_VARIANCE, profile, "budget vs actual variance", history)
    assert first.chart_type == second.chart_type
    assert first.alternatives == second.alternatives


# ── backward compatibility ──────────────────────────────────────────────

def test_old_v1_v2_payload_missing_all_v4_fields_still_validates():
    old_payload = {
        "chart_id": "answer-table-1", "type": "grouped_bar", "title": "Old chart",
        "categories": ["A", "B"], "series": [{"name": "Value", "values": ["1", "2"], "unit": "$"}],
        "unit": "$", "domain": "general", "summary_mode": "total",
        # No alternatives/original_chart_type/fallback_note/schema_version/
        # analytical_intent/selection_source — exactly a v1 payload shape.
    }
    chart = PresentationChart.model_validate(old_payload)
    assert chart.analytical_intent is None
    assert chart.selection_source is None
    assert chart.alternatives == []
