"""Deterministic presentation planning for already-validated answer text.

This module never generates facts. It only inspects the user query and the
final Markdown answer that has already passed Checkpoint C. Numeric charts are
derived exclusively from complete numeric columns in GFM tables, keeping the
table as the accessible textual source of truth.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.orchestration.schemas import (
    AnswerPresentation,
    PresentationChart,
    PresentationGuide,
    PresentationSeries,
)


_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_CITATION = re.compile(r"\s*\[REF-\d+\]\s*")
_MARKDOWN = re.compile(r"[*_`]")
_ORDERED_STEP = re.compile(r"(?m)^\s*\d+[.)]\s+")
_HEADING = re.compile(r"(?m)^#{1,4}\s+")
_HEADING_LINE = re.compile(r"^#{1,4}\s+(.+?)\s*$")
_ORDERED_LINE = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")
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
_VISUAL_REQUEST = re.compile(r"\b(chart|graph|visuali[sz]e|plot)\b", re.IGNORECASE)
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


def _chart_from_table(headers: list[str], rows: list[list[str]], position: int) -> PresentationChart | None:
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
    title = headers[0] if len(series) == 1 else f"{headers[0]} comparison"
    chart_type = "line" if re.search(r"\b(period|quarter|month|year|date)\b", headers[0], re.I) else "bar"
    return PresentationChart(
        chart_id=f"answer-table-{position + 1}",
        type=chart_type,
        title=title,
        categories=categories,
        series=series[:4],
        unit=next(iter(units), ""),
    )


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
        if allow_automatic_chart and (chart := _chart_from_table(headers, rows, position)) is not None
    ]
    has_steps = bool(_ORDERED_STEP.search(answer_text))
    has_headings = bool(_HEADING.search(answer_text))
    if is_missing_input:
        layout = "concise"
    elif is_calculation:
        layout = "calculation"
    elif has_steps and _TIMELINE_QUERY.search(query):
        layout = "step_by_step"
    elif charts:
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
        if _TIMELINE_QUERY.search(query):
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
        guides=guides,
        sections=(
            _extract_sections(answer_text)
            if layout == "descriptive" and _BROAD_EXPLANATION_QUERY.search(query)
            else []
        ),
        follow_up_questions=[] if is_missing_input else _follow_ups(layout, query),
    )
