"""Deterministic presentation planning for already-validated answer text.

This module never generates facts. It only inspects the user query and the
final Markdown answer that has already passed Checkpoint C. Numeric charts are
derived exclusively from complete numeric columns in GFM tables, keeping the
table as the accessible textual source of truth.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.orchestration.format_intent import is_decision_judgment_query
from app.orchestration.schemas import (
    AnswerPresentation,
    PresentationChart,
    PresentationGuide,
    PresentationMetric,
    PresentationSeries,
)


_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_CITATION = re.compile(r"\s*\[REF-\d+\]\s*")
_MARKDOWN = re.compile(r"[*_`]")
# 2026-07-29 real incident: an audit checklist ("Control Environment... -
# Evaluate the company's control environment... Risk Assessment... - Identify
# the locations...") rendered as plain text with zero chart/metric/guide
# panel, even though it's exactly the kind of content the checklist guide
# exists for. Root cause: the model wrote it as bullet lines ('- item'), and
# both patterns below only ever matched a literal numbered prefix ('1.'/'1)')
# — a bulleted procedure or checklist is at least as common in real model
# output as a numbered one, and previously produced nothing at all. Extended
# to accept '-', '*', or '•' as an alternative to a digit prefix; a numbered
# list is still recognized exactly as before, this only adds a second,
# equally common shape rather than replacing the first.
_ORDERED_STEP = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+")
_HEADING = re.compile(r"(?m)^#{1,4}\s+")
_HEADING_LINE = re.compile(r"^#{1,4}\s+(.+?)\s*$")
_ORDERED_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.+?)\s*$")
_COMPARE_QUERY = re.compile(r"\b(compare|comparison|difference|versus|vs\.?|pros?\s+and\s+cons?)\b", re.IGNORECASE)
_TIMELINE_QUERY = re.compile(r"\b(timeline|schedule|deadline|due date|chronolog(?:y|ical)?)\b", re.IGNORECASE)
_CHECKLIST_QUERY = re.compile(r"\b(checklist|check list|review|verify|validation)\b", re.IGNORECASE)
# The composed answer's actual heading/ID phrasing ("### Result", lowercase
# "calculation ID `calc-...`" with no colon) never matched the original
# stricter pattern here — confirmed live (2026-07-24): both the depreciation
# and current-ratio calculation answers fell through to layout="descriptive"
# instead of "calculation", showing the wrong follow-up questions even
# though the calculation itself (and, where registered, its widget) was
# correct. Anchored on the calc-<hex> ID pattern instead, which is generated
# by formula_registry._new_calculation_id() and unique enough not to appear
# in any non-calculation answer; case/colon/backtick-insensitive so future
# phrasing drift in the compose prompt doesn't silently break this again.
_CALCULATION_ANSWER = re.compile(
    r"(?m)^### (?:Verified|Calculated) result\s*$|calculation id:?\s*`?calc-[0-9a-f]{6,}",
    re.IGNORECASE,
)
_MISSING_INPUT_ANSWER = re.compile(r"(?m)^## Information needed\s*$")
_VISUAL_REQUEST = re.compile(
    r"\b(chart|graph|visuali[sz]e|plot|breakdown|composition|proportion|share of|percentage of)\b",
    re.IGNORECASE,
)
_BROAD_EXPLANATION_QUERY = re.compile(
    r"\b(complete picture|full picture|comprehensive|detailed|in depth|overview)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"^\s*(?P<open>\()?\s*(?P<currency>[$£€])?\s*(?P<sign>-)?"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<percent>%?)\s*"
    r"(?P<code>USD|GBP|EUR)?\s*\)?\s*$",
    re.IGNORECASE,
)
# A donut is a weaker general-purpose form than a bar-of-shares (angle/area
# is harder to compare than aligned length), but it's the form actually
# requested for "composition" answers — kept intentionally narrow (exactly
# one category column + one numeric series, capped slice count) so it only
# ever fires for genuine part-of-a-whole data, never as a substitute for an
# ordinary 2-column bar comparison.
_SHARE_HEADER_PATTERN = re.compile(r"\b(share|proportion|composition|breakdown|percent(?:age)?|mix)\b", re.IGNORECASE)
_MAX_DONUT_SLICES = 6


def _chart_display_metadata(
    *, unit: str, category_label: str, title: str,
    categories: list[str], series: list[PresentationSeries],
) -> dict:
    currency_code = {"$": "USD", "USD": "USD", "£": "GBP", "GBP": "GBP", "€": "EUR", "EUR": "EUR"}.get(unit)
    value_format = "percent" if unit == "%" else "currency" if currency_code else "number"
    values = [Decimal(value) for item in series for value in item.values]
    decimal_places = 0 if values and all(value == value.to_integral_value() for value in values) else 2
    y_axis_label = "%" if value_format == "percent" else currency_code or unit
    return {
        "value_format": value_format,
        "currency_code": currency_code,
        "decimal_places": decimal_places,
        "x_axis_label": category_label,
        "y_axis_label": y_axis_label,
        "accessible_summary": (
            f"{title}. {len(categories)} categories and {len(series)} data "
            f"series, derived from the validated answer table."
        ),
    }


def _cells(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _plain(cell: str) -> str:
    return _MARKDOWN.sub("", _CITATION.sub("", cell)).strip()


def _compact(text: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", _plain(text)).strip()
    return value if len(value) <= limit else f"{value[:limit - 1].rstrip()}…"


def _visual_step_label(text: str) -> str:
    value = _compact(text, 110)
    if ":" in value:
        label = value.split(":", 1)[0].strip()
        if 3 <= len(label) <= 70:
            return label
    return value


def _extract_sections(markdown: str) -> list[str]:
    sections = []
    for line in markdown.splitlines():
        match = _HEADING_LINE.match(line.strip())
        if match and (title := _compact(match.group(1), 80)) not in sections:
            sections.append(title)
    return sections[:6]


def _extract_ordered_items(markdown: str) -> list[str]:
    """Extract already-validated numbered content without inventing facts."""
    items: list[str] = []
    current: list[str] = []
    for line in markdown.splitlines():
        match = _ORDERED_LINE.match(line)
        if match:
            if current:
                items.append(_visual_step_label(" ".join(current)))
            current = [match.group(1)]
        elif current and line.strip() and not _HEADING_LINE.match(line.strip()):
            current.append(line.strip())
        elif current:
            items.append(_visual_step_label(" ".join(current)))
            current = []
    if current:
        items.append(_visual_step_label(" ".join(current)))
    return [item for item in items if item][:10]


def _follow_ups(layout: str, query: str) -> list[str]:
    if layout == "calculation":
        return [
            "Explain what this result means.",
            "Show the calculation assumptions and methodology.",
            "Calculate a different scenario.",
        ]
    if _TIMELINE_QUERY.search(query):
        return [
            "Turn this timeline into an owner-and-deadline checklist.",
            "Explain the controls at each stage.",
            "Show the common close bottlenecks.",
        ]
    if _CHECKLIST_QUERY.search(query):
        return [
            "Explain why each checklist item matters.",
            "Show the common mistakes to avoid.",
            "Adapt this checklist for a reviewer.",
        ]
    if layout == "step_by_step":
        return [
            "Turn this answer into a practical checklist.",
            "Explain the common mistakes to avoid.",
            "Show a grounded worked example.",
        ]
    if layout == "comparison":
        return [
            "Highlight the most important differences.",
            "Turn this comparison into a decision checklist.",
            "Explain this comparison with a grounded example.",
        ]
    if layout == "data_visualization":
        return [
            "Explain the main trend shown in this data.",
            "Highlight the largest changes.",
            "Summarize the data for an executive audience.",
        ]
    if layout == "descriptive":
        return [
            "Summarize the key points as a checklist.",
            "Explain this with a grounded example.",
            "What common mistakes should I avoid?",
        ]
    return ["Explain this in more detail.", "Give me a grounded example."]


def _numeric(cell: str) -> tuple[str, str] | None:
    match = _NUMBER.match(_plain(cell))
    if not match:
        return None
    raw = match.group("number").replace(",", "")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if match.group("sign") or match.group("open"):
        value = -value
    currency = match.group("currency") or (match.group("code") or "").upper()
    unit = "%" if match.group("percent") else currency
    return format(value, "f"), unit


def _extract_tables(markdown: str) -> list[tuple[list[str], list[list[str]]]]:
    lines = markdown.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    index = 0
    while index + 1 < len(lines):
        if "|" not in lines[index] or not _TABLE_SEPARATOR.match(lines[index + 1]):
            index += 1
            continue
        headers = [_plain(cell) for cell in _cells(lines[index])]
        rows: list[list[str]] = []
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            row = [_plain(cell) for cell in _cells(lines[index])]
            if len(row) != len(headers):
                break
            rows.append(row)
            index += 1
        if len(headers) >= 2 and rows:
            tables.append((headers, rows))
    return tables


def _is_donut_candidate(
    headers: list[str], series: list[PresentationSeries], unit: str, is_temporal: bool, query: str,
) -> bool:
    """Donut is opt-in only, never inferred from value sign — an ordinary
    2-column comparison (e.g. "Cash | 50000" vs "Receivables | 30000") is
    still a bar comparison, not a proportion, even though both values happen
    to be non-negative. Requires an explicit share/composition/breakdown
    signal in the table's own headers or the user's query, matching the
    same wording that gates automatic charting at all (see _VISUAL_REQUEST)."""
    if is_temporal or len(headers) != 2 or len(series) != 1:
        return False
    return bool(
        unit == "%"
        or _SHARE_HEADER_PATTERN.search(headers[0])
        or _SHARE_HEADER_PATTERN.search(headers[1])
        or _SHARE_HEADER_PATTERN.search(query)
    )


def _cap_donut_slices(
    categories: list[str], series: PresentationSeries,
) -> tuple[list[str], list[PresentationSeries]]:
    """Never render an illegible many-slice donut — beyond the cap, keep the
    largest slices and roll the remainder into one "Other" slice rather than
    silently truncating data out of the chart."""
    if len(categories) <= _MAX_DONUT_SLICES:
        return categories, [series]
    paired = sorted(
        zip(categories, series.values), key=lambda pair: abs(Decimal(pair[1])), reverse=True,
    )
    top = paired[:_MAX_DONUT_SLICES - 1]
    other_total = sum((Decimal(value) for _, value in paired[_MAX_DONUT_SLICES - 1:]), start=Decimal(0))
    capped_categories = [category for category, _ in top] + ["Other"]
    capped_values = [value for _, value in top] + [format(other_total, "f")]
    return capped_categories, [PresentationSeries(name=series.name, values=capped_values)]


def _chart_from_table(
    headers: list[str], rows: list[list[str]], position: int, query: str,
) -> PresentationChart | None:
    if not 2 <= len(rows) <= 12 or len(headers) > 6:
        return None
    categories = [row[0] for row in rows]
    category_header_is_year = bool(headers and re.search(r"\byear\b", headers[0], re.I))
    if any(
        not category
        or (
            _numeric(category)
            and not (category_header_is_year and re.fullmatch(r"\d{4}", category))
        )
        for category in categories
    ):
        return None

    series: list[PresentationSeries] = []
    units: set[str] = set()
    chart_columns = list(range(1, len(headers)))
    # Variance is valuable in the accessible table, but plotting it beside
    # the much larger Budget and Actual series makes their comparison harder
    # to read. Keep variance textual when both primary series are present.
    lowered_headers = {header.lower() for header in headers}
    if {"budget", "actual", "variance"}.issubset(lowered_headers):
        chart_columns = [i for i in chart_columns if headers[i].lower() != "variance"]
    for column in chart_columns:
        parsed = [_numeric(row[column]) for row in rows]
        if any(value is None for value in parsed):
            continue
        values = [value[0] for value in parsed if value is not None]
        column_units = {value[1] for value in parsed if value is not None and value[1]}
        if len(column_units) > 1:
            continue
        units.update(column_units)
        series.append(PresentationSeries(name=headers[column], values=values))

    if not series or len(units) > 1:
        return None
    unit = next(iter(units), "")
    title = headers[0] if len(series) == 1 else f"{headers[0]} comparison"
    is_temporal = bool(re.search(r"\b(period|quarter|month|year|date)\b", headers[0], re.I))

    if _is_donut_candidate(headers, series, unit, is_temporal, query):
        donut_categories, donut_series = _cap_donut_slices(categories, series[0])
        return PresentationChart(
            chart_id=f"answer-table-{position + 1}",
            type="donut",
            title=title,
            categories=donut_categories,
            series=donut_series,
            unit=unit,
            **_chart_display_metadata(
                unit=unit, category_label=headers[0], title=title,
                categories=donut_categories, series=donut_series,
            ),
        )

    if is_temporal:
        chart_type = "area" if len(series) == 1 else "line"
    else:
        chart_type = "bar"
    return PresentationChart(
        chart_id=f"answer-table-{position + 1}",
        type=chart_type,
        title=title,
        categories=categories,
        series=series[:4],
        unit=unit,
        **_chart_display_metadata(
            unit=unit, category_label=headers[0], title=title,
            categories=categories, series=series[:4],
        ),
    )


def _metric_from_table(headers: list[str], rows: list[list[str]], position: int) -> PresentationMetric | None:
    """A table that reduces to exactly one row isn't a chart — it's one
    headline number (e.g. "Total revenue: $482,000"). `_chart_from_table`
    already declines any table with fewer than 2 rows, so this is the
    dedicated path for that case rather than an extension of it."""
    if len(rows) != 1:
        return None
    row = rows[0]
    for column in range(1, len(headers)):
        parsed = _numeric(row[column])
        if parsed is None:
            continue
        value, unit = parsed
        label = _compact(row[0], 60) if not _numeric(row[0]) else headers[column]
        return PresentationMetric(
            metric_id=f"answer-metric-{position + 1}", label=label, value=value, unit=unit,
        )
    return None


def build_answer_presentation(query: str, answer_text: str) -> AnswerPresentation:
    tables = _extract_tables(answer_text)
    is_calculation = bool(_CALCULATION_ANSWER.search(answer_text))
    is_missing_input = bool(_MISSING_INPUT_ANSWER.search(answer_text))
    temporal_table = any(
        headers and re.search(r"\b(period|quarter|month|year|date)\b", headers[0], re.I)
        for headers, _rows in tables
    )
    allow_automatic_chart = bool(_VISUAL_REQUEST.search(query)) or (temporal_table and not is_calculation)
    charts = [
        chart
        for position, (headers, rows) in enumerate(tables)
        if allow_automatic_chart and (chart := _chart_from_table(headers, rows, position, query)) is not None
    ]
    # Not gated by allow_automatic_chart — a table that reduces to one row is
    # already shown as accessible text; rendering it as a stat tile too is a
    # presentation enhancement of data already displayed, not a new chart the
    # user didn't ask for.
    metrics = [
        metric
        for position, (headers, rows) in enumerate(tables)
        if (metric := _metric_from_table(headers, rows, position)) is not None
    ]
    has_steps = bool(_ORDERED_STEP.search(answer_text))
    has_headings = bool(_HEADING.search(answer_text))
    if is_missing_input:
        layout = "concise"
    elif is_calculation:
        layout = "calculation"
    elif has_steps and _TIMELINE_QUERY.search(query):
        layout = "step_by_step"
    elif charts or metrics:
        layout = "data_visualization"
    elif tables or _COMPARE_QUERY.search(query):
        layout = "comparison"
    elif has_steps:
        layout = "step_by_step"
    elif has_headings:
        layout = "descriptive"
    else:
        layout = "concise"
    ordered_items = _extract_ordered_items(answer_text)
    guides: list[PresentationGuide] = []
    if ordered_items and not is_calculation and not is_missing_input:
        # Checked first — a decision-judgment query's numbered considerations
        # take priority over an incidental timeline/checklist keyword also
        # appearing in the same query.
        if is_decision_judgment_query(query):
            guide_type, guide_title = "decision_flow", "Decision considerations"
        elif _TIMELINE_QUERY.search(query):
            guide_type, guide_title = "timeline", "Timeline"
        elif _CHECKLIST_QUERY.search(query):
            guide_type, guide_title = "checklist", "Review checklist"
        else:
            guide_type, guide_title = "process", "Process overview"
        guides.append(PresentationGuide(
            guide_id="answer-guide-1",
            type=guide_type,
            title=guide_title,
            items=ordered_items,
        ))
    return AnswerPresentation(
        layout=layout,
        table_count=len(tables),
        has_steps=has_steps,
        charts=charts,
        metrics=metrics,
        guides=guides,
        sections=(
            _extract_sections(answer_text)
            if layout == "descriptive" and _BROAD_EXPLANATION_QUERY.search(query)
            else []
        ),
        follow_up_questions=[] if is_missing_input else _follow_ups(layout, query),
    )
