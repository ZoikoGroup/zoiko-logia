"""
ResponsePlanner — decides whether an answer needs a visual at all, before any
visualization-family/type decision is made. Deterministic; no LLM call.

Scope note (see intent_classifier.py / data_shape.py docstrings): only the
response modes backed by a real evidence source today are produced —
TEXT_ONLY, TEXT_KPI, TEXT_TABLE, TEXT_CHART, TEXT_GRAPH, TEXT_FLOWCHART.
TEXT_WORKFLOW/TEXT_TIMELINE/TEXT_MULTI_VISUAL/VISUAL_ONLY are defined for
forward compatibility with the fuller spec but are never returned by
plan_response() yet — nothing in this codebase produces workflow/timeline
evidence, and TEXT_MULTI_VISUAL specifically isn't a distinct response_mode
here: multi-visual composition (spec §17) is expressed via
AskKritonResponse.secondary_visualizations alongside whatever primary mode
was already selected, not as its own mode (TEXT_FLOWCHART here means the
user-supplied-stages PROCESS_FLOW path — see extraction.py — not the
removed LLM-authored Mermaid path).
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from app.orchestration.data_shape import (
    DIRECTED_STAGES, NODES_EDGES, NONE, OHLC, PART_TO_WHOLE, SCALAR, TIME_SERIES, XY_NUMERIC,
)
from app.orchestration.intent_classifier import (
    COMPOSITION, CORRELATION, CURRENT_METRIC, DISTRIBUTION, GRAPH_INTENTS, PRECISE_DATA, PROCESS, TREND,
)
from app.orchestration.visualization.domain import classify_domain_context

TEXT_ONLY = "TEXT_ONLY"
TEXT_KPI = "TEXT_KPI"
TEXT_TABLE = "TEXT_TABLE"
TEXT_CHART = "TEXT_CHART"
TEXT_GRAPH = "TEXT_GRAPH"
TEXT_FLOWCHART = "TEXT_FLOWCHART"
TEXT_WORKFLOW = "TEXT_WORKFLOW"
TEXT_TIMELINE = "TEXT_TIMELINE"
TEXT_MULTI_VISUAL = "TEXT_MULTI_VISUAL"
VISUAL_ONLY = "VISUAL_ONLY"

STATISTICAL = "STATISTICAL"
RELATIONSHIP = "RELATIONSHIP"
PROCESS_FAMILY = "PROCESS"
COMPOSITION_FAMILY = "COMPOSITION"
FINANCIAL_FAMILY = "FINANCIAL"

# Section 22 — explicit visual requests, scoped to the visual families this
# pipeline can actually satisfy with real, non-fabricated data.
_EXPLICIT_CHART_HINTS = re.compile(
    r"\b(make (a|it a)?\s*chart|show (this |it )?as a chart|as a (line|bar) chart|"
    r"line chart|chart (?:of|for)|plot (?:this|it|the|a)|give me a chart|only the chart|show only the chart|"
    r"plain line|dashed line|dotted line|dash[ -]?dot line|value[ -]?labell?ed line|"
    r"area (chart )?with markers?|area \+ markers?|vertical bar|horizontal bar|"
    r"clustered bar|diverging bar|waterfall chart|scatter plot|"
    r"treemap|radar chart|box plot|box-and-whisker|box and whisker|whisker plot|"
    r"pie chart|donut chart|as a table|in table form|in tabular form|"
    r"show (?:the |me )?(?:underlying |raw |source )?table)\b",
    re.I,
)
_EXPLICIT_GRAPH_HINTS = re.compile(
    r"\b(interactive graph|evidence network|visualize every|show the (evidence )?network|"
    r"as a graph|as an? network|show this relationship as an? network|"
    r"as an? (evidence|relationship) graph|relationship diagram|knowledge graph|"
    r"(?:show|create|draw|render) (?:this |an? )?(?:relationship )?graph|"
    r"(?:g6|cytoscape)(?:\.js)? (?:evidence |relationship )?(?:graph|network)|"
    r"use (?:g6|cytoscape)(?:\.js)? to (?:show|visuali[sz]e))\b",
    re.I,
)
_EXPLICIT_FLOW_HINTS = re.compile(
    r"\b(show this as a flowchart|as a flowchart|flow diagram|process flow|process diagram|"
    r"as a workflow|interactive workflow|mermaid (?:flowchart|flow|diagram)|x6 (?:workflow|flow|diagram))\b",
    re.I,
)
_EXPLICIT_HEATMAP_HINTS = re.compile(r"\b(as a heatmap|heat ?map|matrix view|adjacency matrix|matrix of)\b", re.I)
# Distinct from _EXPLICIT_FLOW_HINTS: "show this as a flowchart" asks for a
# flow visual but not necessarily an INTERACTIVE one — X6 vs Mermaid routing
# (orchestrator.py's _build_process_flow_spec) needs to know specifically
# whether interactivity was requested, per the design spec's own rule
# ("if user_requests_interactivity: X6; elif complexity >= threshold: X6;
# else: MERMAID").
_EXPLICIT_INTERACTIVE_FLOW_HINTS = re.compile(
    # Allow a short domain qualifier between "interactive" and the format:
    # "interactive accounts-payable workflow", "interactive AML process".
    # The old adjacent-word-only pattern silently routed these very natural
    # prompts to read-only Mermaid instead of X6.
    r"\b(?:interactive(?:\s+[\w-]+){0,4}\s+(workflow|flow|diagram|process)|"
    r"x6 (?:workflow|flow|diagram))\b", re.I,
)
_G6_REQUEST = re.compile(r"\bg6(?:\.js)?\b", re.I)
_CYTOSCAPE_REQUEST = re.compile(r"\bcytoscape(?:\.js)?\b", re.I)
_MERMAID_REQUEST = re.compile(r"\bmermaid\b", re.I)
_X6_REQUEST = re.compile(r"\bx6\b", re.I)
_CHART_VARIANTS = (
    # GROUPED_BAR_CHART/STACKED_BAR_CHART must come BEFORE the bare
    # "bar chart" pattern below — detect_requested_chart_variant() returns
    # the FIRST match in table order, and "grouped bar chart"/"stacked bar
    # chart" both also contain the substring "bar chart", so the longer,
    # more specific phrase has to be checked first or it would always lose
    # to a plain BAR_CHART match.
    ("HUNDRED_PERCENT_STACKED_HORIZONTAL_BAR", re.compile(r"\b(100%|100 percent) stacked horizontal bar\b", re.I)),
    ("STACKED_HORIZONTAL_BAR", re.compile(r"\bstacked horizontal bar\b", re.I)),
    ("HUNDRED_PERCENT_STACKED_BAR", re.compile(r"\b(100%|100 percent) stacked (vertical )?bar\b", re.I)),
    ("GROUPED_BAR_CHART", re.compile(r"\b(grouped|clustered) bar(?: chart| \(multi-series\))?\b", re.I)),
    ("STACKED_BAR_CHART", re.compile(r"\bstacked (vertical )?bar(?: chart)?\b", re.I)),
    ("HORIZONTAL_BAR", re.compile(r"\bhorizontal bar(?: chart)?\b", re.I)),
    ("DIVERGING_BAR", re.compile(r"\bdiverging bar(?: chart)?\b", re.I)),
    ("WATERFALL_CHART", re.compile(r"\bwaterfall(?: chart)?\b", re.I)),
    ("SCATTER_TREND", re.compile(r"\b(scatter plot with (a )?trend line|scatter trend|regression plot|correlation plot)\b", re.I)),
    ("STANDARD_SCATTER", re.compile(r"\bscatter plot\b", re.I)),
    ("TREEMAP_CHART", re.compile(r"\btreemap(?: chart)?\b", re.I)),
    ("RADAR_CHART", re.compile(r"\bradar chart\b", re.I)),
    ("BAR_CHART", re.compile(r"\bvertical bar(?: chart)?\b", re.I)),
    ("BAR_CHART", re.compile(r"\b(bar chart|column chart)\b", re.I)),
    ("AREA_WITH_MARKERS", re.compile(r"\b(area (chart )?with markers?|area \+ markers?)\b", re.I)),
    ("VALUE_LABELED_LINE", re.compile(r"\b(value[ -]?labell?ed line|line with value labels?)\b", re.I)),
    ("DASH_DOT_LINE", re.compile(r"\b(dash[ -]?dot line)\b", re.I)),
    ("DASHED_LINE", re.compile(r"\b(dashed line)\b", re.I)),
    ("DOTTED_LINE", re.compile(r"\b(dotted line)\b", re.I)),
    ("STEP_LINE_CHART", re.compile(r"\b(step[ -]?line|stepped[ -]?line)\b", re.I)),
    ("SPLINE_LINE_CHART", re.compile(r"\b(spline|smooth spline|smooth(?:ed)? line)\b", re.I)),
    ("AREA_CHART", re.compile(r"\b(area chart|filled line|filled area)\b", re.I)),
    ("LINE_WITH_MARKERS", re.compile(r"\b(line with markers?|marked line)\b", re.I)),
    ("PLAIN_LINE", re.compile(r"\bplain line\b", re.I)),
    ("BOX_PLOT", re.compile(r"\b(box plot|box-and-whisker|box and whisker|whisker plot)\b", re.I)),
)


class ResponsePlan(BaseModel):
    intent: str
    response_mode: str
    visual_required: bool
    visual_family: str | None = None
    explicit_visual_request: bool = False
    explicit_heatmap_request: bool = False
    explicit_interactive_request: bool = False
    confidence: float
    domain: str = "GENERAL"
    subdomain: str = "GENERAL"
    requested_chart_variant: str | None = None
    preferred_graph_engine: str | None = None
    preferred_flow_engine: str | None = None


def _make_plan(query: str, **values) -> ResponsePlan:
    context = classify_domain_context(query, values.get("intent"))
    values.setdefault("requested_chart_variant", detect_requested_chart_variant(query))
    values.setdefault("preferred_graph_engine", detect_preferred_graph_engine(query))
    values.setdefault("preferred_flow_engine", detect_preferred_flow_engine(query))
    return ResponsePlan(domain=context.domain, subdomain=context.subdomain, **values)


def detect_explicit_visual_request(query: str) -> bool:
    q = query or ""
    return bool(
        _EXPLICIT_CHART_HINTS.search(q)
        or _EXPLICIT_GRAPH_HINTS.search(q)
        or _EXPLICIT_FLOW_HINTS.search(q)
        or _EXPLICIT_HEATMAP_HINTS.search(q)
        or detect_requested_chart_variant(q) is not None
    )


def detect_explicit_heatmap_request(query: str) -> bool:
    return bool(_EXPLICIT_HEATMAP_HINTS.search(query or ""))


def detect_explicit_interactive_request(query: str) -> bool:
    return bool(_EXPLICIT_INTERACTIVE_FLOW_HINTS.search(query or ""))


def detect_preferred_graph_engine(query: str) -> str | None:
    if _G6_REQUEST.search(query or ""):
        return "g6"
    if _CYTOSCAPE_REQUEST.search(query or ""):
        return "cytoscape"
    return None


def detect_preferred_flow_engine(query: str) -> str | None:
    if _X6_REQUEST.search(query or ""):
        return "x6"
    if _MERMAID_REQUEST.search(query or ""):
        return "mermaid"
    return None


def detect_requested_chart_variant(query: str) -> str | None:
    for variant, pattern in _CHART_VARIANTS:
        if pattern.search(query or ""):
            return variant
    return None


def plan_response(query: str, intent: str, data_shape: str) -> ResponsePlan:
    explicit = detect_explicit_visual_request(query)
    explicit_heatmap = detect_explicit_heatmap_request(query)

    if data_shape == NODES_EDGES and intent in GRAPH_INTENTS:
        return _make_plan(query,
            intent=intent, response_mode=TEXT_GRAPH, visual_required=True,
            visual_family=RELATIONSHIP, explicit_visual_request=explicit,
            explicit_heatmap_request=explicit_heatmap,
            confidence=0.9,
        )

    if data_shape == DIRECTED_STAGES and intent == PROCESS:
        return _make_plan(query,
            intent=intent, response_mode=TEXT_FLOWCHART, visual_required=True,
            visual_family=PROCESS_FAMILY, explicit_visual_request=explicit,
            explicit_interactive_request=detect_explicit_interactive_request(query),
            confidence=0.9,
        )

    if data_shape == XY_NUMERIC and intent == CORRELATION:
        return _make_plan(query,
            intent=intent, response_mode=TEXT_CHART, visual_required=True,
            visual_family=STATISTICAL, explicit_visual_request=explicit,
            confidence=0.9,
        )

    if data_shape == PART_TO_WHOLE and intent == COMPOSITION:
        return _make_plan(query,
            intent=intent, response_mode=TEXT_CHART, visual_required=True,
            visual_family=COMPOSITION_FAMILY, explicit_visual_request=explicit,
            confidence=0.9,
        )

    # Real OHLC bars (market_data.py's fetch_market_sources()) — gated on
    # data_shape alone (see data_shape.py's own note on why), not on intent,
    # same as PART_TO_WHOLE/XY_NUMERIC's evidence-field-presence gating.
    if data_shape == OHLC:
        return _make_plan(query,
            intent=intent, response_mode=TEXT_CHART, visual_required=True,
            visual_family=FINANCIAL_FAMILY, explicit_visual_request=explicit,
            confidence=0.9,
        )

    # No structured evidence at all: never fabricate a chart from nothing,
    # regardless of what the user asked for or how the question reads.
    if data_shape == NONE:
        return _make_plan(query,
            intent=intent, response_mode=TEXT_ONLY, visual_required=False, confidence=0.9,
        )

    if data_shape == TIME_SERIES and (intent in (TREND, DISTRIBUTION) or explicit):
        return _make_plan(query,
            intent=intent, response_mode=TEXT_CHART, visual_required=True,
            visual_family=STATISTICAL, explicit_visual_request=explicit,
            confidence=0.94 if intent in (TREND, DISTRIBUTION) else 0.8,
        )

    # PRECISE_DATA over a real multi-point series wants every value laid out
    # ("give me the exact figures/transactions"), not summarized into a
    # single latest-value KPI or collapsed into a trend line. TIME_SERIES
    # always has >=3 observations (data_shape.py's own threshold), so
    # rules.py's TABLE candidate (which needs >=2) is always reachable here.
    if data_shape == TIME_SERIES and intent == PRECISE_DATA:
        return _make_plan(query,
            intent=intent, response_mode=TEXT_TABLE, visual_required=True,
            visual_family=STATISTICAL, explicit_visual_request=explicit,
            confidence=0.88,
        )

    if data_shape in (SCALAR, TIME_SERIES) and intent in (CURRENT_METRIC, PRECISE_DATA):
        return _make_plan(query,
            intent=intent, response_mode=TEXT_KPI, visual_required=True,
            visual_family=STATISTICAL, explicit_visual_request=explicit,
            confidence=0.85,
        )

    # Evidence exists but the question isn't asking to see it plotted —
    # answer in text, cite the figure inline. Matches the "don't attach
    # unrelated visualizations" rule (spec §20).
    return _make_plan(query, intent=intent, response_mode=TEXT_ONLY, visual_required=False, confidence=0.6)
