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
    DIRECTED_STAGES, NODES_EDGES, NONE, OHLC, PART_TO_WHOLE, SCALAR, SCALAR_TARGET,
    TIME_SERIES, XY_NUMERIC,
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
    # "chart", "graph" and "plot" are interchangeable to users — the same
    # widening applied to _CHART_VARIANTS below, for the same reason.
    r"(?:line|bar|column)\s*(?:chart|graph|plot)|"
    r"chart (?:of|for)|plot (?:this|it|the|a)|give me a chart|only the chart|show only the chart|"
    r"plain line|dashed line|dotted line|dash[ -]?dot line|value[ -]?labell?ed line|"
    r"area (chart )?with markers?|area \+ markers?|vertical bar|horizontal bar|"
    r"clustered bar|diverging bar|waterfall chart|scatter\s*plot|scatter chart|"
    # NOT widened to "histogram"/"candlestick": this regex answers "did the
    # user ask for a visual at all", and a true answer lets every capability
    # carrying the __EXPLICIT_VISUAL__ wildcard match ANY intent. Adding those
    # two let the generic line_chart (priority 0.90) outrank the histogram
    # capability (0.85) on a distribution question and silently swallow it.
    # detect_requested_chart_variant below already records those requests.
    r"treemap|tree map|radar chart|box\s*plot|box-and-whisker|box and whisker|whisker plot|"
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
# Users write "chart", "graph", "plot" and "diagram" interchangeably, and
# routinely close the space ("barchart", "scatterplot"). Matching only the one
# spelling a developer happened to think of is why "bar graph" silently
# produced a LINE chart: the variant went undetected, the BAR capability was
# filtered out for want of its requested_variant, and the default line_chart
# won unopposed. Every pattern below accepts the whole family of spellings.
_KIND = r"(?:\s*(?:chart|graph|plot|diagram))"
_CHART_VARIANTS = (
    # GROUPED_BAR_CHART/STACKED_BAR_CHART must come BEFORE the bare
    # "bar chart" pattern below — detect_requested_chart_variant() returns
    # the FIRST match in table order, and "grouped bar chart"/"stacked bar
    # chart" both also contain the substring "bar chart", so the longer,
    # more specific phrase has to be checked first or it would always lose
    # to a plain BAR_CHART match.
    ("HUNDRED_PERCENT_STACKED_HORIZONTAL_BAR",
     re.compile(rf"\b(?:100\s*%|100\s+percent|hundred\s+percent)\s+stacked\s+horizontal\s+bars?{_KIND}?\b", re.I)),
    ("STACKED_HORIZONTAL_BAR", re.compile(rf"\bstacked\s+horizontal\s+bars?{_KIND}?\b", re.I)),
    ("HUNDRED_PERCENT_STACKED_BAR",
     re.compile(rf"\b(?:100\s*%|100\s+percent|hundred\s+percent)\s+stacked\s+(?:vertical\s+)?bars?{_KIND}?\b", re.I)),
    ("GROUPED_BAR_CHART",
     re.compile(rf"\b(?:grouped|clustered|multi[\s-]?series)\s+bars?(?:{_KIND}| \(multi-series\))?\b", re.I)),
    ("STACKED_BAR_CHART", re.compile(rf"\bstacked\s+(?:vertical\s+)?bars?{_KIND}?\b", re.I)),
    ("HORIZONTAL_BAR", re.compile(rf"\bhorizontal\s+bars?{_KIND}?\b", re.I)),
    ("DIVERGING_BAR", re.compile(rf"\bdiverging\s+bars?{_KIND}?\b", re.I)),
    ("WATERFALL_CHART", re.compile(rf"\bwaterfall{_KIND}?\b", re.I)),
    ("SCATTER_TREND",
     re.compile(r"\b(?:scatter\s*(?:plot\s*)?with\s+(?:a\s+)?trend\s*line|scatter\s*trend|"
                r"regression\s*plot|correlation\s*plot)\b", re.I)),
    # Bare "scatter" is safe here: nothing else in an accounting question uses
    # the word, and requiring the "plot" suffix is what made "scatterplot" miss.
    ("STANDARD_SCATTER", re.compile(rf"\bscatter{_KIND}?\b", re.I)),
    ("TREEMAP_CHART", re.compile(rf"\btree\s*map{_KIND}?\b", re.I)),
    # "spider" must carry an explicit chart word; "radar" alone is unambiguous.
    ("RADAR_CHART", re.compile(rf"\b(?:radar{_KIND}?|spider{_KIND})\b", re.I)),
    # "vertical bar" folded in here rather than kept as its own entry — both
    # spellings resolve to the same BAR_CHART variant.
    ("BAR_CHART",
     re.compile(rf"\b(?:vertical\s+bars?{_KIND}?|bar{_KIND}|column{_KIND}|"
                r"(?:as|in|using)\s+bars)\b", re.I)),
    ("AREA_WITH_MARKERS", re.compile(r"\b(?:area\s*(?:chart\s*)?with\s+markers?|area\s*\+\s*markers?)\b", re.I)),
    ("VALUE_LABELED_LINE", re.compile(r"\b(?:value[\s-]?labell?ed\s+line|line\s+with\s+value\s+labels?)\b", re.I)),
    ("DASH_DOT_LINE", re.compile(r"\bdash[\s-]?dot\s+line\b", re.I)),
    ("DASHED_LINE", re.compile(r"\bdashed\s+line\b", re.I)),
    ("DOTTED_LINE", re.compile(r"\bdotted\s+line\b", re.I)),
    ("STEP_LINE_CHART", re.compile(r"\b(?:step|stepped)[\s-]?line\b", re.I)),
    ("SPLINE_LINE_CHART", re.compile(r"\b(?:spline|smooth\s+spline|smooth(?:ed)?\s+line)\b", re.I)),
    ("AREA_CHART", re.compile(rf"\b(?:area{_KIND}|filled\s+line|filled\s+area)\b", re.I)),
    # Optional "chart", as AREA_WITH_MARKERS allows: without it "line chart
    # with markers" fell through to STANDARD_LINE and drew a plain line.
    ("LINE_WITH_MARKERS", re.compile(r"\b(?:line\s*(?:chart\s*)?with\s+markers?|marked\s+line)\b", re.I)),
    ("PLAIN_LINE", re.compile(r"\bplain\s+line\b", re.I)),
    ("SWIMLANE_DIAGRAM", re.compile(r"\bswim[\s-]?lanes?\b", re.I)),
    ("BOX_PLOT", re.compile(r"\b(?:box\s*plot|box[\s-]?and[\s-]?whisker|whisker\s*plot)\b", re.I)),
    # These two name types that are already the DEFAULT for their data shape,
    # so their capabilities carry no requested_variant gate and win on shape
    # and intent alone. Listing them makes the request *recorded*, which is
    # what lets a substitution be reported honestly. They must stay last:
    # every pattern above is a more specific spelling of the same words.
    #
    # Deliberately NOT listed here: "histogram" and "candlestick".
    # detect_explicit_visual_request() falls through to this table, so an
    # entry here also flips explicit_visual_request to True — which lets every
    # capability carrying the __EXPLICIT_VISUAL__ wildcard match ANY intent.
    # For "create a histogram of these values" that handed the route to the
    # generic line_chart (priority 0.90) over the histogram capability (0.85),
    # silently turning a requested histogram into a line. Both types are
    # reachable without an entry here, and a request for a chart that CANNOT
    # be drawn still gets its note, because the note compares the delivered
    # route's variant rather than this table's verdict.
    # Pie and donut are separate requests, not synonyms: one has a hole and
    # the other does not, and a reader who asked for a pie and received a ring
    # was never told why. PIE_CHART first — neither pattern is a prefix of the
    # other, but keeping the more specific word ahead matches the table's
    # convention.
    ("PIE_CHART", re.compile(rf"\bpie{_KIND}?\b", re.I)),
    ("DONUT_CHART", re.compile(rf"\b(?:donut{_KIND}?|doughnut{_KIND}?|ring\s+chart)\b", re.I)),
    ("STANDARD_LINE", re.compile(rf"\bline{_KIND}\b", re.I)),
    # ── Named, but not routable ──────────────────────────────────────────
    # No capability carries these variants, so nothing can be drawn for them.
    # They are listed for exactly that reason: an unrecognised chart name
    # left requested_chart_variant at None, the shape's default capability
    # won unopposed, and the user who asked for a funnel got a line chart
    # with no explanation — the silent substitution the whole reporting path
    # exists to prevent. Recorded here, the request is visible to
    # orchestrator.py's substitution check, which then says plainly that the
    # chart is not available for this data.
    #
    # Adding a capability for any of these later needs nothing changed here;
    # the entry simply starts matching a real route instead of reporting a
    # gap. Each needs a data shape the pipeline does not yet produce — flows
    # between accounts, stage counts, an actual-versus-target pair — so the
    # honest answer today is that they cannot be drawn.
    # "flow diagram" deliberately excluded: _EXPLICIT_FLOW_HINTS already owns
    # it for PROCESS_FLOW, and claiming it here would turn a drawable
    # flowchart request into a refusal.
    ("SANKEY_CHART", re.compile(rf"\bsankey{_KIND}?\b", re.I)),
    ("FUNNEL_CHART", re.compile(rf"\bfunnel{_KIND}?\b", re.I)),
    ("GAUGE_CHART", re.compile(rf"\b(?:gauge{_KIND}?|speedometer{_KIND}?)\b", re.I)),
    ("BULLET_CHART", re.compile(rf"\bbullet\s*(?:chart|graph|plot)\b", re.I)),
    ("SUNBURST_CHART", re.compile(rf"\bsunburst{_KIND}?\b", re.I)),
    ("CALENDAR_HEATMAP", re.compile(r"\bcalendar\s*(?:heat\s*map|plot|chart|view)\b", re.I)),
    ("GANTT_CHART", re.compile(rf"\bgantt{_KIND}?\b", re.I)),
    ("BUBBLE_CHART", re.compile(rf"\bbubble{_KIND}?\b", re.I)),
    ("VIOLIN_PLOT", re.compile(rf"\bviolin{_KIND}?\b", re.I)),
    ("PARETO_CHART", re.compile(rf"\bpareto{_KIND}?\b", re.I)),
    ("CHORD_DIAGRAM", re.compile(r"\bchord\s*diagram\b", re.I)),
    ("PARALLEL_COORDINATES", re.compile(r"\bparallel\s*coordinates?\b", re.I)),
    ("STREAMGRAPH", re.compile(r"\b(?:streamgraph|stream\s+graph|themeriver)\b", re.I)),
    ("SLOPE_CHART", re.compile(rf"\bslope{_KIND}?\b", re.I)),
    ("BUMP_CHART", re.compile(rf"\bbump{_KIND}?\b", re.I)),
    ("DUMBBELL_CHART", re.compile(rf"\bdumbbell{_KIND}?\b", re.I)),
    ("TORNADO_CHART", re.compile(rf"\btornado{_KIND}?\b", re.I)),
    ("WORD_CLOUD", re.compile(r"\bword\s*cloud\b", re.I)),
    # Bare "heat map" stays with _EXPLICIT_HEATMAP_HINTS, which routes a real,
    # drawable adjacency heatmap; only the map-shaped spellings land here.
    ("CHOROPLETH_MAP", re.compile(r"\b(?:choropleth|world\s+map|map\s+chart)\b", re.I)),
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

    # Gated on the shape alone once a chart was explicitly asked for. The
    # shape only exists when something already built real slices, and
    # requiring COMPOSITION intent on top of that dropped the document case:
    # "show the assets in this document as a pie chart" classifies as FACT, so
    # the slices were built, the shape was right, and no plan asked for a
    # visual — leaving a bar chart of the underlying rows and no explanation.
    if data_shape == PART_TO_WHOLE and (intent == COMPOSITION or explicit):
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

    # A figure with a stated target always wants the visual: the comparison is
    # the entire content of the question, and it reads far better as a dial
    # than as a sentence. No intent gate — "revenue 8.2m against a target of
    # 10m" classifies as FACT, which none of the branches above admit, so
    # requiring a visual intent here would leave the shape permanently
    # unreachable despite the evidence being complete.
    if data_shape == SCALAR_TARGET:
        return _make_plan(query,
            intent=intent, response_mode=TEXT_KPI, visual_required=True,
            visual_family=STATISTICAL, explicit_visual_request=explicit,
            confidence=0.9,
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
