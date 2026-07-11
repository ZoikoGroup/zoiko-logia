"""
Massarius™ retrieval and evidence subsystem — deterministic routing
(ZL-ENG-02 §6, ZL-ENG-03 §5.6).

This module does NOT reimplement the (risk_level, confidence_state) -> route
matrix — that lives in app/orchestration/routing_matrix.py and is a genuinely
solid, deterministic, versioned implementation already. What this module adds
is the fuller signature ZL-ENG-03 §5.6 specifies (jurisdiction, framework,
tenant_policy alongside SourceBundle.confidence_state), so callers has one
function to call regardless of whether a future policy rule actually varies
by jurisdiction/framework/tenant — today none does, but the signature is
stable so adding one later doesn't require a call-site change everywhere.

Must NOT: classify risk (risk_safety.py's job), build or read raw source
content (bundle_builder.py's job), or decide licence eligibility
(license_gate.py's job). Purely a function of already-decided inputs -> route.
"""
from __future__ import annotations

from typing import Optional

from app.orchestration.routing_matrix import (
    CLASSIFIER_VERSION,
    POLICY_VERSION,
    RouteDecision,
    resolve_route,
)

__all__ = ["CLASSIFIER_VERSION", "POLICY_VERSION", "RouteDecision", "resolve_policy"]


def resolve_policy(
    *,
    confidence_state: str,
    risk_level: str,
    jurisdiction: str = "",
    framework: str = "",
    tenant_policy: Optional[dict] = None,
    clarification_cycle: int = 0,
) -> RouteDecision:
    """
    Resolve the route for a query given SourceBundle.confidence_state plus
    risk_level, jurisdiction, framework, and tenant policy overrides.

    Takes confidence_state as a plain string rather than the SourceBundle
    itself deliberately — retrieval can fail entirely (no bundle at all),
    in which case the caller still needs to resolve a route from a fallback
    confidence_state (e.g. "insufficient"). Requiring a live SourceBundle
    here would make that case impossible to express.

    Pure function — no hidden state, no randomness, same inputs always
    produce the same RouteDecision. Callable both at initial classification
    (right after bundle_builder.py produces the SourceBundle) and again at
    re-evaluation, if a later step (e.g. answer_validator.py's Checkpoint C)
    determines the bundle's confidence should be downgraded before a final
    route is committed to — same function, same determinism guarantee either
    time, just called with an updated confidence_state.

    jurisdiction/framework/tenant_policy are accepted per ZL-ENG-03 §5.6's
    signature but don't currently change the outcome — no policy rule keys
    on them yet. They're real parameters, not placeholders, so a future rule
    that does vary by jurisdiction/framework/tenant doesn't require touching
    every call site again.
    """
    del jurisdiction, framework, tenant_policy  # accepted, not yet policy-relevant — see docstring

    return resolve_route(
        risk_level=risk_level,
        confidence_state=confidence_state,
        clarification_cycle=clarification_cycle,
    )
