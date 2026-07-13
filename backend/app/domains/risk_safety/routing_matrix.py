"""
Versioned routing matrix — the single source of truth for what happens once
L2 semantic scoring has produced a risk_level and retrieval has produced a
source confidence_state. Every (risk_level, confidence_state) combination
must resolve to exactly one entry here; risk_classifier.classify() looks
this matrix up instead of branching inline, so classifier_version (the ML
model) and ROUTING_MATRIX_VERSION (this rulebook) can both be recorded on
every risk_classification_applied audit event.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domains.risk_safety.models import RiskLevel, Route

ROUTING_MATRIX_VERSION = "v1"


@dataclass(frozen=True)
class RouteRule:
    allowed: bool
    route: Route
    requires_sources: bool = False
    requires_citation: bool = False
    requires_professional_boundary: bool = False
    limitation: str | None = None


# Keyed by (risk_level, confidence_state). confidence_state comes from
# orchestration/retrieve.py's SourceBundle.confidence_state: HIGH_CONFIDENCE |
# LOW_CONFIDENCE | NO_ELIGIBLE_SOURCE. Any confidence_state not explicitly
# listed for a risk_level falls back to that risk_level's "default" entry
# (see _DEFAULTS below) — this is what HIGH_CONFIDENCE rows represent today.
ROUTING_MATRIX: dict[tuple[str, str], RouteRule] = {
    # LOW risk — always answerable regardless of source strength.
    (RiskLevel.LOW.value, "HIGH_CONFIDENCE"): RouteRule(True, Route.LLM),
    (RiskLevel.LOW.value, "LOW_CONFIDENCE"): RouteRule(True, Route.LLM),
    (RiskLevel.LOW.value, "NO_ELIGIBLE_SOURCE"): RouteRule(
        True, Route.CLARIFICATION, limitation="No source available."
    ),

    # MEDIUM risk — educational context, needs sources + boundary notice.
    (RiskLevel.MEDIUM.value, "HIGH_CONFIDENCE"): RouteRule(
        True, Route.LLM, requires_sources=True, requires_professional_boundary=True,
        limitation="Educational context — not specific professional advice.",
    ),
    (RiskLevel.MEDIUM.value, "LOW_CONFIDENCE"): RouteRule(
        True, Route.LLM, requires_sources=True, requires_professional_boundary=True,
        limitation="Educational context — not specific professional advice.",
    ),
    (RiskLevel.MEDIUM.value, "NO_ELIGIBLE_SOURCE"): RouteRule(
        True, Route.CLARIFICATION, limitation="No source available."
    ),

    # HIGH risk — the judgment-call tier. Needs strong sources; degrades to
    # human review the moment source quality can't back a HIGH-risk answer.
    (RiskLevel.HIGH.value, "HIGH_CONFIDENCE"): RouteRule(
        True, Route.LLM, requires_sources=True, requires_citation=True, requires_professional_boundary=True,
        limitation="Answer must include source citations and professional boundary notice.",
    ),
    (RiskLevel.HIGH.value, "LOW_CONFIDENCE"): RouteRule(
        False, Route.HUMAN_REVIEW, limitation="Low confidence source on high risk query."
    ),
    (RiskLevel.HIGH.value, "NO_ELIGIBLE_SOURCE"): RouteRule(
        False, Route.HUMAN_REVIEW, limitation="High risk requires source."
    ),
}

# Fallback used when a confidence_state value shows up that isn't one of the
# three known states above (e.g. a future value) — resolves to the same rule
# as that risk_level's HIGH_CONFIDENCE row rather than failing closed/open
# silently.
_DEFAULTS: dict[str, RouteRule] = {
    RiskLevel.LOW.value: ROUTING_MATRIX[(RiskLevel.LOW.value, "HIGH_CONFIDENCE")],
    RiskLevel.MEDIUM.value: ROUTING_MATRIX[(RiskLevel.MEDIUM.value, "HIGH_CONFIDENCE")],
    RiskLevel.HIGH.value: ROUTING_MATRIX[(RiskLevel.HIGH.value, "HIGH_CONFIDENCE")],
}


def resolve(risk_level: str, confidence_state: str) -> RouteRule:
    return ROUTING_MATRIX.get((risk_level, confidence_state)) or _DEFAULTS[risk_level]
