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
    DIRECTED_STAGES, NODES_EDGES, NONE, PART_TO_WHOLE, SCALAR, TIME_SERIES, XY_NUMERIC,
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

# Section 22 — explicit visual requests, scoped to the visual families this
# pipeline can actually satisfy with real, non-fabricated data.
_EXPLICIT_CHART_HINTS = re.compile(
    r"\b(make (a|it a)?\s*chart|show (this |it )?as a chart|as a (line|bar) chart|"
    r"plot (this|it)|give me a chart|only the chart|show only the chart|"
    r"box plot|box-and-whisker|box and whisker|whisker plot)\b",
    re.I,
)
_EXPLICIT_GRAPH_HINTS = re.compile(
    r"\b(interactive graph|evidence network|visualize every|show the (evidence )?network|"
    r"as a graph|as an? (evidence|relationship) graph)\b",
    re.I,
)
_EXPLICIT_FLOW_HINTS = re.compile(
    # "flow diagram" / "process diagram" / "flow chart" (two words) are as
    # natural as "flowchart", and an adjacency-only pattern missed all of them:
    # "explain the types of taxes with visuals (flow diagram)" scored
    # visual_required=False, so nothing was drawn and nothing asked the model to
    # draw either. The leading "as a" is optional for the same reason — a
    # request can name the format without that preposition.
    r"\b(show this as a flowchart|as a flowchart|as a workflow|interactive workflow|"
    r"flow ?charts?|flow diagrams?|process (?:flow|diagram)s?|"
    r"workflow diagrams?|decision trees?|org(?:anisation|anization)? charts?)\b",
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
    r"\binteractive(?:\s+[\w-]+){0,4}\s+(workflow|flow|diagram|process)\b", re.I,
)
_CHART_VARIANTS = (
    ("BAR_CHART", re.compile(r"\b(bar chart|column chart)\b", re.I)),
    ("STEP_LINE_CHART", re.compile(r"\b(step line|stepped line)\b", re.I)),
    ("SPLINE_LINE_CHART", re.compile(r"\b(spline|smoothed? line)\b", re.I)),
    ("AREA_CHART", re.compile(r"\b(area chart|filled line)\b", re.I)),
    ("LINE_WITH_MARKERS", re.compile(r"\b(line with markers?|marked line)\b", re.I)),
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


def _make_plan(query: str, **values) -> ResponsePlan:
    context = classify_domain_context(query, values.get("intent"))
    values.setdefault("requested_chart_variant", detect_requested_chart_variant(query))
    return ResponsePlan(domain=context.domain, subdomain=context.subdomain, **values)


def detect_explicit_visual_request(query: str) -> bool:
    q = query or ""
    return bool(_EXPLICIT_CHART_HINTS.search(q) or _EXPLICIT_GRAPH_HINTS.search(q) or _EXPLICIT_FLOW_HINTS.search(q))


def detect_explicit_heatmap_request(query: str) -> bool:
    return bool(_EXPLICIT_HEATMAP_HINTS.search(query or ""))


def detect_explicit_interactive_request(query: str) -> bool:
    return bool(_EXPLICIT_INTERACTIVE_FLOW_HINTS.search(query or ""))


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
