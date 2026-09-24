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
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

TOOL_NAME = "render_chart"


class _Series(BaseModel):
    name: str
    data: list[float]


class BarLineChart(BaseModel):
    type: Literal["bar", "line"]
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
                    "enum": ["bar", "line", "pie", "sankey", "scatter", "radar", "heatmap", "candlestick"],
                    "description": (
                        "'line' for a trend over time; 'bar' for comparisons across categories "
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
    if spec.get("type") != "bar":
        spec.pop("stacked", None)
    return "```chart\n" + json.dumps(spec) + "\n```"
