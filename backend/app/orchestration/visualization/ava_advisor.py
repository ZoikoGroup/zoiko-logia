"""
Statistical chart-type disambiguation — the role AVA (AntV's chart-advisor
library) plays in the design spec: "which statistical visualization best
represents this data?"

This is NOT a call into the real @antv/ava npm package. That library is
JavaScript-only; this backend is 100% Python, and there is no Python port.
Actually embedding it would mean running a separate Node.js microservice the
Python backend calls over HTTP — a second runtime to build, deploy and
monitor, for a recommendation this small amount of chart-type ambiguity
doesn't yet justify. Instead, this module implements AVA's specific
STATISTICAL-family purpose natively: given a data shape, contribute an
additional scored candidate alongside the deterministic rules in rules.py.
If a real cross-language AVA integration is wanted later, this module is the
one place that decision plugs into — rules.py and orchestrator.py don't need
to change.

Scope: the only ambiguity that exists today is TIME_SERIES with few enough
points that a bar-per-period comparison reads at least as well as a trend
line (a short series is often more "compare these few values" than "watch
a trend unfold"). Longer series stay LINE-only — AVA does not override that,
matching the spec's "AVA does not override high-confidence correctness
rules" (spec §29 DoD #4).
"""
from __future__ import annotations

from app.orchestration.data_shape import TIME_SERIES

# A short series (few periods) is ambiguous between LINE and BAR; a longer
# one reads unambiguously as a trend, so AVA contributes nothing past this.
_BAR_AMBIGUITY_MAX_POINTS = 5


def recommend(data_shape: str, observation_count: int) -> tuple[str, float] | None:
    """Returns (visualization_type, score) for AVA's one supported
    disambiguation, or None when there's no ambiguity to resolve."""
    if data_shape == TIME_SERIES and observation_count <= _BAR_AMBIGUITY_MAX_POINTS:
        return ("BAR", 0.55)
    return None
