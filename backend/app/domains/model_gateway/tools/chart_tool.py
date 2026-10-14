"""Tool-calling schema for chart generation.

Replaces asking the model to hand-write a ```chart fenced JSON block inside
its prose (see websearch.py's _VISUAL_INSTRUCTIONS) with a real function/tool
call: the model proposes typed arguments, this module validates them against
the exact shape AnswerRenderer.tsx can render, and the caller builds the
fenced block from the validated data rather than trusting the model's own
text. The model cannot make the frontend draw a type it never actually
requested through the tool, and a chart labelled "bar" can no longer ship
with a JSON payload the frontend renders as something else — the label and
the data now come from the same validated call.

Deliberately scoped to the 8 chart types AnswerRenderer.tsx actually draws
(bar, line, pie, sankey, scatter, radar, heatmap, candlestick). The unrelated
chart_type Literal in orchestration/schemas.py (gauge, donut, waterfall,
bullet, treemap, kpi) has no renderer wired to it yet — adding those requires
frontend work first, so they are intentionally not offered as tool choices
here; asking for one of them still degrades to the closest real type via the
existing prose instructions, same as today.
"""
from __future__ import annotations

import json
import math
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

TOOL_NAME = "render_chart"


class _Series(BaseModel):
    name: str
    data: list[float]


class BarLineChart(BaseModel):
    # "area": a line filled to the axis (cumulative totals). "waterfall": one
    # series — a starting amount, then signed changes, optionally ending on
    # the running total. Both were drawn as plain line/bar before.
    type: Literal["bar", "line", "area", "waterfall"]
    title: str
    categories: list[str]
    series: list[_Series] = Field(min_length=1)
    stacked: bool = False


class _PieSlice(BaseModel):
    name: str
    value: float


class PieChart(BaseModel):
    type: Literal["pie"]
    title: str
    data: list[_PieSlice] = Field(min_length=1)


class _SankeyNode(BaseModel):
    name: str


class _SankeyLink(BaseModel):
    source: str
    target: str
    value: float


class SankeyChart(BaseModel):
    type: Literal["sankey"]
    title: str
    nodes: list[_SankeyNode] = Field(min_length=1)
    links: list[_SankeyLink] = Field(min_length=1)


class _ScatterSeries(BaseModel):
    name: str
    points: list[list[float]]


class ScatterChart(BaseModel):
    type: Literal["scatter"]
    title: str
    xName: str
    yName: str
    series: list[_ScatterSeries] = Field(min_length=1)


class _RadarIndicator(BaseModel):
    name: str
    max: float


class _RadarSeries(BaseModel):
    name: str
    data: list[float]


class RadarChart(BaseModel):
    type: Literal["radar"]
    title: str
    indicators: list[_RadarIndicator] = Field(min_length=1)
    series: list[_RadarSeries] = Field(min_length=1)


class HeatmapChart(BaseModel):
    type: Literal["heatmap"]
    title: str
    categories: list[str]
    yCategories: list[str]
    cells: list[list[float]]


class CandlestickChart(BaseModel):
    type: Literal["candlestick"]
    title: str
    categories: list[str]
    ohlc: list[list[float]]


ChartArguments = Annotated[
    Union[
        BarLineChart, PieChart, SankeyChart, ScatterChart,
        RadarChart, HeatmapChart, CandlestickChart,
    ],
    Field(discriminator="type"),
]
_chart_adapter: TypeAdapter[ChartArguments] = TypeAdapter(ChartArguments)


# OpenAI/Groq-compatible function-calling tool definition. Hand-authored
# rather than derived from the Pydantic union above: provider tool schemas
# want a flat oneOf keyed on a shared discriminator with per-branch required
# fields, which is what is written here; the Pydantic models above are the
# server-side validation of whatever arguments come back, not a mirror of
# this schema's authoring format.
CHART_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Render a data chart. Use this whenever the answer includes "
            "quantitative data suited to a chart (a trend, a comparison "
            "across categories, a breakdown of a whole, a flow between "
            "stages, a correlation, a ratio profile, a value across two "
            "dimensions, or OHLC price data) — do not describe the chart in "
            "prose instead of calling this. Only use figures given by the "
            "user, correctly computed from them, or present in the provided "
            "sources; never invent illustrative numbers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["bar", "line", "area", "waterfall", "pie", "sankey", "scatter", "radar", "heatmap", "candlestick"],
                    "description": (
                        "'line' for a trend over time; 'area' for a cumulative or filled trend; "
                        "'waterfall' for a bridge from a starting amount through signed changes to a "
                        "result (one series: start, then each change, optionally the final total); "
                        "'bar' for comparisons across categories "
                        "(add stacked=true when the series are parts of a total); 'pie' for parts "
                        "of a single whole; 'sankey' for a flow between stages; 'scatter' for "
                        "correlation between two measures; 'radar' for comparing several ratios on "
                        "one profile; 'heatmap' for a value across two dimensions; 'candlestick' "
                        "only for open/close/low/high price data."
                    ),
                },
                "title": {"type": "string"},
                "categories": {
                    "type": "array", "items": {"type": "string"},
                    "description": "bar/line/heatmap/candlestick: the x-axis periods or categories.",
                },
                "series": {
                    "type": "array",
                    "description": "bar/line/scatter/radar: one entry per named series.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "data": {"type": "array", "items": {"type": "number"}},
                            "points": {
                                "type": "array",
                                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                            },
                        },
                        "required": ["name"],
                    },
                },
                "stacked": {"type": "boolean", "description": "bar only: true when series are parts of a total."},
                "data": {
                    "type": "array",
                    "description": "pie: one entry per slice.",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "value": {"type": "number"}},
                        "required": ["name", "value"],
                    },
                },
                "nodes": {
                    "type": "array",
                    "description": "sankey: every stage referenced by links.",
                    "items": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                },
                "links": {
                    "type": "array",
                    "description": "sankey: flows between nodes.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"}, "target": {"type": "string"}, "value": {"type": "number"},
                        },
                        "required": ["source", "target", "value"],
                    },
                },
                "xName": {"type": "string", "description": "scatter: x-axis label."},
                "yName": {"type": "string", "description": "scatter: y-axis label."},
                "indicators": {
                    "type": "array",
                    "description": "radar: one axis per ratio, with its scale max.",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "max": {"type": "number"}},
                        "required": ["name", "max"],
                    },
                },
                "yCategories": {"type": "array", "items": {"type": "string"}, "description": "heatmap: y-axis categories."},
                "cells": {
                    "type": "array",
                    "description": "heatmap: [xIndex, yIndex, value] rows. candlestick: [open, close, low, high] rows (use 'ohlc').",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "ohlc": {
                    "type": "array",
                    "description": "candlestick: one [open, close, low, high] row per category.",
                    "items": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                },
            },
            "required": ["type", "title"],
        },
    },
}


class ChartToolError(ValueError):
    """Arguments the model passed to render_chart failed validation."""


def build_chart_fence(raw_arguments: str) -> str:
    """Validate a render_chart tool call's raw (JSON string) arguments and
    return the exact ```chart fenced block AnswerRenderer.tsx parses.

    Raises ChartToolError on malformed JSON or a shape that doesn't match any
    supported chart type — the caller falls back to the model's own prose
    (which may still contain a hand-written ```chart block) rather than
    surfacing this as a user-facing failure.
    """
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ChartToolError(f"render_chart arguments were not valid JSON: {exc}") from exc

    try:
        chart = _chart_adapter.validate_python(parsed)
    except ValidationError as exc:
        raise ChartToolError(f"render_chart arguments did not match a known chart shape: {exc}") from exc

    spec = chart.model_dump(exclude_none=True, exclude_defaults=False)

    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ChartToolError("Chart values must be finite numbers")
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)

    finite(spec)
    if isinstance(chart, BarLineChart):
        if not chart.categories or any(len(series.data) != len(chart.categories) for series in chart.series):
            raise ChartToolError("Every series must have exactly one value per category")
        if chart.type == "waterfall" and len(chart.series) != 1:
            raise ChartToolError("Waterfall charts require one signed series")
    elif isinstance(chart, PieChart):
        if any(item.value < 0 for item in chart.data) or sum(item.value for item in chart.data) <= 0:
            raise ChartToolError("Pie charts require non-negative parts with a positive total")
    elif isinstance(chart, ScatterChart):
        if any(not series.points or any(len(point) != 2 for point in series.points) for series in chart.series):
            raise ChartToolError("Scatter observations must be x/y pairs")
    elif isinstance(chart, RadarChart):
        if any(indicator.max <= 0 for indicator in chart.indicators) or any(
            len(series.data) != len(chart.indicators) or any(value < 0 or value > indicator.max for value, indicator in zip(series.data, chart.indicators))
            for series in chart.series
        ):
            raise ChartToolError("Radar values must match the indicators and their bounds")
    elif isinstance(chart, HeatmapChart):
        if not chart.categories or not chart.yCategories or any(
            len(cell) != 3 or cell[0] != int(cell[0]) or cell[1] != int(cell[1])
            or not 0 <= cell[0] < len(chart.categories) or not 0 <= cell[1] < len(chart.yCategories)
            for cell in chart.cells
        ):
            raise ChartToolError("Heatmap cells require valid x/y indexes and a value")
        if len({(cell[0], cell[1]) for cell in chart.cells}) != len(chart.cells):
            raise ChartToolError("Heatmap cell coordinates must be unique")
    elif isinstance(chart, SankeyChart):
        names = {node.name for node in chart.nodes}
        if len(names) != len(chart.nodes) or any(
            link.source not in names or link.target not in names or link.source == link.target or link.value < 0
            for link in chart.links
        ):
            raise ChartToolError("Sankey flows require distinct existing nodes and non-negative values")
    elif isinstance(chart, CandlestickChart):
        if len(chart.ohlc) != len(chart.categories) or any(
            len(row) != 4 or row[2] > min(row[0], row[1]) or row[3] < max(row[0], row[1]) or row[2] > row[3]
            for row in chart.ohlc
        ):
            raise ChartToolError("Candlesticks require matching dates and valid open/close/low/high values")
    if spec.get("type") != "bar":
        spec.pop("stacked", None)
    return "```chart\n" + json.dumps(spec) + "\n```"


# ── Registry entry ───────────────────────────────────────────────────────────
# The same render_chart tool, declared through the agent tool registry. The
# model-facing schema is CHART_TOOL_SCHEMA's hand-written parameters; the
# args model only accepts the object, and build_chart_fence() remains the
# real validation, so a chart can reach the answer only via validated data.
from pydantic import ConfigDict  # noqa: E402

from app.domains.identity.permissions import KRITON_TOOL_ROLES
from app.domains.model_gateway.tool_registry import ToolResult, ToolSpec  # noqa: E402


class _ChartToolArgs(BaseModel):
    model_config = ConfigDict(extra="allow")


async def _handle_render_chart(args: _ChartToolArgs) -> ToolResult:
    try:
        fence = build_chart_fence(json.dumps(args.model_dump()))
    except ChartToolError as exc:
        return ToolResult.failure(
            "invalid_arguments",
            f"The chart could not be rendered ({str(exc)[:300]}). Fix the arguments or explain the data in text.",
        )
    return ToolResult(
        ok=True,
        content=(
            "Chart rendered successfully. It is attached automatically BELOW your answer — "
            "refer to it as 'the chart below' if at all, and do not restate its JSON."
        ),
        artifacts=(fence,),
    )


RENDER_CHART_TOOL = ToolSpec(
    name=TOOL_NAME,
    version="1.0",
    description=CHART_TOOL_SCHEMA["function"]["description"],
    args_model=_ChartToolArgs,
    handler=_handle_render_chart,
    data_source="figures already in the conversation or returned by other tools",
    risk_level="low",
    timeout_seconds=2.0,
    allowed_roles=KRITON_TOOL_ROLES,
    tenant_scope="none",
    owner="Frontend / Visualization",
    parameters_schema=CHART_TOOL_SCHEMA["function"]["parameters"],
)
