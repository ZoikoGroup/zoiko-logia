"""Dynamic Visualization Selection v1 + v2 + v3.

A named, testable contract: a DataProfile schema, a closed AnalyticalIntent
enum, and a declarative VisualizationSpec registry that states what each
chart type requires and what it degrades to when the data doesn't qualify.
Still no scoring for WHICH chart is primary, no LLM, no randomness — one
deterministic chart type (or an explicit fallback, or none) per
(intent, profile, query) combination.

v2 maps the two intents v1 left unmapped (correlation, financial_movement)
and adds eight chart types: scatter, bubble, heatmap, correlation_matrix,
dumbbell, lollipop, bullet, and a PresentationChart-native waterfall (the
existing CalculationWidget waterfall — a different code path entirely — is
untouched). A few chart types (heatmap vs correlation_matrix, dumbbell vs
lollipop, bullet vs dumbbell) can't be told apart from data shape alone, so
select_chart_type also takes the raw query for a small, narrow set of
keyword tie-breaks — never a fuzzy match, never LLM-assisted, same
"one regex pattern per real query shape" posture as intent detection.

v3 adds select_chart_with_alternatives: candidate generation, a fixed-weight
deterministic scoring model, and up to three ranked, registry-valid
alternative chart types for a "Try another view" control. It deliberately
does NOT change what select_chart_type itself picks as the primary chart —
the default pick for every existing query shape is bit-for-bit unchanged
from v1/v2; v3 only adds ranked alternatives alongside it, plus an explicit
override when the query names a compatible chart type by name. See that
function's docstring for the full algorithm and the deliberate scope
boundary around temporal (line/area) and single-measure donut charts, which
stay outside the ranked-alternatives system exactly as they were outside
select_chart_type's dynamic engine in v1/v2.

AnalyticalIntent.TEXT_ONLY is the explicit "nothing chartable here" state —
detect_analytical_intent always returns a real value, never None.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class SelectionSource(str, Enum):
    """How a chart's currently-active type came to be selected — v4.
    deterministic_default/explicit_user_request/safe_fallback are decided
    here, backend-side, at answer-generation time. alternative_switch and
    legacy_payload describe states the backend can't observe (a client-side
    view switch after the fact; rendering an old saved payload with no v3
    fields) and are set by the frontend telemetry code instead — see
    presentation.py and AnswerChartFigure.tsx respectively."""
    DETERMINISTIC_DEFAULT = "deterministic_default"
    EXPLICIT_USER_REQUEST = "explicit_user_request"
    ALTERNATIVE_SWITCH = "alternative_switch"
    SAFE_FALLBACK = "safe_fallback"
    LEGACY_PAYLOAD = "legacy_payload"
    # v10 — the primary pick was nudged away from the ordinary deterministic
    # default by a consent-based personalized signal (see
    # visualization_personalization.py). Only ever set when that nudge was
    # itself a near-tie break among already-compatible candidates — never
    # when an explicit request or saved preference already decided the
    # pick, both of which are resolved first and take priority.
    PERSONALIZED = "personalized"


# Which renderer actually draws each chart type — Recharts for everything
# except the few ECharts has no Recharts equivalent for (heatmap/bullet/
# correlation_matrix have no Recharts primitive; box_plot and the
# PresentationChart-native waterfall specifically chose ECharts in v1/v2 —
# see BoxPlotChart.tsx and EChartsPresentationChart.tsx). Used only for
# telemetry's "renderer" field, never for rendering decisions themselves.
_CHART_RENDERER: dict[str, str] = {
    "bar": "recharts", "line": "recharts", "area": "recharts", "donut": "recharts", "dual_axis": "recharts",
    "grouped_bar": "recharts", "stacked_bar": "recharts", "percentage_stacked_bar": "recharts",
    "diverging_bar": "recharts", "radar": "recharts", "dumbbell": "recharts", "lollipop": "recharts",
    "histogram": "recharts", "funnel": "recharts", "slope": "recharts", "scatter": "recharts", "bubble": "recharts",
    "box_plot": "echarts", "heatmap": "echarts", "correlation_matrix": "echarts", "bullet": "echarts", "waterfall": "echarts",
    # v5.
    "composition_bar": "recharts",
}


def chart_renderer(chart_type: str | None) -> str | None:
    return _CHART_RENDERER.get(chart_type) if chart_type else None


def chart_family(chart_type: str | None) -> str | None:
    """v5 — see _CHART_FAMILY. None for chart types with no family (bar,
    dual_axis) exactly as chart_renderer returns None for an unknown type."""
    return _CHART_FAMILY.get(chart_type) if chart_type else None


class AnalyticalIntent(str, Enum):
    COMPARISON = "comparison"
    TARGET_VARIANCE = "target_variance"
    TREND = "trend"
    COMPOSITION = "composition"
    DISTRIBUTION = "distribution"
    CORRELATION = "correlation"
    FLOW = "flow"
    FINANCIAL_MOVEMENT = "financial_movement"
    TEXT_ONLY = "text_only"


@dataclass(frozen=True)
class DataProfile:
    dimensions: tuple[str, ...]
    measures: tuple[str, ...]
    category_count: int = 0
    measure_count: int = 0
    contains_time: bool = False
    contains_negative_values: bool = False
    contains_target: bool = False
    part_to_whole_valid: bool = False
    contains_distribution: bool = False
    contains_flow: bool = False
    # v2 additions — kept to exactly what the new chart types' compatibility
    # rules need, not an open-ended profiling framework.
    observation_count: int = 0
    numeric_measure_count: int = 0
    contains_paired_measures: bool = False
    contains_size_measure: bool = False
    size_values_non_negative: bool = True
    contains_matrix_shape: bool = False
    contains_ordered_steps: bool = False
    contains_start_value: bool = False
    contains_signed_deltas: bool = False
    contains_final_total: bool = False
    # v5 additions — bringing temporal (line/area) and composition
    # (donut/composition_bar/stacked_bar/percentage_stacked_bar) into the
    # same registry-validated system.
    time_point_count: int = 0
    temporal_series_count: int = 0
    time_interval_consistent: bool = False
    series_are_additive: bool = True
    contains_missing_periods: bool = False
    composition_group_count: int = 0
    group_totals_positive: bool = False
    contains_zero_total_group: bool = False
    categories_form_meaningful_whole: bool = False


# Ordered so a more specific signal is checked before a more generic one that
# would otherwise also match the same words ("variance"/"vs" also reads as a
# generic comparison; target_variance must win when both are present).
_INTENT_PATTERNS: tuple[tuple[AnalyticalIntent, re.Pattern], ...] = (
    (AnalyticalIntent.TARGET_VARIANCE, re.compile(
        r"\bvariance\b|\b(?:vs\.?|versus|against)\s+(?:target|budget|benchmark|plan|forecast)\b|"
        r"\bbudget\s+vs\.?\s+actual\b",
        re.IGNORECASE,
    )),
    (AnalyticalIntent.TREND, re.compile(
        r"\btrend\b|\bover\s+time\b|\byear[\s-]over[\s-]year\b|\bmonth[\s-]over[\s-]month\b|"
        r"\bgrowth\s+(?:over|trend)\b|\bbefore\s+(?:and|vs\.?|versus)\s+after\b|"
        r"\bchange\s+between\s+(?:two|the)\s+periods?\b|\bperiod[\s-]over[\s-]period\s+change\b|"
        r"\bslope\s+chart\b",
        re.IGNORECASE,
    )),
    (AnalyticalIntent.DISTRIBUTION, re.compile(r"\b(distribution|histogram|spread|frequency)\b", re.IGNORECASE)),
    (AnalyticalIntent.COMPOSITION, re.compile(
        r"\b(composition|breakdown|share|allocation|mix|proportion)\b", re.IGNORECASE,
    )),
    (AnalyticalIntent.CORRELATION, re.compile(
        r"\bcorrelat\w*\b|\brelationship\s+between\b|\bheat\s?map\b|\bmatrix\b|"
        r"\bscatter\b|\bbubble\s+chart\b",
        re.IGNORECASE,
    )),
    (AnalyticalIntent.FLOW, re.compile(
        r"\bordered\s+stages?\b|\bfunnel\b|\bstage\s+reduction\b|\bstage[\s-]by[\s-]stage\b", re.IGNORECASE,
    )),
    # "movement" added 2026-08-03: "Show the movement to ending cash" (a
    # fully-specified starting-balance-plus-deltas cash-flow-bridge request)
    # matched none of the existing trigger words and fell through to
    # COMPARISON's much later, weaker match — see risk_classifier.py's
    # _VISUALIZATION_KEYWORDS for the sibling fix at the risk-classification
    # layer this same live query also hit.
    (AnalyticalIntent.FINANCIAL_MOVEMENT, re.compile(r"\bbridge\b|\bwaterfall\b|\bwalk\s+from\b|\bmovement\b", re.IGNORECASE)),
    (AnalyticalIntent.COMPARISON, re.compile(
        r"\bcompare\b|\bcomparison\b|\bversus\b|\bvs\.?\b|"
        r"\brank(?:ing|ed)?\b|\bhighest\s+to\s+lowest\b|\blowest\s+to\s+highest\b",
        re.IGNORECASE,
    )),
)

_TEMPORAL_HEADER = re.compile(r"\b(?:period|quarter|month|year|date|week|day|20\d{2})\b", re.IGNORECASE)
_TARGET_HEADER = re.compile(r"\b(target|budget|benchmark|plan|forecast|goal)\b", re.IGNORECASE)

# Query-level tie-breaks between chart types that look identical from data
# shape alone. Narrow, literal, and only ever used to choose among a small
# set of candidates the intent + profile have already deemed plausible —
# never a substitute for the intent/profile compatibility checks themselves.
_HEATMAP_KEYWORDS = re.compile(r"\bheat\s?map\b", re.IGNORECASE)
_BUBBLE_KEYWORDS = re.compile(r"\bbubble\b|\bmagnitude\b|\bsized?\s+by\b|\bweighted\s+by\b", re.IGNORECASE)
_RANKING_KEYWORDS = re.compile(r"\brank(?:ed|ing)?\b|\bhighest\b|\blowest\b|\btop\b|\bbest\b|\bworst\b", re.IGNORECASE)
_BASELINE_KEYWORDS = re.compile(r"\bbaseline\b|\bprevious\b|\bprior\b", re.IGNORECASE)

# High cardinality and negative values both make a part-to-whole chart
# (donut/pie/percentage-stacked-bar) misleading or unreadable — a slice
# below zero has no sensible "share of the whole" meaning, and beyond ~8
# slices a part-to-whole chart stops being readable at a glance.
_MAX_PART_TO_WHOLE_CATEGORIES = 8

_MONTH_ORDER = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_LABEL = re.compile(
    r"^(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)$",
    re.IGNORECASE,
)
_QUARTER_LABEL = re.compile(r"^q([1-4])$", re.IGNORECASE)
_YEAR_LABEL = re.compile(r"^(\d{4})$")


def _analyze_temporal_sequence(categories: list[str]) -> tuple[bool, bool, bool]:
    """Best-effort, narrow recognition of a bare month-name, quarter
    (Q1-Q4), or 4-digit-year sequence — returns
    (recognized, chronologically_ordered, has_gaps). Deliberately never
    claims ordering or gaplessness for a pattern it doesn't positively
    recognize (e.g. "Q1 2024", ISO dates, arbitrary period labels) — that's
    the conservative, "don't invent facts" default this whole module
    follows, not a limitation to work around with a heavier date parser.
    A single time point (or fewer) is trivially "ordered" but never
    "recognized" — there's nothing to sequence."""
    if len(categories) < 2:
        return (False, False, False)
    stripped = [c.strip() for c in categories]

    month_matches = [_MONTH_LABEL.match(c) for c in stripped]
    if all(month_matches):
        indices = [_MONTH_ORDER.index(m.group(1)[:3].lower()) for m in month_matches]  # type: ignore[union-attr]
        ordered = all(indices[i] <= indices[i + 1] for i in range(len(indices) - 1))
        gaps = any((indices[i + 1] - indices[i]) % 12 not in (0, 1) for i in range(len(indices) - 1))
        return (True, ordered, gaps)

    quarter_matches = [_QUARTER_LABEL.match(c) for c in stripped]
    if all(quarter_matches):
        indices = [int(m.group(1)) for m in quarter_matches]  # type: ignore[union-attr]
        ordered = all(indices[i] <= indices[i + 1] for i in range(len(indices) - 1))
        gaps = any((indices[i + 1] - indices[i]) % 4 not in (0, 1) for i in range(len(indices) - 1))
        return (True, ordered, gaps)

    year_matches = [_YEAR_LABEL.match(c) for c in stripped]
    if all(year_matches):
        years = [int(m.group(1)) for m in year_matches]  # type: ignore[union-attr]
        ordered = all(years[i] <= years[i + 1] for i in range(len(years) - 1))
        gaps = any(years[i + 1] - years[i] != 1 for i in range(len(years) - 1))
        return (True, ordered, gaps)

    return (False, False, False)


def _is_non_increasing(values: list[str]) -> bool:
    decimals = [Decimal(v) for v in values]
    return all(decimals[i] >= decimals[i + 1] for i in range(len(decimals) - 1))


def _column_values(numeric_cells: dict[int, list[tuple[str, str] | None]], index: int) -> list[Decimal]:
    return [Decimal(cell[0]) for cell in numeric_cells[index] if cell is not None]


def _is_constant(values: list[Decimal]) -> bool:
    return len(set(values)) <= 1


def _reconciles_as_bridge(values: list[Decimal]) -> bool:
    """True if the first value plus every value in between (already signed —
    positive for an addition, negative for a deduction, matching how a
    source table would literally write a bridge) equals the last value,
    within a small tolerance for rounding in the source data."""
    if len(values) < 3:
        return False
    start, *middle, total = values
    reconciled = start + sum(middle)
    tolerance = max(abs(total) * Decimal("0.01"), Decimal("0.01"))
    return abs(reconciled - total) <= tolerance


def _measure_indices(headers: list[str], numeric_cells: dict[int, list[tuple[str, str] | None]]) -> list[int]:
    dimension_indices = {
        i for i in range(len(headers))
        if i not in numeric_cells or any(cell is None for cell in numeric_cells[i])
    }
    return [i for i in range(len(headers)) if i in numeric_cells and i not in dimension_indices]


def compute_data_profile(headers: list[str], rows: list[list[str]], numeric_cells: dict[int, list[tuple[str, str] | None]]) -> DataProfile:
    """numeric_cells maps column index -> [(value, unit) | None per row],
    reusing whatever the caller already parsed via presentation.py's own
    _numeric() rather than re-parsing — this module never re-derives facts
    from the answer text, only profiles what's already been extracted."""
    measure_indices = _measure_indices(headers, numeric_cells)
    dimension_indices = [i for i in range(len(headers)) if i not in measure_indices]

    dimensions = tuple(headers[i] for i in dimension_indices)
    measures = tuple(headers[i] for i in measure_indices)
    category_count = len(rows)
    measure_count = len(measures)

    # Time is a property of the row axis (each row a time point), not of any
    # measure column — matches presentation.py's own is_temporal check on
    # headers[0] (the caller always treats column 0 as the row dimension),
    # computed independently there since it also gates the pre-existing
    # area/dual_axis path this module must not compete with.
    contains_time = bool(headers) and bool(_TEMPORAL_HEADER.search(headers[0]))
    contains_target = any(_TARGET_HEADER.search(headers[i]) for i in measure_indices)

    contains_negative_values = any(
        Decimal(cell[0]) < 0
        for i in measure_indices
        for cell in numeric_cells[i]
        if cell is not None
    )
    part_to_whole_valid = (
        measure_count >= 1
        and not contains_negative_values
        and 0 < category_count <= _MAX_PART_TO_WHOLE_CATEGORIES
    )
    # Any single- or multi-measure table of individual rows can, in
    # principle, represent a distribution (a histogram/box-plot input) —
    # the registry's own minimum_observations per chart type is what
    # actually gates whether there's enough data to plot one meaningfully.
    contains_distribution = measure_count >= 1 and category_count >= 1
    # A funnel needs an ordered, monotonically shrinking single measure
    # (leads -> qualified -> won) — checked from the real values already
    # extracted, never inferred from header wording alone.
    contains_flow = (
        measure_count == 1
        and category_count >= 3
        and _is_non_increasing([cell[0] for cell in numeric_cells[measure_indices[0]] if cell is not None])
    )

    # v2 — scatter/correlation always use the first two measure columns as
    # x/y, rejecting the pairing outright if either is constant or the two
    # columns are literally identical (nothing to relate).
    contains_paired_measures = False
    if measure_count >= 2:
        x_values = _column_values(numeric_cells, measure_indices[0])
        y_values = _column_values(numeric_cells, measure_indices[1])
        contains_paired_measures = (
            not _is_constant(x_values) and not _is_constant(y_values) and x_values != y_values
        )

    # Bubble uses the third measure column as size.
    contains_size_measure = measure_count >= 3
    size_values_non_negative = True
    if contains_size_measure:
        size_values_non_negative = all(v >= 0 for v in _column_values(numeric_cells, measure_indices[2]))

    # A heatmap reinterprets the existing dimension x measure-columns grid
    # (already how grouped_bar/stacked_bar see the same table) as rows x
    # columns — no new table shape required, just a genuine 2D grid to grid.
    contains_matrix_shape = measure_count >= 2 and category_count >= 2

    # Waterfall: single measure, ordered rows, first value the start and
    # last value the total, middle values already signed deltas (positive
    # for an addition, negative for a deduction) that reconcile to the
    # total — checked from real values, never inferred from header wording.
    contains_ordered_steps = measure_count == 1 and category_count >= 3
    contains_start_value = measure_count == 1 and category_count >= 1
    contains_final_total = measure_count == 1 and category_count >= 2
    contains_signed_deltas = (
        contains_ordered_steps
        and _reconciles_as_bridge(_column_values(numeric_cells, measure_indices[0]))
    )

    # v5 — temporal. category values ARE the time points for a temporal
    # table (row[0] per presentation.py's own convention); recognized only
    # for the narrow month/quarter/year patterns _analyze_temporal_sequence
    # positively identifies — anything else stays "not consistent, no
    # claimed gaps", the conservative default.
    categories = [row[0] for row in rows] if rows else []
    time_point_count = category_count if contains_time else 0
    temporal_series_count = measure_count if contains_time else 0
    temporal_recognized, temporal_ordered, temporal_has_gaps = (
        _analyze_temporal_sequence(categories) if contains_time else (False, False, False)
    )
    time_interval_consistent = contains_time and temporal_recognized and temporal_ordered and not temporal_has_gaps
    contains_missing_periods = contains_time and temporal_recognized and temporal_ordered and temporal_has_gaps
    # Measures sharing one unit (or none specified) can be honestly summed
    # or area-filled together; different units cannot — same reasoning
    # presentation.py's own multi-axis guard already applies elsewhere.
    measure_units = {
        cell[1]
        for i in measure_indices
        for cell in numeric_cells[i]
        if cell is not None and cell[1]
    }
    series_are_additive = measure_count <= 1 or len(measure_units) <= 1

    # v5 — composition. A "group" is one row/category; its total is the sum
    # across that row's measure columns (what a stacked bar actually stacks).
    composition_group_count = measure_count if measure_count >= 2 else 0
    row_totals = [
        sum(
            Decimal(numeric_cells[i][row_index][0])
            for i in measure_indices
            if numeric_cells[i][row_index] is not None
        )
        for row_index in range(category_count)
    ] if measure_count >= 1 else []
    group_totals_positive = bool(row_totals) and all(total > 0 for total in row_totals)
    contains_zero_total_group = any(total == 0 for total in row_totals)

    # Single-total composition (donut/composition_bar): the "whole" is the
    # sum of the one measure column across every category. Deliberately
    # doesn't bake in the cardinality cap the way part_to_whole_valid does
    # — donut and composition_bar enforce that differently (see the
    # registry), since composition_bar is explicitly meant to tolerate more
    # categories than a donut can.
    single_measure_total = (
        sum(Decimal(cell[0]) for cell in numeric_cells[measure_indices[0]] if cell is not None)
        if measure_count == 1 else Decimal(0)
    )
    categories_form_meaningful_whole = (
        measure_count == 1
        and not contains_negative_values
        and category_count > 0
        and single_measure_total > 0
    )

    return DataProfile(
        dimensions=dimensions,
        measures=measures,
        category_count=category_count,
        measure_count=measure_count,
        contains_time=contains_time,
        contains_negative_values=contains_negative_values,
        contains_target=contains_target,
        part_to_whole_valid=part_to_whole_valid,
        contains_distribution=contains_distribution,
        contains_flow=contains_flow,
        observation_count=category_count,
        numeric_measure_count=measure_count,
        contains_paired_measures=contains_paired_measures,
        contains_size_measure=contains_size_measure,
        size_values_non_negative=size_values_non_negative,
        contains_matrix_shape=contains_matrix_shape,
        contains_ordered_steps=contains_ordered_steps,
        contains_start_value=contains_start_value,
        contains_signed_deltas=contains_signed_deltas,
        contains_final_total=contains_final_total,
        time_point_count=time_point_count,
        temporal_series_count=temporal_series_count,
        time_interval_consistent=time_interval_consistent,
        series_are_additive=series_are_additive,
        contains_missing_periods=contains_missing_periods,
        composition_group_count=composition_group_count,
        group_totals_positive=group_totals_positive,
        contains_zero_total_group=contains_zero_total_group,
        categories_form_meaningful_whole=categories_form_meaningful_whole,
    )


def compute_correlation_matrix(
    headers: list[str], numeric_cells: dict[int, list[tuple[str, str] | None]],
) -> tuple[list[str], list[list[str]]]:
    """Pearson correlation coefficient between every pair of measure
    columns, computed deterministically in plain Python (Decimal, stdlib
    only — never delegated to the LLM). Returns (labels, matrix) where
    matrix[i][j] is the coefficient between measure i and measure j,
    formatted to two decimal places; the diagonal is always "1.00"."""
    measure_indices = _measure_indices(headers, numeric_cells)
    labels = [headers[i] for i in measure_indices]
    columns = [_column_values(numeric_cells, i) for i in measure_indices]
    n = len(columns[0]) if columns else 0
    means = [sum(col) / n for col in columns] if n else []

    matrix: list[list[str]] = []
    for i, col_i in enumerate(columns):
        row: list[str] = []
        for j, col_j in enumerate(columns):
            if i == j:
                row.append("1.00")
                continue
            covariance = sum((col_i[k] - means[i]) * (col_j[k] - means[j]) for k in range(n))
            variance_i = sum((v - means[i]) ** 2 for v in col_i)
            variance_j = sum((v - means[j]) ** 2 for v in col_j)
            denominator_squared = variance_i * variance_j
            coefficient = (covariance / denominator_squared.sqrt()) if denominator_squared > 0 else Decimal(0)
            row.append(str(coefficient.quantize(Decimal("0.01"))))
        matrix.append(row)
    return labels, matrix


def detect_analytical_intent(query: str) -> AnalyticalIntent:
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(query):
            return intent
    return AnalyticalIntent.TEXT_ONLY


# ─── Visualization compatibility registry ──────────────────────────────────

@dataclass(frozen=True)
class VisualizationSpec:
    chart_type: str
    supported_intents: tuple[AnalyticalIntent, ...]
    requires_numeric_observations: bool = False
    minimum_observations: int = 0
    supports_negative_values: bool = True
    minimum_measures: int = 0
    maximum_measures: int | None = None
    maximum_categories: int | None = None
    requires_part_to_whole: bool = False
    requires_ordered_stages: bool = False
    requires_two_points_per_entity: bool = False
    # v2 additions.
    requires_paired_measures: bool = False
    requires_size_measure: bool = False
    requires_non_negative_size: bool = False
    requires_matrix_shape: bool = False
    requires_ordered_steps: bool = False
    requires_signed_deltas: bool = False
    requires_target: bool = False
    # v5 additions — temporal_series (line, area) and composition
    # (single_total_composition, multi_group_composition) families.
    requires_ordered_temporal: bool = False
    minimum_time_points: int = 0
    requires_additive_or_single_series: bool = False
    requires_meaningful_whole: bool = False
    requires_positive_group_totals: bool = False
    # Another chart_type in this registry, the literal "bar" (the
    # pre-existing, always-compatible fallback outside this registry), or
    # None (no chart — the caller keeps the text/table answer as-is).
    fallback: str | None = None


_REGISTRY: tuple[VisualizationSpec, ...] = (
    VisualizationSpec(
        chart_type="grouped_bar", supported_intents=(AnalyticalIntent.COMPARISON,),
        minimum_measures=2, fallback="bar",
    ),
    VisualizationSpec(
        chart_type="radar", supported_intents=(AnalyticalIntent.COMPARISON,),
        minimum_measures=3, maximum_measures=6, maximum_categories=5, fallback="grouped_bar",
    ),
    VisualizationSpec(
        chart_type="stacked_bar", supported_intents=(AnalyticalIntent.COMPOSITION,),
        minimum_measures=2, fallback="bar",
    ),
    VisualizationSpec(
        chart_type="percentage_stacked_bar", supported_intents=(AnalyticalIntent.COMPOSITION,),
        minimum_measures=2, requires_part_to_whole=True, supports_negative_values=False,
        requires_positive_group_totals=True,
        fallback="stacked_bar",
    ),
    VisualizationSpec(
        chart_type="diverging_bar",
        supported_intents=(AnalyticalIntent.TARGET_VARIANCE, AnalyticalIntent.COMPOSITION, AnalyticalIntent.FINANCIAL_MOVEMENT),
        minimum_measures=2, fallback="grouped_bar",
    ),
    VisualizationSpec(
        chart_type="histogram", supported_intents=(AnalyticalIntent.DISTRIBUTION,),
        requires_numeric_observations=True, minimum_observations=5, minimum_measures=1, maximum_measures=1,
        fallback=None,
    ),
    VisualizationSpec(
        chart_type="box_plot", supported_intents=(AnalyticalIntent.DISTRIBUTION,),
        requires_numeric_observations=True, minimum_observations=3, minimum_measures=1,
        fallback="bar",
    ),
    VisualizationSpec(
        chart_type="funnel", supported_intents=(AnalyticalIntent.FLOW,),
        requires_ordered_stages=True, minimum_measures=1, maximum_measures=1, minimum_observations=3,
        fallback="bar",
    ),
    VisualizationSpec(
        chart_type="slope",
        supported_intents=(AnalyticalIntent.TREND, AnalyticalIntent.FINANCIAL_MOVEMENT),
        requires_two_points_per_entity=True, minimum_measures=2, maximum_measures=2,
        fallback="grouped_bar",
    ),
    # v2
    VisualizationSpec(
        chart_type="scatter", supported_intents=(AnalyticalIntent.CORRELATION,),
        minimum_measures=2, minimum_observations=5, requires_paired_measures=True,
        fallback="grouped_bar",
    ),
    VisualizationSpec(
        chart_type="bubble", supported_intents=(AnalyticalIntent.CORRELATION,),
        minimum_measures=3, minimum_observations=5, requires_size_measure=True, requires_non_negative_size=True,
        fallback="scatter",
    ),
    VisualizationSpec(
        chart_type="heatmap", supported_intents=(AnalyticalIntent.CORRELATION,),
        requires_matrix_shape=True, minimum_measures=2, maximum_measures=12, maximum_categories=20,
        fallback="grouped_bar",
    ),
    VisualizationSpec(
        chart_type="correlation_matrix", supported_intents=(AnalyticalIntent.CORRELATION,),
        minimum_measures=3, minimum_observations=5,
        fallback="scatter",
    ),
    VisualizationSpec(
        chart_type="dumbbell",
        supported_intents=(AnalyticalIntent.COMPARISON, AnalyticalIntent.TARGET_VARIANCE, AnalyticalIntent.FINANCIAL_MOVEMENT),
        minimum_measures=2, maximum_measures=2, maximum_categories=15,
        fallback="grouped_bar",
    ),
    VisualizationSpec(
        chart_type="lollipop", supported_intents=(AnalyticalIntent.COMPARISON,),
        minimum_measures=1, maximum_measures=1,
        fallback="bar",
    ),
    VisualizationSpec(
        chart_type="bullet",
        supported_intents=(AnalyticalIntent.TARGET_VARIANCE, AnalyticalIntent.FINANCIAL_MOVEMENT),
        minimum_measures=2, maximum_measures=2, requires_target=True,
        fallback="dumbbell",
    ),
    VisualizationSpec(
        chart_type="waterfall", supported_intents=(AnalyticalIntent.FINANCIAL_MOVEMENT,),
        minimum_measures=1, maximum_measures=1, minimum_observations=3,
        requires_ordered_steps=True, requires_signed_deltas=True,
        fallback="slope",
    ),
    # v5 — temporal_series and single_total_composition. supported_intents
    # is unused by these two (they're reached via select_family_alternatives,
    # never generate_candidates/_INTENT_PREFERENCE_LISTS — see that
    # function's docstring) but kept non-empty for schema consistency with
    # every other entry in this registry.
    VisualizationSpec(
        chart_type="line", supported_intents=(AnalyticalIntent.TREND,),
        minimum_measures=1, requires_ordered_temporal=True, minimum_time_points=2,
        fallback="bar",
    ),
    VisualizationSpec(
        chart_type="area", supported_intents=(AnalyticalIntent.TREND,),
        minimum_measures=1, requires_ordered_temporal=True, minimum_time_points=2,
        requires_additive_or_single_series=True,
        fallback="line",
    ),
    VisualizationSpec(
        chart_type="donut", supported_intents=(AnalyticalIntent.COMPOSITION,),
        minimum_measures=1, maximum_measures=1, maximum_categories=_MAX_PART_TO_WHOLE_CATEGORIES,
        supports_negative_values=False, requires_meaningful_whole=True,
        fallback="composition_bar",
    ),
    VisualizationSpec(
        chart_type="composition_bar", supported_intents=(AnalyticalIntent.COMPOSITION,),
        minimum_measures=1, maximum_measures=1,
        supports_negative_values=False, requires_meaningful_whole=True,
        fallback="bar",
    ),
)
_SPEC_BY_TYPE = {spec.chart_type: spec for spec in _REGISTRY}


def _is_compatible(spec: VisualizationSpec, profile: DataProfile) -> bool:
    if profile.measure_count < spec.minimum_measures:
        return False
    if spec.maximum_measures is not None and profile.measure_count > spec.maximum_measures:
        return False
    if spec.maximum_categories is not None and profile.category_count > spec.maximum_categories:
        return False
    if spec.requires_numeric_observations and not profile.contains_distribution:
        return False
    if profile.category_count < spec.minimum_observations:
        return False
    if not spec.supports_negative_values and profile.contains_negative_values:
        return False
    if spec.requires_part_to_whole and not profile.part_to_whole_valid:
        return False
    if spec.requires_ordered_stages and not profile.contains_flow:
        return False
    if spec.requires_two_points_per_entity and profile.measure_count != 2:
        return False
    if spec.requires_paired_measures and not profile.contains_paired_measures:
        return False
    if spec.requires_size_measure and not profile.contains_size_measure:
        return False
    if spec.requires_non_negative_size and not profile.size_values_non_negative:
        return False
    if spec.requires_matrix_shape and not profile.contains_matrix_shape:
        return False
    if spec.requires_ordered_steps and not profile.contains_ordered_steps:
        return False
    if spec.requires_signed_deltas and not profile.contains_signed_deltas:
        return False
    if spec.requires_target and not profile.contains_target:
        return False
    # v5 — "ordered temporal" means the row axis was positively recognized
    # AND chronologically ordered by _analyze_temporal_sequence, regardless
    # of whether it also has gaps (time_interval_consistent is gapless-only;
    # contains_missing_periods is gapped-but-still-ordered) — an unordered or
    # unrecognized sequence leaves both false, which is the conservative
    # "don't claim what wasn't verified" default this whole module follows.
    if spec.requires_ordered_temporal and not (
        profile.contains_time and (profile.time_interval_consistent or profile.contains_missing_periods)
    ):
        return False
    if spec.minimum_time_points and profile.time_point_count < spec.minimum_time_points:
        return False
    if spec.requires_additive_or_single_series and not profile.series_are_additive:
        return False
    if spec.requires_meaningful_whole and not profile.categories_form_meaningful_whole:
        return False
    # Checking only contains_zero_total_group (not group_totals_positive
    # too) is deliberate: given supports_negative_values=False already
    # excludes negative rows elsewhere in this function, "no zero-total
    # group" and "every group total is positive" are mathematically the
    # same condition — and contains_zero_total_group defaults to False on a
    # hand-constructed DataProfile (used throughout this test suite),
    # whereas group_totals_positive defaults to False too but means the
    # OPPOSITE thing, which would wrongly reject any profile that never set
    # it explicitly.
    if spec.requires_positive_group_totals and profile.contains_zero_total_group:
        return False
    return True


def _resolve(chart_type: str | None, profile: DataProfile, depth: int = 0) -> str | None:
    """Follows a chart's declared fallback chain until a compatible type is
    found or the chain bottoms out at None (text/table) — depth-capped so a
    misconfigured registry can never loop forever."""
    if chart_type is None or depth > 4:
        return None
    if chart_type == "bar":
        return "bar"
    spec = _SPEC_BY_TYPE.get(chart_type)
    if spec is None:
        return None
    if _is_compatible(spec, profile):
        return chart_type
    return _resolve(spec.fallback, profile, depth + 1)


def _first_compatible(candidates: tuple[str, ...], profile: DataProfile) -> str | None:
    """Tries each candidate's own direct compatibility in priority order —
    for cases like target_variance (bullet, then dumbbell, then
    diverging_bar) where the right fallback depends on which specific
    candidate was being attempted, not a single fixed chain. The last
    candidate still gets its own registry fallback chain as the final
    safety net, so this never dead-ends where _resolve alone wouldn't."""
    for chart_type in candidates:
        spec = _SPEC_BY_TYPE.get(chart_type)
        if spec is not None and _is_compatible(spec, profile):
            return chart_type
    return _resolve(candidates[-1], profile) if candidates else None


def select_chart_type(intent: AnalyticalIntent, profile: DataProfile, query: str = "") -> str | None:
    """Deterministic, narrow — only ever returns a type this module has a
    real, registry-validated chart for, or an explicit fallback of one.
    query is used only for a small set of literal keyword tie-breaks
    between chart types that are otherwise indistinguishable from data
    shape alone (see the module docstring); it never changes what counts as
    compatible."""
    if intent == AnalyticalIntent.COMPARISON:
        if profile.measure_count >= 3:
            return _resolve("radar", profile)
        if profile.measure_count == 2:
            if _BASELINE_KEYWORDS.search(query):
                return _first_compatible(("dumbbell", "grouped_bar"), profile)
            return _resolve("grouped_bar", profile)
        if profile.measure_count == 1 and _RANKING_KEYWORDS.search(query):
            return _first_compatible(("lollipop", "bar"), profile)
        return _resolve("grouped_bar", profile)
    if intent == AnalyticalIntent.TARGET_VARIANCE:
        if profile.contains_target:
            return _first_compatible(("bullet", "dumbbell", "diverging_bar"), profile)
        return _resolve("diverging_bar", profile)
    if intent == AnalyticalIntent.COMPOSITION:
        # Single-measure composition (e.g. "expense breakdown by category")
        # is exactly the pre-existing donut chart's job — defer to it rather
        # than cascading through this registry to a plain bar, which would
        # silently override a working, cardinality-guarded donut path.
        if profile.measure_count < 2:
            return None
        if profile.contains_negative_values:
            return _resolve("diverging_bar" if profile.contains_target else "grouped_bar", profile)
        return _resolve("percentage_stacked_bar", profile)
    if intent == AnalyticalIntent.DISTRIBUTION:
        histogram_spec = _SPEC_BY_TYPE["histogram"]
        preferred = (
            "histogram" if profile.measure_count == 1 and profile.category_count >= histogram_spec.minimum_observations
            else "box_plot"
        )
        return _resolve(preferred, profile)
    if intent == AnalyticalIntent.FLOW:
        return _resolve("funnel", profile)
    if intent == AnalyticalIntent.TREND:
        return _resolve("slope", profile)
    if intent == AnalyticalIntent.CORRELATION:
        if _HEATMAP_KEYWORDS.search(query) and profile.contains_matrix_shape:
            return _resolve("heatmap", profile)
        if profile.measure_count >= 3:
            if _BUBBLE_KEYWORDS.search(query) and profile.contains_size_measure:
                return _resolve("bubble", profile)
            correlation_matrix_spec = _SPEC_BY_TYPE["correlation_matrix"]
            if profile.category_count < correlation_matrix_spec.minimum_observations:
                # Enough numeric fields to correlate, but not enough rows to
                # make the coefficients meaningful — refuse rather than
                # guess at a matrix, and don't silently downgrade to a
                # different chart that would hide the real limitation.
                return None
            return _resolve("correlation_matrix", profile)
        return _resolve("scatter", profile)
    if intent == AnalyticalIntent.FINANCIAL_MOVEMENT:
        if profile.measure_count == 1:
            return _resolve("waterfall", profile)
        if profile.contains_target:
            return _first_compatible(("bullet", "dumbbell", "diverging_bar"), profile)
        # "Walk from Q1 to Q4" etc. reads as a period-to-period change, not a
        # baseline/actual framing — prefer slope when the query itself says
        # so, same literal-keyword tie-break precedent as the other
        # otherwise-indistinguishable chart-type choices in this function.
        if re.search(r"\bwalk\s+from\b|\bchange\s+between\s+(?:two|the)\s+periods?\b", query, re.IGNORECASE):
            return _first_compatible(("slope", "dumbbell", "diverging_bar"), profile)
        return _first_compatible(("dumbbell", "diverging_bar", "slope"), profile)
    return None


# ─── Dynamic Visualization Selection v3 — ranked alternatives ──────────────
#
# Chart types that render from a genuinely different payload shape than
# "categories (rows) x series (measures)" are grouped into families;
# alternatives are only ever offered within the SAME family as whatever was
# actually selected, so "Try another view" never needs a different backend
# payload — every alternative renders from the exact same PresentationChart
# already sent to the client. This is what "no incompatible data
# transformation" (a hard requirement for the frontend view switcher) is
# built on, not a separate check layered on top.
_CHART_FAMILY: dict[str, str] = {
    "bar": "category_series", "grouped_bar": "category_series",
    "diverging_bar": "category_series", "radar": "category_series",
    "dumbbell": "category_series", "lollipop": "category_series", "bullet": "category_series",
    "histogram": "distribution", "box_plot": "distribution",
    "scatter": "paired_numeric", "bubble": "paired_numeric",
    "heatmap": "matrix", "correlation_matrix": "matrix",
    "funnel": "ordered_single_measure", "waterfall": "ordered_single_measure",
    "slope": "two_point_per_entity",
    # v5 — reclassified out of category_series (see module docstring below
    # and select_family_alternatives): stacked_bar/percentage_stacked_bar
    # only ever appear together, via AnalyticalIntent.COMPOSITION's own
    # preference list, so this move changes no existing pairing — it just
    # names the family correctly and gives temporal/single-total composition
    # charts their own, non-overlapping families.
    "stacked_bar": "multi_group_composition", "percentage_stacked_bar": "multi_group_composition",
    "line": "temporal_series", "area": "temporal_series",
    "donut": "single_total_composition", "composition_bar": "single_total_composition",
}

# v5 — fixed candidate lists for the two chart families select_chart_type
# has no branch for at all (line/area/donut/composition_bar are chosen by
# presentation.py's own is_temporal/composition_requested heuristics, not by
# AnalyticalIntent — see select_family_alternatives). Order only matters
# for the sort key's stable-order tie-break; analytical_intent_fit is 0 for
# both members of each list either way since neither appears in
# _INTENT_PREFERENCE_LISTS.
TEMPORAL_PREFERENCE: tuple[str, ...] = ("area", "line")
SINGLE_TOTAL_COMPOSITION_PREFERENCE: tuple[str, ...] = ("donut", "composition_bar")

# The spec's own recommended preference mappings, restricted to chart types
# that actually have a VisualizationSpec registry entry with real
# compatibility rules. "line", "area", and single-measure "donut"/
# "composition_bar" are deliberately absent from THIS dict (still v1-v3
# scope): they're chosen by presentation.py's own is_temporal/
# composition_requested heuristics, not by AnalyticalIntent, so they can't
# slot into an intent-keyed preference list the way every other chart type
# here does. v5 gives them ranked alternatives too, but through
# select_family_alternatives + TEMPORAL_PREFERENCE/
# SINGLE_TOTAL_COMPOSITION_PREFERENCE above, not through this dict or
# generate_candidates — see that function's docstring for why.
_INTENT_PREFERENCE_LISTS: dict[AnalyticalIntent, tuple[str, ...]] = {
    AnalyticalIntent.COMPARISON: ("grouped_bar", "dumbbell", "lollipop", "diverging_bar", "radar"),
    AnalyticalIntent.TARGET_VARIANCE: ("bullet", "dumbbell", "diverging_bar", "grouped_bar"),
    AnalyticalIntent.TREND: ("slope",),
    AnalyticalIntent.COMPOSITION: ("percentage_stacked_bar", "stacked_bar"),
    AnalyticalIntent.DISTRIBUTION: ("histogram", "box_plot"),
    AnalyticalIntent.CORRELATION: ("scatter", "bubble", "correlation_matrix", "heatmap"),
    AnalyticalIntent.FLOW: ("funnel",),
    AnalyticalIntent.FINANCIAL_MOVEMENT: ("waterfall", "diverging_bar", "slope", "dumbbell", "bullet"),
}

# One literal phrase per registered chart type — used only to detect that
# the user actually asked for a specific chart by name, for the explicit-
# request-wins rule and the tie-break chain. Never a fuzzy or synonym-heavy
# match; a query that doesn't use one of these exact phrasings is simply not
# an explicit request, and falls through to ordinary ranking.
_CHART_TYPE_SYNONYMS: tuple[tuple[str, re.Pattern], ...] = (
    # V8.2 evidence-only exact aliases. They intentionally have no registry
    # spec and therefore can never become candidates or renderers.
    ("treemap", re.compile(r"\btreemap\b", re.IGNORECASE)),
    ("sankey", re.compile(r"\bsankey(?: diagram| chart)?\b", re.IGNORECASE)),
    ("gauge", re.compile(r"\b(?:gauge|speedometer) chart\b", re.IGNORECASE)),
    ("violin", re.compile(r"\bviolin plot\b", re.IGNORECASE)),
    ("percentage_stacked_bar", re.compile(r"\bpercentage[\s-]stacked\s+bar\b|\b100%\s+stacked\s+bar\b", re.IGNORECASE)),
    ("stacked_bar", re.compile(r"\bstacked\s+bar\b", re.IGNORECASE)),
    ("grouped_bar", re.compile(r"\bgrouped\s+bar\b", re.IGNORECASE)),
    ("diverging_bar", re.compile(r"\bdiverging\s+bar\b", re.IGNORECASE)),
    ("dumbbell", re.compile(r"\bdumbbell\b", re.IGNORECASE)),
    ("lollipop", re.compile(r"\blollipop\b", re.IGNORECASE)),
    ("bullet", re.compile(r"\bbullet\s+chart\b", re.IGNORECASE)),
    ("radar", re.compile(r"\bradar\s+chart\b|\bspider\s+chart\b", re.IGNORECASE)),
    ("histogram", re.compile(r"\bhistogram\b", re.IGNORECASE)),
    ("box_plot", re.compile(r"\bbox\s?plot\b|\bbox[\s-]and[\s-]whisker\b", re.IGNORECASE)),
    ("bubble", re.compile(r"\bbubble\s+chart\b", re.IGNORECASE)),
    ("scatter", re.compile(r"\bscatter\s?(?:plot|chart)?\b", re.IGNORECASE)),
    ("correlation_matrix", re.compile(r"\bcorrelation\s+matrix\b", re.IGNORECASE)),
    ("heatmap", re.compile(r"\bheat\s?map\b", re.IGNORECASE)),
    ("funnel", re.compile(r"\bfunnel\b", re.IGNORECASE)),
    ("waterfall", re.compile(r"\bwaterfall\b", re.IGNORECASE)),
    ("slope", re.compile(r"\bslope\s+chart\b", re.IGNORECASE)),
    # v5.
    ("composition_bar", re.compile(r"\bcomposition\s+bar\b", re.IGNORECASE)),
    ("donut", re.compile(r"\bdonut\s+chart\b|\bpie\s+chart\b", re.IGNORECASE)),
    ("area", re.compile(r"\barea\s+chart\b", re.IGNORECASE)),
    ("line", re.compile(r"\bline\s+chart\b|\bline\s+graph\b", re.IGNORECASE)),
)

# Fixed, documented per-type baselines for the three "static" scoring
# dimensions readability/mobile_suitability/accessibility, plus complexity
# (higher = more complex, i.e. worse). All on a 0-1 scale. These are
# editorial judgments about the chart types themselves (a radar chart is
# harder to read at a glance than a bar chart, on any device, for any data)
# — not derived from any one answer's data, which is what data_shape_fit
# and category_cardinality are for instead.
_READABILITY: dict[str, float] = {
    "grouped_bar": 0.95, "stacked_bar": 0.85, "percentage_stacked_bar": 0.80, "diverging_bar": 0.85,
    "dumbbell": 0.80, "lollipop": 0.85, "bullet": 0.75, "radar": 0.60,
    "histogram": 0.85, "box_plot": 0.70,
    "scatter": 0.75, "bubble": 0.65, "heatmap": 0.60, "correlation_matrix": 0.55,
    "funnel": 0.85, "waterfall": 0.75, "slope": 0.80,
    # v5.
    "line": 0.85, "area": 0.80, "donut": 0.70, "composition_bar": 0.85,
}
_MOBILE_SUITABILITY: dict[str, float] = {
    "grouped_bar": 0.80, "stacked_bar": 0.85, "percentage_stacked_bar": 0.85, "diverging_bar": 0.85,
    "dumbbell": 0.70, "lollipop": 0.85, "bullet": 0.60, "radar": 0.45,
    "histogram": 0.80, "box_plot": 0.75,
    "scatter": 0.60, "bubble": 0.50, "heatmap": 0.50, "correlation_matrix": 0.40,
    "funnel": 0.75, "waterfall": 0.70, "slope": 0.75,
    # v5.
    "line": 0.85, "area": 0.75, "donut": 0.70, "composition_bar": 0.85,
}
_ACCESSIBILITY: dict[str, float] = {
    "grouped_bar": 0.90, "stacked_bar": 0.85, "percentage_stacked_bar": 0.80, "diverging_bar": 0.85,
    "dumbbell": 0.75, "lollipop": 0.85, "bullet": 0.70, "radar": 0.55,
    "histogram": 0.70, "box_plot": 0.60,
    "scatter": 0.55, "bubble": 0.45, "heatmap": 0.60, "correlation_matrix": 0.60,
    "funnel": 0.80, "waterfall": 0.75, "slope": 0.80,
    # v5.
    "line": 0.85, "area": 0.75, "donut": 0.65, "composition_bar": 0.85,
}
_COMPLEXITY: dict[str, float] = {
    "grouped_bar": 0.10, "stacked_bar": 0.20, "percentage_stacked_bar": 0.25, "diverging_bar": 0.20,
    "dumbbell": 0.35, "lollipop": 0.20, "bullet": 0.40, "radar": 0.45,
    "histogram": 0.25, "box_plot": 0.40,
    "scatter": 0.30, "bubble": 0.45, "heatmap": 0.50, "correlation_matrix": 0.60,
    "funnel": 0.30, "waterfall": 0.40, "slope": 0.30,
    # v5.
    "line": 0.15, "area": 0.20, "donut": 0.25, "composition_bar": 0.15,
}
_DEFAULT_MAXIMUM_CATEGORIES = 20

# Fixed weights — every score is a linear combination of these, computed the
# same way for every candidate. complexity_penalty and
# recent_repetition_penalty carry negative weights (their own 0-1 value is
# "how bad", so a negative weight subtracts it); everything else is
# "how good". No LLM, no randomness anywhere in this file.
_WEIGHTS: dict[str, float] = {
    "analytical_intent_fit": 0.28,
    "data_shape_fit": 0.16,
    "explicit_query_match": 0.20,
    "readability": 0.12,
    "mobile_suitability": 0.06,
    "accessibility": 0.06,
    "category_cardinality": 0.08,
    "complexity_penalty": -0.10,
    "recent_repetition_penalty": -0.06,
}
# An explicit, compatible request must outright win (requirement: "explicit
# user requests outrank inferred preferences when the requested chart is
# compatible") — not just be weighted heavily. WEIGHTS above alone can't
# guarantee that against a candidate that scores near-1.0 on every other
# bounded 0-1 dimension, so a real match gets a fixed bonus large enough
# that no combination of the other dimensions can outscore it.
_EXPLICIT_MATCH_BONUS = 10.0
# recent_repetition_penalty is capped small and per-occurrence, exactly so
# it can never flip a ranking that correctness/readability already decided
# — three consecutive repeats of the same chart type cost at most 0.3 of a
# 0-1 scored dimension, weighted at -0.06, i.e. at most an ~0.018 swing.
_REPETITION_PENALTY_PER_OCCURRENCE = 0.1
_REPETITION_PENALTY_CAP = 0.3

# v10 — a consent-based personalization signal (see
# visualization_personalization.py) may add at most this much directly to a
# candidate's score, deliberately smaller than the smallest "major"
# dimension weight above (data_shape_fit at 0.16, readability at 0.12) and
# tiny next to _EXPLICIT_MATCH_BONUS. This bound is what makes "may only
# break a near tie among compatible candidates" true structurally: the
# personalized candidate can only overtake the ordinary default in the sort
# order (see the near-tie check in select_chart_with_alternatives/
# select_family_alternatives below) when their PRE-personalization score gap
# was already within this cap — a genuine analytical-intent or data-fit
# difference is always larger than this and can never be erased by it.
_MAX_PERSONALIZATION_BOOST = 0.05

# v6 — identifies which weight set _WEIGHTS above currently represents, for
# recommendation-quality reporting (see visualization_analytics.py and
# ranking_configuration.py). Recorded on every backend-emitted
# visualization_selected/alternative_views_shown/visualization_fallback_used
# telemetry event so a future analysis can compare outcomes across weight
# revisions — this constant is bumped by hand whenever _WEIGHTS itself
# changes; nothing reads a RankingConfiguration row to pick a version or a
# weight at runtime. That is deliberate: v6 builds a governed *proposal and
# review* pipeline for weight changes (ranking_configuration.py), not a live
# runtime-configurable scorer — see that module's docstring for why
# activation stays a manual, out-of-band (code + this constant) step.
RANKING_VERSION = "1.0.0"

# v6 — validated bounds for any proposed or drafted RankingConfiguration's
# weights (see ranking_configuration.py). Mirrors _WEIGHTS' own sign
# convention exactly: "how good" dimensions may only ever be tuned within
# [0, 1] (never flipped into a penalty), "how bad" dimensions
# (complexity_penalty, recent_repetition_penalty) only within [-1, 0] (never
# flipped into a bonus) — a configuration can never invert what a dimension
# means, only how strongly it counts.
WEIGHT_BOUNDS: dict[str, tuple[float, float]] = {
    "analytical_intent_fit": (0.0, 1.0),
    "data_shape_fit": (0.0, 1.0),
    "explicit_query_match": (0.0, 1.0),
    "readability": (0.0, 1.0),
    "mobile_suitability": (0.0, 1.0),
    "accessibility": (0.0, 1.0),
    "category_cardinality": (0.0, 1.0),
    "complexity_penalty": (-1.0, 0.0),
    "recent_repetition_penalty": (-1.0, 0.0),
}
WEIGHT_DIMENSIONS: tuple[str, ...] = tuple(_WEIGHTS.keys())


def current_weights() -> dict[str, float]:
    """A copy of the live production weights (never the live dict itself —
    callers must not be able to mutate scoring behavior by holding a
    reference to this)."""
    return dict(_WEIGHTS)


def _explicitly_requested_type(query: str) -> str | None:
    for chart_type, pattern in _CHART_TYPE_SYNONYMS:
        if pattern.search(query):
            return chart_type
    return None


def explicitly_requested_chart_type(query: str) -> str | None:
    """Public V8.2 exact-alias detector; deliberately no fuzzy matching."""
    return _explicitly_requested_type(query)


def _intent_fit_score(chart_type: str, intent: AnalyticalIntent) -> float:
    preference_list = _INTENT_PREFERENCE_LISTS.get(intent, ())
    if chart_type not in preference_list:
        return 0.0
    position = preference_list.index(chart_type)
    return 1.0 - (position / max(1, len(preference_list)))


def _data_shape_fit(chart_type: str, profile: DataProfile) -> float:
    """How comfortably the profile clears this type's own requirements —
    compatibility (_is_compatible) is binary pass/fail; this is the
    graded version, used only for ranking among already-compatible
    candidates. Barely-cleared minimums score lower than a real margin."""
    spec = _SPEC_BY_TYPE.get(chart_type)
    if spec is None:
        return 0.5
    score = 1.0
    if spec.minimum_observations and profile.category_count < spec.minimum_observations * 1.5:
        score -= 0.15
    if spec.minimum_measures and profile.measure_count == spec.minimum_measures and spec.maximum_measures != spec.minimum_measures:
        score -= 0.05
    return max(0.0, min(1.0, score))


def _category_cardinality_score(chart_type: str, profile: DataProfile) -> float:
    spec = _SPEC_BY_TYPE.get(chart_type)
    cap = (spec.maximum_categories if spec and spec.maximum_categories else _DEFAULT_MAXIMUM_CATEGORIES)
    if profile.category_count <= cap:
        return 1.0
    overflow_ratio = (profile.category_count - cap) / cap
    return max(0.0, 1.0 - overflow_ratio)


def _repetition_penalty(chart_type: str, recent_chart_types: tuple[str, ...]) -> float:
    if not recent_chart_types:
        return 0.0
    occurrences = recent_chart_types.count(chart_type)
    return min(_REPETITION_PENALTY_CAP, occurrences * _REPETITION_PENALTY_PER_OCCURRENCE)


@dataclass(frozen=True)
class ScoredCandidate:
    """Diagnostics only — see select_chart_with_alternatives' docstring.
    Never round-tripped into a PresentationChart or a saved payload."""
    chart_type: str
    score: float
    breakdown: dict[str, float]


@dataclass(frozen=True)
class VisualizationSelection:
    chart_type: str | None
    alternatives: tuple[str, ...]
    candidates: tuple[ScoredCandidate, ...]
    explicit_request_invalid: bool = False
    requested_chart_type: str | None = None
    selection_source: SelectionSource | None = None
    # v10 — true only when a personalized signal actually won the near-tie
    # break for THIS chart's primary pick (see select_chart_with_alternatives'
    # docstring). presentation.py reads this directly rather than re-deriving
    # it from selection_source, so the "when to show the frontend label" rule
    # lives in exactly one place.
    personalization_affected_selection: bool = False


def _compatible_candidates(preference_list: tuple[str, ...], profile: DataProfile) -> tuple[str, ...]:
    """Every chart type in preference_list that is registry-compatible with
    this exact profile — never a type without a real VisualizationSpec
    entry, never one that fails its own compatibility checks. The order
    here is preference_list's own order, which _intent_fit_score (and the
    stable-order tie-break in _make_candidate_sort_key) reads positionally."""
    compatible: list[str] = []
    for chart_type in preference_list:
        spec = _SPEC_BY_TYPE.get(chart_type)
        if spec is not None and _is_compatible(spec, profile):
            compatible.append(chart_type)
    return tuple(compatible)


def generate_candidates(intent: AnalyticalIntent, profile: DataProfile) -> tuple[str, ...]:
    """Every chart type this intent's preference list names that is also
    registry-compatible with this exact profile. See _compatible_candidates."""
    return _compatible_candidates(_INTENT_PREFERENCE_LISTS.get(intent, ()), profile)


def _score_candidate(
    chart_type: str, intent: AnalyticalIntent, profile: DataProfile, query: str, recent_chart_types: tuple[str, ...],
    weights: dict[str, float] | None = None, personalization_boosts: dict[str, float] | None = None,
) -> ScoredCandidate:
    """weights defaults to the live production _WEIGHTS — v7's experiment
    engine is the only caller that ever passes something else (a variant
    RankingConfiguration's weights, for conversations assigned to that
    arm). Passing different weights can only ever re-ORDER already-
    compatible candidates against each other; it cannot make an
    incompatible one appear here at all (that gate is generate_candidates/
    _is_compatible, upstream of this function and blind to weights) and it
    cannot beat an explicit compatible request (_EXPLICIT_MATCH_BONUS is
    applied after, and outside, the weighted sum below regardless of which
    weights dict was used).

    personalization_boosts (v10) — an optional chart_type -> raw preference-
    share (0-1) mapping from visualization_personalization.py; clamped to
    [0, _MAX_PERSONALIZATION_BOOST] and added directly, exactly like
    _EXPLICIT_MATCH_BONUS is, so its bound holds regardless of what the
    caller passes in — a defensive clamp, not a trust assumption."""
    active_weights = weights if weights is not None else _WEIGHTS
    breakdown = {
        "analytical_intent_fit": _intent_fit_score(chart_type, intent),
        "data_shape_fit": _data_shape_fit(chart_type, profile),
        "explicit_query_match": 1.0 if _explicitly_requested_type(query) == chart_type else 0.0,
        "readability": _READABILITY.get(chart_type, 0.5),
        "mobile_suitability": _MOBILE_SUITABILITY.get(chart_type, 0.5),
        "accessibility": _ACCESSIBILITY.get(chart_type, 0.5),
        "category_cardinality": _category_cardinality_score(chart_type, profile),
        "complexity_penalty": _COMPLEXITY.get(chart_type, 0.5),
        "recent_repetition_penalty": _repetition_penalty(chart_type, recent_chart_types),
    }
    score = sum(active_weights[dimension] * value for dimension, value in breakdown.items())
    if breakdown["explicit_query_match"] == 1.0:
        score += _EXPLICIT_MATCH_BONUS
    if personalization_boosts:
        score += min(_MAX_PERSONALIZATION_BOOST, max(0.0, personalization_boosts.get(chart_type, 0.0)))
    return ScoredCandidate(chart_type=chart_type, score=score, breakdown=breakdown)


def _make_candidate_sort_key(intent: AnalyticalIntent, requested: str | None, candidates: tuple[str, ...]):
    """Deterministic tie-break chain: primary weighted score (already
    dominated by the explicit-match bonus when relevant, and nudged by
    recent_repetition_penalty within its small capped range), then explicit
    request, then higher analytical fit, then lower complexity, then stable
    registry (preference-list) order. Extracted to module level (rather
    than a closure inside select_chart_with_alternatives) specifically so
    it's directly unit-testable against constructed near-tie candidates —
    see test_presentation_dataprofile_v4.py."""
    def _sort_key(candidate: ScoredCandidate) -> tuple[float, int, float, float, int]:
        return (
            -candidate.score,
            0 if candidate.chart_type == requested else 1,
            -_intent_fit_score(candidate.chart_type, intent),
            _COMPLEXITY.get(candidate.chart_type, 0.5),
            candidates.index(candidate.chart_type),
        )
    return _sort_key


def _personalization_override(
    ranked: tuple[ScoredCandidate, ...], candidates: tuple[str, ...],
    default_chart_type: str | None, personalization_preferred_chart_type: str | None,
) -> bool:
    """v10 — true only when the personalized candidate is registry-
    compatible (already guaranteed by its presence in `candidates`, the
    same list every other rule here is bound by) AND scores at least as
    well as the ordinary default under whichever weights are active.
    Because _score_candidate clamps any personalization contribution to
    _MAX_PERSONALIZATION_BOOST, this can only be true when the two
    candidates' PRE-personalization scores were already within that small
    margin — a genuine near tie, never a way to override a real
    analytical-intent or data-fit difference (see _MAX_PERSONALIZATION_BOOST's
    own docstring for the bound this relies on)."""
    if not personalization_preferred_chart_type or personalization_preferred_chart_type not in candidates:
        return False
    if default_chart_type is None or default_chart_type not in candidates:
        return False
    if personalization_preferred_chart_type == default_chart_type:
        return False
    scores = {candidate.chart_type: candidate.score for candidate in ranked}
    personalized_score = scores.get(personalization_preferred_chart_type)
    default_score = scores.get(default_chart_type)
    if personalized_score is None or default_score is None:
        return False
    return personalized_score >= default_score


def select_chart_with_alternatives(
    intent: AnalyticalIntent, profile: DataProfile, query: str = "", recent_chart_types: tuple[str, ...] = (),
    weights: dict[str, float] | None = None, preferred_chart_type: str | None = None,
    personalization_preferred_chart_type: str | None = None, personalization_boosts: dict[str, float] | None = None,
) -> VisualizationSelection:
    """Adds ranked, registry-valid alternatives on top of the existing
    select_chart_type — the default (non-explicit) primary pick is always
    exactly what select_chart_type already returns; this function never
    second-guesses it. Only two things can move the primary pick away from
    that default:
      1. the query names a chart type by name (see _CHART_TYPE_SYNONYMS)
         AND that type is registry-compatible with this profile — then it
         becomes the primary pick, per the "explicit requests outrank
         inferred preferences when compatible" rule; the ordinary default
         is pushed into the alternatives list instead of being discarded.
      2. the query names a chart type that is NOT compatible — the default
         pick is used exactly as before, and explicit_request_invalid=True
         so the caller can attach an explanatory fallback note.

    Alternatives are capped at three, restricted to the same "chart family"
    as the primary pick (see _CHART_FAMILY) so every one of them renders
    from the identical PresentationChart payload with zero data
    transformation, and never include the primary pick itself.

    Scoring (_score_candidate) is used only to ORDER candidates within a
    family for the alternatives list, and to decide the explicit-request
    tie-break when more than one compatible candidate matches the query
    (which cannot happen with the current one-phrase-per-type synonym
    table, but the ordering is still well-defined if it ever does).

    weights — v7: None (the default) uses the live production _WEIGHTS;
    ranking_experiments.py passes a variant RankingConfiguration's weights
    for conversations a running experiment assigned to the variant arm.
    Only the SCORE changes; candidates/compatibility/family and the
    explicit-request-wins rule are entirely unaffected either way.

    personalization_preferred_chart_type/personalization_boosts — v10,
    resolved once per request by visualization_personalization.py and
    None whenever personalization is disabled, ineligible, stale, or
    unavailable. Strictly lower priority than both an explicit request and
    a saved preference (see the override chain below); can only become the
    primary pick via the bounded near-tie check in
    _personalization_override, and otherwise only nudges alternatives
    ordering through personalization_boosts, exactly like weights does for
    an experiment.
    """
    candidates = generate_candidates(intent, profile)
    requested = _explicitly_requested_type(query)
    explicit_request_invalid = requested is not None and requested not in candidates

    if not candidates:
        return VisualizationSelection(
            chart_type=None, alternatives=(), candidates=(),
            explicit_request_invalid=explicit_request_invalid, requested_chart_type=requested,
        )

    scored = [
        _score_candidate(c, intent, profile, query, recent_chart_types, weights, personalization_boosts)
        for c in candidates
    ]
    _sort_key = _make_candidate_sort_key(intent, requested, candidates)

    ranked = tuple(sorted(scored, key=_sort_key))

    default_chart_type = select_chart_type(intent, profile, query)
    explicit_wins = requested is not None and requested in candidates
    preference_wins = not explicit_wins and preferred_chart_type in candidates
    personalization_wins = not explicit_wins and not preference_wins and _personalization_override(
        ranked, candidates, default_chart_type, personalization_preferred_chart_type,
    )
    chart_type = (
        requested if explicit_wins
        else preferred_chart_type if preference_wins
        else personalization_preferred_chart_type if personalization_wins
        else default_chart_type
    )
    if chart_type is None:
        return VisualizationSelection(
            chart_type=None, alternatives=(), candidates=ranked,
            explicit_request_invalid=explicit_request_invalid, requested_chart_type=requested,
            selection_source=None,
        )

    selection_source = (
        SelectionSource.EXPLICIT_USER_REQUEST if explicit_wins
        else SelectionSource.PERSONALIZED if personalization_wins
        else SelectionSource.SAFE_FALLBACK if explicit_request_invalid
        else SelectionSource.DETERMINISTIC_DEFAULT
    )
    family = _CHART_FAMILY.get(chart_type)
    alternatives = tuple(
        candidate.chart_type for candidate in ranked
        if candidate.chart_type != chart_type and _CHART_FAMILY.get(candidate.chart_type) == family
    )[:3]
    return VisualizationSelection(
        chart_type=chart_type, alternatives=alternatives, candidates=ranked,
        explicit_request_invalid=explicit_request_invalid, requested_chart_type=requested,
        selection_source=selection_source, personalization_affected_selection=personalization_wins,
    )


# ─── Dynamic Visualization Selection v5 — temporal & composition ───────────

def select_family_alternatives(
    default_chart_type: str, preference_list: tuple[str, ...], intent: AnalyticalIntent,
    profile: DataProfile, query: str = "", recent_chart_types: tuple[str, ...] = (),
    weights: dict[str, float] | None = None, preferred_chart_type: str | None = None,
    personalization_preferred_chart_type: str | None = None, personalization_boosts: dict[str, float] | None = None,
) -> VisualizationSelection:
    """The temporal (line/area) and single-total-composition (donut/
    composition_bar) equivalent of select_chart_with_alternatives, for chart
    types select_chart_type has no branch for at all — they're chosen by
    presentation.py's own is_temporal/composition_requested heuristics, not
    by AnalyticalIntent, so they can't be reached through
    generate_candidates/_INTENT_PREFERENCE_LISTS the way every other v1-v4
    chart type is.

    Reuses the exact same scoring/ranking machinery as v3
    (_score_candidate, _make_candidate_sort_key) and the same
    explicit-request-wins / explicit-request-invalid rules — but
    default_chart_type is supplied by the caller (presentation.py mirrors
    the pre-v5 ternary bit-for-bit to compute it) rather than derived here,
    so this function can never itself change what the default is; it only
    ever adds ranked alternatives around that default, or — for a
    registry-compatible explicit request naming another family member —
    swaps which member is primary. A default that isn't itself
    registry-compatible (e.g. area chosen for temporal data this module
    couldn't positively verify as chronologically ordered) is still
    returned as-is, with an empty alternatives list: this is the "falls
    back safely" case, never a crash or a silent default change.

    weights — v7, same meaning as select_chart_with_alternatives'."""
    candidates = _compatible_candidates(preference_list, profile)
    requested = _explicitly_requested_type(query)
    # Matches select_chart_with_alternatives' own semantics exactly: ANY
    # explicit request for a type this profile doesn't support counts as
    # invalid — not just requests naming another member of this family —
    # since a request for, say, a scatter chart on temporal data is just as
    # unsupported as a request for a non-additive area chart.
    explicit_request_invalid = requested is not None and requested not in candidates

    scored = [
        _score_candidate(c, intent, profile, query, recent_chart_types, weights, personalization_boosts)
        for c in candidates
    ]
    _sort_key = _make_candidate_sort_key(intent, requested, candidates)
    ranked = tuple(sorted(scored, key=_sort_key))

    explicit_wins = requested is not None and requested in candidates
    preference_wins = not explicit_wins and preferred_chart_type in candidates
    personalization_wins = not explicit_wins and not preference_wins and _personalization_override(
        ranked, candidates, default_chart_type, personalization_preferred_chart_type,
    )
    chart_type = (
        requested if explicit_wins
        else preferred_chart_type if preference_wins
        else personalization_preferred_chart_type if personalization_wins
        else default_chart_type
    )
    selection_source = (
        SelectionSource.EXPLICIT_USER_REQUEST if explicit_wins
        else SelectionSource.PERSONALIZED if personalization_wins
        else SelectionSource.SAFE_FALLBACK if explicit_request_invalid
        else SelectionSource.DETERMINISTIC_DEFAULT
    )
    family = _CHART_FAMILY.get(chart_type)
    alternatives = tuple(
        candidate.chart_type for candidate in ranked
        if candidate.chart_type != chart_type and _CHART_FAMILY.get(candidate.chart_type) == family
    )[:3]
    return VisualizationSelection(
        chart_type=chart_type, alternatives=alternatives, candidates=ranked,
        explicit_request_invalid=explicit_request_invalid, requested_chart_type=requested,
        selection_source=selection_source, personalization_affected_selection=personalization_wins,
    )
