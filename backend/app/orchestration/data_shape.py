"""
Deterministic data-shape classification for Ask Kriton's visualization pipeline.

Kept separate from intent (per the design spec) — intent is about what the
user is asking for, data shape is about what the evidence actually looks
like. Only NONE / SCALAR / TIME_SERIES / NODES_EDGES / DIRECTED_STAGES /
XY_NUMERIC / PART_TO_WHOLE are implemented, matching what EvidenceModel can
actually contain today — CATEGORY_VALUE and the rest of the wider taxonomy
still aren't, because no data source produces those shapes in this codebase.

NODES_EDGES vs DIRECTED_STAGES: both are backed by the SAME
entities/relationships storage (see extraction.py) — which one applies is
decided by intent, not by the graph's own shape. A graph-shaped intent
(intent_classifier.GRAPH_INTENTS) reads it as a relationship graph; a
PROCESS intent reads the identical entities/relationships as an ordered
stage sequence. This mirrors how the same "A -> B -> C" text can mean either
depending on what the user actually asked for.
"""
from __future__ import annotations

from app.orchestration.evidence import EvidenceModel
from app.orchestration.intent_classifier import GRAPH_INTENTS, PROCESS, CORRELATION, COMPOSITION

NONE = "NONE"
SCALAR = "SCALAR"
TIME_SERIES = "TIME_SERIES"
NODES_EDGES = "NODES_EDGES"
DIRECTED_STAGES = "DIRECTED_STAGES"
XY_NUMERIC = "XY_NUMERIC"
PART_TO_WHOLE = "PART_TO_WHOLE"

# Below this many observations, a line chart is more noise than signal — a
# two-point "trend" line is just a single change, better said in text.
_MIN_TIME_SERIES_POINTS = 3

# Same minimum as a meaningful trend line — a 2-point "correlation" is just
# one pair of numbers, not a real statistical relationship.
_MIN_XY_POINTS = 3

# A donut with one slice is just a KPI wearing a costume — need at least two
# real holders (or a holder + the synthesized "Other" gap) for a composition
# to say anything a single figure couldn't.
_MIN_COMPOSITION_SLICES = 2


def classify_data_shape(evidence: EvidenceModel, intent: str | None = None) -> str:
    # Two real, independently-fetched, period-aligned series (dbnomics.py's
    # _find_two_series) — checked before the entities/relationships and
    # single-series branches below, since a correlation query also carries
    # >=3 primary observations that would otherwise be misread as TIME_SERIES.
    if (
        intent == CORRELATION
        and len(evidence.observations) >= _MIN_XY_POINTS
        and len(evidence.secondary_observations) == len(evidence.observations)
    ):
        return XY_NUMERIC

    # Real, named shareholders and their declared ownership band
    # (market_data.py's _find_ownership) — checked early for the same reason
    # as XY_NUMERIC above: composition evidence lives in its own field, never
    # mixed into `observations`, so this never collides with TIME_SERIES.
    if intent == COMPOSITION and len(evidence.composition) >= _MIN_COMPOSITION_SLICES:
        return PART_TO_WHOLE

    if evidence.entities and evidence.relationships:
        if intent == PROCESS:
            return DIRECTED_STAGES
        if intent in GRAPH_INTENTS:
            return NODES_EDGES
        # Entities/relationships were extracted but the intent doesn't ask to
        # see them as a graph or a flow — don't force one (spec §20/§21).

    n = len(evidence.observations)
    if n == 0:
        return NONE
    if n == 1:
        return SCALAR
    if n >= _MIN_TIME_SERIES_POINTS:
        return TIME_SERIES
    # 2 observations: not enough for a meaningful line, not a single figure
    # either — treat as SCALAR (report the latest value) rather than force a
    # chart that would just be a single line segment.
    return SCALAR
