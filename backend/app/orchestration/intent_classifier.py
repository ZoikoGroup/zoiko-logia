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
from app.orchestration.market_data import _OWNERSHIP_HINTS, _OWNERSHIP_STRUCTURE_CHART_HINT
from app.orchestration.number_words import SPELLED_NUMBER_PATTERN

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
    r"flowchart|flow diagram|interactive flow|interactive diagram|"
    r"process flow|process diagram|mermaid (?:flowchart|flow|diagram)|x6 (?:workflow|flow|diagram)|"
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
    # with and without a leading "as a"/"of" — response_planner.py's own
    # explicit-heatmap-request regex (_EXPLICIT_HEATMAP_HINTS) matches bare
    # "heatmap"/"heat map" anywhere in the query with no "as a"/"of" needed;
    # this must stay in sync with that or the intent gate blocks a request
    # the planner already recognises as an explicit heatmap ask (e.g. "Show a
    # heatmap of: A pays B" has no "as a"/"of a" heatmap phrase, only "of:").
    r"show (this|it|this relationship) as an? (heatmap|heat ?map|graph|network|matrix)|"
    r"heatmap|heat ?map|as an? matrix|matrix view|matrix of|adjacency matrix|"
    r"(?:show|create|draw|render) (?:this |an? )?(?:relationship )?graph|"
    r"(?:g6|cytoscape)(?:\.js)? (?:evidence |relationship )?(?:graph|network)|"
    r"use (?:g6|cytoscape)(?:\.js)? to (?:show|visuali[sz]e))\b",
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

# Deliberately narrower than _RELATIONSHIP_HINTS's "relationship between" —
# "correlat*" wording only, so a statistical-correlation question (two real
# numeric series) and an entity-relationship-graph question never collide on
# the same phrasing. Must stay in sync with dbnomics.py's
# _CORRELATION_SPLIT_PATTERNS, which extracts the two named subjects.
_CORRELATION_HINTS = re.compile(
    r"\b(correlation between|correlated with|correlation of|correlate .+ with|"
    r"scatter plot with (a )?trend line|scatter plot (comparing|of) .+ and .+|"
    r"scatter (plot|chart|graph) (for|of) .+ vs\.? .+|"
    r"scatter trend|regression plot|correlation plot|"
    r"compare .+ (and|vs\.?|versus) .+ (using|as|with|in) (an? )?(grouped|stacked|100% stacked|scatter))\b", re.I,
)

_TREND_HINTS = re.compile(
    r"\b(trend|over time|over the (last|past)|history|historical|"
    # \d+ OR a spelled-out number ("the last ten years") — see
    # number_words.py's docstring for why this needed a shared fix.
    rf"last (?:\d+|{SPELLED_NUMBER_PATTERN}) (years?|quarters?|months?)|since \d{{4}}|growth (rate|over)|"
    r"track(ed)? over|movement of|change over|"
    # A request for any of the pipeline's supported chart renderings over a
    # named subject implies "plot this measure over its dimension" — the
    # only real chart-worthy reading of a bare subject name is a trend view.
    # Must stay in sync with response_planner.py's _CHART_VARIANTS regexes.
    r"bar chart|column chart|vertical bar|horizontal bar|grouped bar|clustered bar|"
    r"stacked bar|stacked horizontal bar|diverging bar|waterfall chart|plain line|"
    r"dashed line|dotted line|dash[ -]?dot line|"
    r"step[ -]?line|stepped[ -]?line|spline|smooth spline|smooth(?:ed)? line|area chart|filled line|filled area|"
    r"area (chart )?with markers?|area \+ markers?|value[ -]?labell?ed line|"
    r"line with value labels?|line with markers?|marked line|line chart)\b",
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

# Catch-all for an explicit "draw/visualize this" ask that names no more
# specific graph-shaped phrasing (e.g. "Visualize: A owns B" — a real,
# parseable relation clause per extraction.py, but neither "relationship
# between" nor "ownership structure" nor any other _RELATIONSHIP_HINTS
# phrase appears). Checked LAST, only once every narrower/more specific
# hint above (TREND, CORRELATION, COMPOSITION, DISTRIBUTION, etc.) has
# already had first refusal — so "visualize Apple's stock trend" still
# resolves via _TREND_HINTS, never here. Resolving to RELATIONSHIP is
# arbitrary among GRAPH_INTENTS (all map to the same NODES_EDGES shape in
# data_shape.py) — this only ever matters paired with real extracted
# structure; service.py still discards it when extract_graph() finds
# nothing to draw.
_EXPLICIT_DIAGRAM_HINTS = re.compile(
    r"\b(visuali[sz]e|visuali[sz]ation of|diagram (of|for)|graph (of|for)|"
    r"draw (a |the )?(diagram|graph)|map (out|this))\b",
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
    # Checked early and narrowly (shareholders/PSC/cap table/"who owns" —
    # never RELATIONSHIP's "ownership structure") so a real shareholding
    # lookup is never shadowed by, or mistaken for, a user-supplied entity
    # graph request. The second condition is a narrow exception: "ownership
    # structure" co-occurring with an explicit pie/donut-chart request is
    # unambiguous — the user is asking for this company's real, fetched
    # shareholding, not a graph they're about to supply themselves. See
    # _OWNERSHIP_STRUCTURE_CHART_HINT's own docstring in market_data.py.
    if _OWNERSHIP_HINTS.search(q) or _OWNERSHIP_STRUCTURE_CHART_HINT.search(q):
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
    if _EXPLICIT_DIAGRAM_HINTS.search(q):
        return RELATIONSHIP
    return FACT
