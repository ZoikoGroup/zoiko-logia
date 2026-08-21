"""
Deterministic intent classification for Ask Kriton's visualization pipeline.

Scope note: this implements the subset of the full intent taxonomy that the
current evidence sources can actually back with real data —
  - TREND, DISTRIBUTION, CURRENT_METRIC, PRECISE_DATA — dbnomics.py (time
    series) / frankfurter.py (a single FX rate). DISTRIBUTION reinterprets
    the SAME real DBnomics values as a value distribution (histogram)
    instead of a trend line — not a new data source, just a second honest
    way to look at data already fetched (see rules.py's HISTOGRAM rule).
  - PROCESS — a directed-stages chain the user supplies explicitly in their
    own query text (extraction.py), since Mermaid/LLM-authored diagrams were
    removed.
  - RELATIONSHIP / NETWORK / EVIDENCE_ANALYSIS / DEPENDENCY / LINEAGE — an
    entity/relationship graph the user supplies explicitly in their own
    query text (extraction.py) — there is still no independent entity-
    extraction pipeline over arbitrary retrieved text, so these only resolve
    when the user states the structure themselves (e.g. "A owns B; B
    invoices C" or "A -> B -> C"). Matches the spec's own example: "visualize
    every SUPPLIED entity and relationship."
  - CORRELATION — two real, independently-fetched, period-aligned series
    (dbnomics.py's _find_two_series) → SCATTER.
  - COMPOSITION — real, named UK shareholders and their declared ownership
    BAND (market_data.py's _find_ownership, Companies House persons-with-
    significant-control) → DONUT. Deliberately narrower than RELATIONSHIP's
    "ownership structure" phrasing (a user-SUPPLIED entity graph) — this is
    a real company's actual filed shareholding, fetched, never supplied by
    the user in their own query text.
  - FACT/DEFINITION/EXPLANATION (default) — no visual-worthy evidence.

COMPARISON/HIERARCHY are still NOT implemented — no categorical data source
exists in this codebase to back them with real (non-fabricated) evidence.
Keyword-only classification for those would just guess at a chart the
evidence can't actually support, which is the failure mode ZL-T0-04
(data-honesty) exists to prevent. Add them once a real data source exists.
"""
from __future__ import annotations

import re

from app.orchestration.dbnomics import _STAT_HINTS
from app.orchestration.market_data import _OWNERSHIP_HINTS

TREND = "TREND"
DISTRIBUTION = "DISTRIBUTION"
CORRELATION = "CORRELATION"
COMPOSITION = "COMPOSITION"
CURRENT_METRIC = "CURRENT_METRIC"
PRECISE_DATA = "PRECISE_DATA"
PROCESS = "PROCESS"
EVIDENCE_ANALYSIS = "EVIDENCE_ANALYSIS"
RELATIONSHIP = "RELATIONSHIP"
NETWORK = "NETWORK"
DEPENDENCY = "DEPENDENCY"
LINEAGE = "LINEAGE"
FACT = "FACT"

# Any of these count as "graph-shaped intent" for data_shape.py / rules.py's
# evidence-graph rule (spec §8).
GRAPH_INTENTS = frozenset({EVIDENCE_ANALYSIS, RELATIONSHIP, NETWORK, DEPENDENCY, LINEAGE})

_PROCESS_HINTS = re.compile(
    r"\b(process|workflow|procedure|steps? (to|for|in)|approval flow|"
    r"flowchart|interactive flow|interactive diagram|"
    r"explain (the|how) .*(process|workflow|procedure)|how does .* work)\b",
    re.I,
)

_EVIDENCE_ANALYSIS_HINTS = re.compile(
    r"\b(evidence graph|evidence network|evidence trail|audit evidence|"
    r"supplied entit(y|ies)|every (entity|entities) and relationship)\b",
    re.I,
)

_RELATIONSHIP_HINTS = re.compile(
    r"\b(relationship between|how (are|is) .* (connected|related)|"
    r"connection between|how .* relate|ownership structure|"
    # An explicit request to render AS a graph-shaped format (heatmap/graph/
    # network/matrix) is itself relationship-shaped intent, independent of
    # whether the query also uses "connected"/"related" wording — e.g. "show
    # this as a heatmap: Acme Corp owns Beta Ltd" has no "connected" phrase
    # but is still asking to visualize a relationship structure. Matched both
    # with and without a leading "as a" (response_planner.py's own explicit-
    # heatmap-request regex matches bare "matrix view" too — this must stay
    # in sync with that, or the intent gate blocks a request the planner
    # already recognises as an explicit heatmap ask).
    r"show (this|it) as an? (heatmap|heat ?map|graph|network|matrix)|"
    r"as an? (heatmap|heat ?map|matrix)|matrix view|matrix of)\b",
    re.I,
)

# "relationship between" alone (not the wider _RELATIONSHIP_HINTS set) is
# ambiguous between an entity-graph request and a statistical-correlation
# request — see classify_intent()'s disambiguation using this.
_RELATIONSHIP_BETWEEN_HINT = re.compile(r"\brelationship between\b", re.I)

_NETWORK_HINTS = re.compile(r"\b(network (of|diagram|graph)|ownership network|ownership chain)\b", re.I)

_DEPENDENCY_HINTS = re.compile(r"\b(depends? on|dependenc(y|ies)|dependency map)\b", re.I)

_LINEAGE_HINTS = re.compile(r"\b(data lineage|lineage of|audit trail of)\b", re.I)

_DISTRIBUTION_HINTS = re.compile(
    r"\b(distribution of|spread of|spread out|histogram|frequency of|how (are|is) .* distributed)\b",
    re.I,
)

_COMPOSITION_VISUAL_HINTS = re.compile(
    r"\b(donut chart|doughnut chart|ring chart|pie chart)\b", re.I,
)

# Deliberately narrower than _RELATIONSHIP_HINTS's "relationship between" —
# "correlat*" wording only, so a statistical-correlation question (two real
# numeric series) and an entity-relationship-graph question never collide on
# the same phrasing. Must stay in sync with dbnomics.py's
# _CORRELATION_SPLIT_PATTERNS, which extracts the two named subjects.
_CORRELATION_HINTS = re.compile(
    r"\b(correlation between|correlated with|correlation of|correlate .+ with)\b", re.I,
)

_TREND_HINTS = re.compile(
    r"\b(trend|over time|over the (last|past)|history|historical|"
    r"last \d+ (years?|quarters?|months?)|since \d{4}|growth (rate|over)|"
    r"track(ed)? over|movement of|change over|"
    # A request for any of the pipeline's supported chart renderings over a
    # named subject implies "plot this measure over its dimension" — the
    # only real chart-worthy reading of a bare subject name is a trend view.
    # Must stay in sync with response_planner.py's _CHART_VARIANTS regexes.
    r"bar chart|column chart|step line|stepped line|spline line|smoothed? line|"
    r"area chart|filled line|line with markers?|marked line|line chart)\b",
    re.I,
)

_CURRENT_METRIC_HINTS = re.compile(
    r"\b(current|latest|today'?s|right now|as of (now|today)|what is the (rate|value|figure))\b",
    re.I,
)

_PRECISE_DATA_HINTS = re.compile(
    r"\b(exact|precise|exactly|exact figure|exact value|convert|conversion)\b",
    re.I,
)


def classify_intent(query: str) -> str:
    """Deterministic, regex-based — no LLM/ML call, so it's fast, free, and
    always reproducible for the same input (a hard requirement for the
    regression suite in test_visualization_pipeline.py).

    Graph-shaped intents are checked before PROCESS: a query can contain both
    "process"-adjacent language and an explicit relationship structure (e.g.
    "map the dependency network for this process"), and the graph reading is
    the more specific/informative one when both are present.
    """
    q = query or ""
    if _EVIDENCE_ANALYSIS_HINTS.search(q):
        return EVIDENCE_ANALYSIS
    if _COMPOSITION_VISUAL_HINTS.search(q):
        return COMPOSITION
    # Checked early and narrowly (shareholders/PSC/cap table/"who owns" —
    # never RELATIONSHIP's "ownership structure") so a real shareholding
    # lookup is never shadowed by, or mistaken for, a user-supplied entity
    # graph request.
    if _OWNERSHIP_HINTS.search(q):
        return COMPOSITION
    # "relationship between X and Y" is ambiguous between an entity-graph
    # request and a statistical-correlation request. When X/Y look like real
    # economic statistics (the same keywords dbnomics.py itself gates real
    # series lookups on), prefer the reading that can actually be backed by
    # real paired data — checked before the wider _RELATIONSHIP_HINTS so
    # this narrower, more specific case wins.
    if _RELATIONSHIP_BETWEEN_HINT.search(q) and _STAT_HINTS.search(q):
        return CORRELATION
    if _RELATIONSHIP_HINTS.search(q):
        return RELATIONSHIP
    if _NETWORK_HINTS.search(q):
        return NETWORK
    if _DEPENDENCY_HINTS.search(q):
        return DEPENDENCY
    if _LINEAGE_HINTS.search(q):
        return LINEAGE
    if _PROCESS_HINTS.search(q):
        return PROCESS
    if _CORRELATION_HINTS.search(q):
        return CORRELATION
    if _DISTRIBUTION_HINTS.search(q):
        return DISTRIBUTION
    # Checked before _TREND_HINTS: an explicit "exact"/"precise"/"convert"
    # ask is a deliberate, narrow signal that should win even when the SAME
    # query also carries an incidental time-range phrase _TREND_HINTS would
    # otherwise match first — e.g. "the exact figures for the last 8
    # quarters" is a PRECISE_DATA request that happens to name a time span,
    # not a trend-chart request. Same precedence rationale as CORRELATION
    # being checked before the wider RELATIONSHIP above.
    if _PRECISE_DATA_HINTS.search(q):
        return PRECISE_DATA
    if _TREND_HINTS.search(q):
        return TREND
    if _CURRENT_METRIC_HINTS.search(q):
        return CURRENT_METRIC
    return FACT
