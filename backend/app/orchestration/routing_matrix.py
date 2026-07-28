"""
Deterministic routing policy matrix — ZL-ENG-02 §8.

This is the SINGLE SOURCE OF TRUTH for route selection.
Each risk_level + confidence_state combination maps to exactly one route.
classifier_version and policy_version are recorded in every route_selected audit event.

Routing Rules (§8.1):
  - Model gateway executes ONLY when route == LLM.
  - Clarification is bounded to 2 cycles per query_id; the 3rd escalates to REFERRAL.
  - SECURITY_INCIDENT creates a persisted incident object.
  - REFUSAL returns a safe message and records refusal_returned.
  - REFERRAL returns a hedged/limited response naming the right kind of
    professional for the topic — no persisted review object, no human
    follow-up expected (analytics logging only). See the 2026-07-22 product
    vision doc (memory: product-vision-kriton-tutor-not-search, item 3):
    the earlier design routed every under-confident/advice-shaped HIGH-risk
    query to HUMAN_REVIEW, which doesn't scale as a manual queue. This
    matrix no longer resolves to HUMAN_REVIEW anywhere — ROUTE_HUMAN_REVIEW
    and the persisted-review-case machinery (orchestration/persisted_objects.py)
    still exist and still work, they're just not fed by this matrix
    anymore. If some other, non-routing-driven trigger for a manual review
    case is added later, that's a deliberate new decision, not a silent
    revival of this one.
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
ROUTE_HUMAN_REVIEW = "HUMAN_REVIEW"  # kept for persisted_objects.py/other callers — no longer resolved to by this matrix, see module docstring
ROUTE_REFERRAL = "REFERRAL"  # hedged/limited answer + disclaimer + named professional; no review case
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
RISK_ZERO = "ZERO"
RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_RESTRICTED = "RESTRICTED"

MAX_CLARIFICATION_CYCLES = 2  # §8.1 — 3rd unresolved cycle escalates to HUMAN_REVIEW


# ── Policy Matrix — §8 ────────────────────────────────────────────────────────
# (risk_level, confidence_state) → route
_MATRIX: dict[tuple[str, str], str] = {
    # ZERO risk — small talk / navigational, no substantive content. Same
    # permissive shape as LOW; it exists as its own tier so a lower bucket
    # than LOW is available for content with genuinely no advice/interpretive
    # weight, without changing LOW's own behavior.
    (RISK_ZERO, CONF_SUFFICIENT):    ROUTE_LLM,
    (RISK_ZERO, CONF_LIMITED):       ROUTE_LLM,
    (RISK_ZERO, CONF_INSUFFICIENT):  ROUTE_CLARIFICATION,

    # LOW risk
    (RISK_LOW, CONF_SUFFICIENT):    ROUTE_LLM,
    (RISK_LOW, CONF_LIMITED):       ROUTE_LLM,            # with mandatory caveats
    (RISK_LOW, CONF_INSUFFICIENT):  ROUTE_CLARIFICATION,

    # MEDIUM risk — auto-answer only when confidence is genuinely sufficient.
    # Anything weaker asks for clarification first rather than escalating
    # straight to a human — MAX_CLARIFICATION_CYCLES below still escalates
    # to HUMAN_REVIEW if two clarification rounds don't resolve it, so this
    # isn't a way to avoid human review forever, just to not spend a
    # reviewer's time on something a follow-up question could resolve.
    (RISK_MEDIUM, CONF_SUFFICIENT):    ROUTE_LLM,          # disclaimer_required = True
    (RISK_MEDIUM, CONF_LIMITED):       ROUTE_CLARIFICATION,
    (RISK_MEDIUM, CONF_INSUFFICIENT):  ROUTE_CLARIFICATION,

    # HIGH risk — the judgment-call tier.
    #
    # Real incident (2026-07-20): CONF_SUFFICIENT used to also map to
    # ROUTE_HUMAN_REVIEW unconditionally — every confidence state, meaning
    # the classifier's "accounting or audit opinion" / "regulated tax or
    # legal advice" labels (which cover most of what this product exists to
    # answer) could never get a direct answer at all, regardless of how
    # strong the retrieved sources were. Fixed to LLM below.
    #
    # 2026-07-22: the weaker confidence rows below used to degrade to
    # ROUTE_HUMAN_REVIEW too — per the product vision doc (item 3), a
    # manual review queue doesn't scale, so these now resolve to a real
    # (hedged, when there's something to hedge from) or referral response
    # instead, never a persisted review case. LIMITED still has real,
    # if weak, sources — attempt a hedged LLM answer (forced disclaimer +
    # professional referral, both enforced in orchestration/service.py).
    # INSUFFICIENT/CONFLICTING have nothing trustworthy to compose from at
    # all — REFERRAL skips composition entirely rather than attempting an
    # answer with no real grounding.
    (RISK_HIGH, CONF_SUFFICIENT):    ROUTE_LLM,
    (RISK_HIGH, CONF_LIMITED):       ROUTE_LLM,
    (RISK_HIGH, CONF_INSUFFICIENT):  ROUTE_REFERRAL,
    (RISK_HIGH, CONF_CONFLICTING):   ROUTE_REFERRAL,
    (RISK_HIGH, CONF_STALE):         ROUTE_CLARIFICATION,  # unreachable — the cross-cutting STALE check below always wins first; kept for table completeness
    (RISK_HIGH, CONF_RESTRICTED):    ROUTE_REFUSAL,

    # RESTRICTED — any confidence → REFUSAL
    (RISK_RESTRICTED, CONF_SUFFICIENT):    ROUTE_REFUSAL,
    (RISK_RESTRICTED, CONF_LIMITED):       ROUTE_REFUSAL,
    (RISK_RESTRICTED, CONF_INSUFFICIENT):  ROUTE_REFUSAL,
    (RISK_RESTRICTED, CONF_CONFLICTING):   ROUTE_REFUSAL,
    (RISK_RESTRICTED, CONF_STALE):         ROUTE_REFUSAL,
    (RISK_RESTRICTED, CONF_RESTRICTED):    ROUTE_REFUSAL,

    # Cross-cutting confidence states (any risk) — CONFLICTING no longer
    # escalates to a human queue (2026-07-22, see module docstring);
    # sources that genuinely disagree with each other means Kriton can't
    # confidently answer, which is exactly what REFERRAL is for.
    ("ANY", CONF_CONFLICTING):   ROUTE_REFERRAL,
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
    # True whenever the response must name a specific professional to
    # consult (REFERRAL route always; a hedged HIGH-risk LLM answer too) —
    # orchestration/service.py uses this to append
    # professional_referral.referral_message(category) to the response.
    professional_referral_required: bool = False


def resolve_route(
    risk_level: str,
    confidence_state: str,
    clarification_cycle: int = 0,
    advice_signal: bool = False,
) -> RouteDecision:
    """
    Resolve the deterministic route for a given risk_level + confidence_state.
    Escalates CLARIFICATION to HUMAN_REVIEW after MAX_CLARIFICATION_CYCLES per §8.1.

    advice_signal: True when the query names the reader's own situation
    ("my company", "should I file...") — app/domains/risk_safety/
    risk_classifier.py's has_advice_signal, surfaced on SafetyDecision.
    requires_human_review and threaded down through massarius/policy_matrix.py.
    A HIGH-risk query with this signal always gets a hedged answer with a
    forced professional referral, regardless of source strength — this is
    a content signal, not part of the confidence matrix, so it's checked
    as its own override rather than folded into risk_level or _MATRIX.
    """
    # RESTRICTED risk always maps to REFUSAL — no cross-cutting override (§8)
    if risk_level == RISK_RESTRICTED:
        return RouteDecision(route=ROUTE_REFUSAL)

    # Licence/access restriction always wins regardless of risk level or
    # advice signal — this is about what the source's licence permits
    # exposing, not how risky the question is, so it's checked before the
    # advice-signal override below.
    if confidence_state == CONF_RESTRICTED:
        return RouteDecision(route=ROUTE_REFUSAL)

    # A HIGH-risk query that also names the reader's own situation gets a
    # hedged answer (still LLM — the product vision's tax-investigation
    # example explicitly wants a general explanation, not a blank refusal)
    # with a forced disclaimer + professional referral, regardless of
    # source strength. Takes priority over the softer conflicting
    # cross-cutting outcome just below, same reasoning as before this
    # override existed — a personal-advice-shaped high-risk query always
    # gets the referral treatment, not a generic clarification.
    if risk_level == RISK_HIGH and advice_signal:
        return RouteDecision(route=ROUTE_REFERRAL, disclaimer_required=True, professional_referral_required=True)

    # Cross-cutting confidence overrides (any non-RESTRICTED risk)
    if confidence_state == CONF_CONFLICTING:
        return RouteDecision(route=ROUTE_REFERRAL, disclaimer_required=True, professional_referral_required=True)
    if confidence_state == CONF_STALE:
        return RouteDecision(route=ROUTE_CLARIFICATION)

    route = _MATRIX.get((risk_level, confidence_state))

    # Fallback: if risk is HIGH and confidence unknown, be conservative —
    # a referral, not a guessed answer.
    if route is None:
        route = ROUTE_REFERRAL if risk_level == RISK_HIGH else ROUTE_CLARIFICATION

    # §8.1 — Clarification cycle escalation. Was ROUTE_HUMAN_REVIEW; two
    # unresolved clarification rounds means Kriton genuinely can't narrow
    # this down itself, which is exactly what REFERRAL is for — not a
    # signal to queue it for a human.
    if route == ROUTE_CLARIFICATION and clarification_cycle >= MAX_CLARIFICATION_CYCLES:
        route = ROUTE_REFERRAL

    disclaimer_required = (
        risk_level == RISK_MEDIUM
        or risk_level == RISK_HIGH  # mandatory professional-boundary notice on every HIGH-risk answer
        or confidence_state == CONF_LIMITED
        or route == ROUTE_REFERRAL
    )

    # A hedged HIGH-risk answer (LIMITED confidence, still real sources)
    # gets the same forced referral as the advice-signal case above — weak
    # evidence behind a high-risk answer is exactly when naming a real
    # professional matters most. REFERRAL itself always carries it too.
    professional_referral_required = route == ROUTE_REFERRAL or (
        risk_level == RISK_HIGH and route == ROUTE_LLM and confidence_state != CONF_SUFFICIENT
    )

    clarification_message: Optional[str] = None
    if route == ROUTE_CLARIFICATION:
        clarification_message = _clarification_for(confidence_state, risk_level)

    return RouteDecision(
        route=route,
        disclaimer_required=disclaimer_required,
        clarification_message=clarification_message,
        professional_referral_required=professional_referral_required,
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
