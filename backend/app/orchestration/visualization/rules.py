"""
Deterministic visualization-candidate scoring (spec §8/§9).

Combines: plain deterministic rules over data_shape/intent/evidence, PLUS
ava_advisor.py's statistical disambiguation signal (the spec's "AVA
recommendation" term) for the one case that's genuinely ambiguous today
(short time series: LINE vs BAR). There is still no LLM-fallback term — see
orchestrator.py's module docstring for why nothing here needs one yet.
"""
from __future__ import annotations

from app.orchestration.data_shape import DIRECTED_STAGES, NODES_EDGES, PART_TO_WHOLE, SCALAR, TIME_SERIES, XY_NUMERIC
from app.orchestration.intent_classifier import COMPOSITION, CORRELATION, DISTRIBUTION, PRECISE_DATA
from app.orchestration.visualization import ava_advisor

_MIN_LINE_POINTS = 3
_MIN_HISTOGRAM_POINTS = 8
_MIN_BOX_POINTS = 4
_MIN_TABLE_POINTS = 2
_MIN_DONUT_SLICES = 2


def score_candidates(
    data_shape: str,
    observation_count: int,
    explicit_visual_request: bool,
    entity_count: int = 0,
    edge_count: int = 0,
    intent: str | None = None,
    explicit_heatmap_request: bool = False,
    explicit_box_request: bool = False,
    composition_count: int = 0,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}

    def add_score(viz_type: str, s: float) -> None:
        scores[viz_type] = max(scores.get(viz_type, 0.0), s)

    if data_shape == TIME_SERIES and observation_count >= _MIN_LINE_POINTS:
        add_score("LINE", 0.70)
        # BAR is only ever reachable via the router's "bar_chart" capability,
        # which itself requires an explicit "bar chart"/"column chart"
        # request (router.py's requested_variant="BAR_CHART" gate) — so an
        # unconditional score here is safe: this line is never consulted for
        # a plain, un-requested time series the way LINE's score is.
        add_score("BAR", 0.70)

    # PRECISE_DATA intent ("give me the exact figures/transactions") wants
    # every real value laid out, not summarized into a trend line — scored
    # above LINE so it wins when the user explicitly asked for exactness.
    if data_shape == TIME_SERIES and intent == PRECISE_DATA and observation_count >= _MIN_TABLE_POINTS:
        add_score("TABLE", 0.90)

    # DISTRIBUTION intent reinterprets the SAME real values as a histogram
    # instead of a trend — scored above LINE so it wins when explicitly
    # asked for, but only with enough points for meaningful binning.
    if data_shape == TIME_SERIES and intent == DISTRIBUTION and observation_count >= _MIN_HISTOGRAM_POINTS:
        add_score("HISTOGRAM", 0.85)

    # BOX (quartile summary of the SAME real values HISTOGRAM bins) only
    # wins when explicitly requested — a box plot is a much less familiar
    # default than a histogram for the same distribution question.
    if data_shape == TIME_SERIES and explicit_box_request and observation_count >= _MIN_BOX_POINTS:
        add_score("BOX", 0.95)

    # SCATTER is only ever reachable via the router's "correlation_scatter"
    # capability, which itself requires CORRELATION intent + XY_NUMERIC shape
    # (two real, independently-fetched series — see dbnomics.py's
    # _find_two_series) — an unconditional score here is safe on the same
    # basis as BAR's above.
    if data_shape == XY_NUMERIC and intent == CORRELATION and observation_count >= 3:
        add_score("SCATTER", 0.90)

    if data_shape == SCALAR:
        add_score("KPI", 0.75)

    # DONUT is only ever reachable via COMPOSITION intent + PART_TO_WHOLE
    # shape (real, named PSC shareholders — market_data.py's _find_ownership)
    # — an unconditional score here is safe on the same basis as SCATTER's
    # above: neither can occur for a query that isn't already that shape.
    if data_shape == PART_TO_WHOLE and intent == COMPOSITION and composition_count >= _MIN_DONUT_SLICES:
        add_score("DONUT", 0.85)

    if data_shape == NODES_EDGES and entity_count >= 2 and edge_count >= 1:
        add_score("EVIDENCE_GRAPH", 0.95)
        # HEATMAP only offered when explicitly asked for — an adjacency
        # matrix is a much less readable default than a graph for the small
        # entity counts this pipeline actually produces, so it must outscore
        # EVIDENCE_GRAPH's high default rather than compete on equal footing.
        if explicit_heatmap_request:
            add_score("HEATMAP", 0.97)

    if data_shape == DIRECTED_STAGES and entity_count >= 2:
        add_score("PROCESS_FLOW", 0.90)

    # AVA's statistical disambiguation — a genuine second opinion, not a
    # decision override (spec §29 DoD #4: never beats a high-confidence rule).
    ava_pick = ava_advisor.recommend(data_shape, observation_count)
    if ava_pick:
        viz_type, score = ava_pick
        add_score(viz_type, score)

    # Explicit user request (spec §22) bumps the matching candidate — bounded,
    # never enough alone to promote a candidate the data shape can't support.
    if explicit_visual_request:
        for viz_type in ("LINE", "EVIDENCE_GRAPH", "PROCESS_FLOW"):
            if viz_type in scores:
                scores[viz_type] = min(1.0, scores[viz_type] + 0.05)

    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
