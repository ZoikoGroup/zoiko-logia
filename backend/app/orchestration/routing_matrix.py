"""
Deterministic routing policy matrix — ZL-ENG-02 §8.

This is the SINGLE SOURCE OF TRUTH for route selection.
Each risk_level + confidence_state combination maps to exactly one route.
classifier_version and policy_version are recorded in every route_selected audit event.

Routing Rules (§8.1):
  - Model gateway executes ONLY when route == LLM.
  - Clarification is bounded to 2 cycles per query_id; the 3rd escalates to HUMAN_REVIEW.
  - HUMAN_REVIEW creates a persisted review_case object.
  - SECURITY_INCIDENT creates a persisted incident object.
  - REFUSAL returns a safe message and records refusal_returned.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CLASSIFIER_VERSION = "rc_1.0"
POLICY_VERSION = "pm_1.0"

# Route constants
ROUTE_LLM = "LLM"
ROUTE_REFUSAL = "REFUSAL"
ROUTE_CLARIFICATION = "CLARIFICATION"
ROUTE_HUMAN_REVIEW = "HUMAN_REVIEW"
ROUTE_SECURITY_INCIDENT = "SECURITY_INCIDENT"
ROUTE_REJECTED = "REJECTED"

# Confidence state constants — §7.2
CONF_SUFFICIENT = "sufficient"
CONF_LIMITED = "limited"
CONF_INSUFFICIENT = "insufficient"
CONF_CONFLICTING = "conflicting_sources"
CONF_STALE = "stale_sources"
CONF_RESTRICTED = "restricted_sources"

# Risk level constants
RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_RESTRICTED = "RESTRICTED"

MAX_CLARIFICATION_CYCLES = 2  # §8.1 — 3rd unresolved cycle escalates to HUMAN_REVIEW


# ── Policy Matrix — §8 ────────────────────────────────────────────────────────
# (risk_level, confidence_state) → route
_MATRIX: dict[tuple[str, str], str] = {
    # LOW risk
    (RISK_LOW, CONF_SUFFICIENT):    ROUTE_LLM,
    (RISK_LOW, CONF_LIMITED):       ROUTE_LLM,            # with mandatory caveats
    (RISK_LOW, CONF_INSUFFICIENT):  ROUTE_CLARIFICATION,

    # MEDIUM risk
    (RISK_MEDIUM, CONF_SUFFICIENT):    ROUTE_LLM,          # disclaimer_required = True
    (RISK_MEDIUM, CONF_LIMITED):       ROUTE_HUMAN_REVIEW,
    (RISK_MEDIUM, CONF_INSUFFICIENT):  ROUTE_HUMAN_REVIEW,

    # HIGH risk — any confidence → HUMAN_REVIEW
    (RISK_HIGH, CONF_SUFFICIENT):    ROUTE_HUMAN_REVIEW,
    (RISK_HIGH, CONF_LIMITED):       ROUTE_HUMAN_REVIEW,
    (RISK_HIGH, CONF_INSUFFICIENT):  ROUTE_HUMAN_REVIEW,
    (RISK_HIGH, CONF_CONFLICTING):   ROUTE_HUMAN_REVIEW,
    (RISK_HIGH, CONF_STALE):         ROUTE_HUMAN_REVIEW,
    (RISK_HIGH, CONF_RESTRICTED):    ROUTE_REFUSAL,

    # RESTRICTED — any confidence → REFUSAL
    (RISK_RESTRICTED, CONF_SUFFICIENT):    ROUTE_REFUSAL,
    (RISK_RESTRICTED, CONF_LIMITED):       ROUTE_REFUSAL,
    (RISK_RESTRICTED, CONF_INSUFFICIENT):  ROUTE_REFUSAL,
    (RISK_RESTRICTED, CONF_CONFLICTING):   ROUTE_REFUSAL,
    (RISK_RESTRICTED, CONF_STALE):         ROUTE_REFUSAL,
    (RISK_RESTRICTED, CONF_RESTRICTED):    ROUTE_REFUSAL,

    # Cross-cutting confidence states (any risk)
    ("ANY", CONF_CONFLICTING):   ROUTE_HUMAN_REVIEW,
    ("ANY", CONF_STALE):         ROUTE_CLARIFICATION,
    ("ANY", CONF_RESTRICTED):    ROUTE_REFUSAL,
}


@dataclass
class RouteDecision:
    route: str
    classifier_version: str = CLASSIFIER_VERSION
    policy_version: str = POLICY_VERSION
    disclaimer_required: bool = False
    clarification_message: Optional[str] = None


def resolve_route(
    risk_level: str,
    confidence_state: str,
    clarification_cycle: int = 0,
) -> RouteDecision:
    """
    Resolve the deterministic route for a given risk_level + confidence_state.
    Escalates CLARIFICATION to HUMAN_REVIEW after MAX_CLARIFICATION_CYCLES per §8.1.
    """
    # RESTRICTED risk always maps to REFUSAL — no cross-cutting override (§8)
    if risk_level == RISK_RESTRICTED:
        return RouteDecision(route=ROUTE_REFUSAL)

    # Cross-cutting confidence overrides (any non-RESTRICTED risk)
    if confidence_state == CONF_CONFLICTING:
        return RouteDecision(route=ROUTE_HUMAN_REVIEW)
    if confidence_state == CONF_RESTRICTED:
        return RouteDecision(route=ROUTE_REFUSAL)
    if confidence_state == CONF_STALE:
        return RouteDecision(route=ROUTE_CLARIFICATION)

    route = _MATRIX.get((risk_level, confidence_state))

    # Fallback: if risk is HIGH and confidence unknown, be conservative
    if route is None:
        route = ROUTE_HUMAN_REVIEW if risk_level == RISK_HIGH else ROUTE_CLARIFICATION

    # §8.1 — Clarification cycle escalation
    if route == ROUTE_CLARIFICATION and clarification_cycle >= MAX_CLARIFICATION_CYCLES:
        route = ROUTE_HUMAN_REVIEW

    disclaimer_required = (
        risk_level == RISK_MEDIUM
        or confidence_state == CONF_LIMITED
    )

    clarification_message: Optional[str] = None
    if route == ROUTE_CLARIFICATION:
        clarification_message = _clarification_for(confidence_state, risk_level)

    return RouteDecision(
        route=route,
        disclaimer_required=disclaimer_required,
        clarification_message=clarification_message,
    )



def _clarification_for(confidence_state: str, risk_level: str) -> str:
    if confidence_state == CONF_INSUFFICIENT:
        return (
            "To find the most relevant sources, could you clarify: "
            "Does this question relate to a specific jurisdiction (e.g., UK GAAP, IFRS, US GAAP), "
            "reporting framework, or entity type?"
        )
    if confidence_state == CONF_STALE:
        return (
            "The sources available for this topic may not reflect the most current standards. "
            "Could you confirm whether you need the latest effective guidance, "
            "or are you researching historical treatment?"
        )
    return (
        "Could you provide more context about your specific situation, jurisdiction, "
        "or the reporting framework you are working under?"
    )


def map_safety_confidence(safety_confidence: Optional[str]) -> str:
    """
    Map legacy safety_confidence strings (HIGH_CONFIDENCE, LOW_CONFIDENCE, NO_ELIGIBLE_SOURCE)
    to the §7.2 canonical confidence states.
    """
    mapping = {
        "HIGH_CONFIDENCE": CONF_SUFFICIENT,
        "SUFFICIENT": CONF_SUFFICIENT,
        "LOW_CONFIDENCE": CONF_LIMITED,
        "NO_ELIGIBLE_SOURCE": CONF_INSUFFICIENT,
        "CONFLICT_UNRESOLVED": CONF_CONFLICTING,
        "STALE": CONF_STALE,
        "RESTRICTED": CONF_RESTRICTED,
    }
    return mapping.get(safety_confidence or "", CONF_SUFFICIENT)
