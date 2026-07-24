"""
orchestration/routing_matrix.py — the canonical (risk_level, confidence_state)
-> route matrix actually used by ask_kriton() via massarius/policy_matrix.py.

No prior test file covered this module at all (test_routing_matrix.py tests
a different, legacy matrix in risk_safety/routing_matrix.py — confirmed by
import path while making this change). This covers the policy change made
this session: MEDIUM risk now always routes to LLM (with disclaimer)
regardless of confidence state, and HIGH risk + sufficient confidence now
also routes to LLM (with disclaimer) instead of HUMAN_REVIEW.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.orchestration.routing_matrix import (
    resolve_route,
    ROUTE_LLM, ROUTE_HUMAN_REVIEW, ROUTE_REFUSAL, ROUTE_CLARIFICATION,
    RISK_ZERO, RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_RESTRICTED,
    CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT,
    CONF_CONFLICTING, CONF_STALE, CONF_RESTRICTED,
)


def test_zero_risk_always_routes_to_llm_with_no_disclaimer():
    """ZERO is the new bottom tier (casual conversation/navigational help,
    e.g. greetings) — always answers directly, and unlike every other tier,
    NEVER requires a disclaimer, even under limited confidence (there's
    nothing to disclaim for 'hey what's up')."""
    for confidence in (CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT):
        decision = resolve_route(RISK_ZERO, confidence)
        assert decision.route == ROUTE_LLM, f"ZERO + {confidence} should be LLM, got {decision.route}"
        assert decision.disclaimer_required is False, f"ZERO + {confidence} must never require a disclaimer"
    print("test_zero_risk_always_routes_to_llm_with_no_disclaimer: PASSED")


def test_medium_risk_always_routes_to_llm_regardless_of_confidence():
    """The policy change: MEDIUM used to escalate to HUMAN_REVIEW on
    limited/insufficient confidence — now it always answers, with a
    mandatory disclaimer (see the next test)."""
    for confidence in (CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT):
        decision = resolve_route(RISK_MEDIUM, confidence)
        assert decision.route == ROUTE_LLM, f"MEDIUM + {confidence} should be LLM, got {decision.route}"
        assert decision.disclaimer_required is True, f"MEDIUM + {confidence} must require a disclaimer"
    print("test_medium_risk_always_routes_to_llm_regardless_of_confidence: PASSED")


def test_high_risk_sufficient_confidence_now_routes_to_llm_with_disclaimer():
    """The other half of the policy change: HIGH + sufficient confidence
    used to always escalate — now it answers directly, but MUST carry a
    disclaimer (the companion fix — without it this would ship silently
    undisclaimed, which was flagged as unacceptable before implementing)."""
    decision = resolve_route(RISK_HIGH, CONF_SUFFICIENT)
    assert decision.route == ROUTE_LLM
    assert decision.disclaimer_required is True
    print("test_high_risk_sufficient_confidence_now_routes_to_llm_with_disclaimer: PASSED")


def test_high_risk_weaker_confidence_still_escalates():
    """Only sufficient confidence changed for HIGH risk — limited/
    insufficient/conflicting must still escalate to human review, and
    restricted_sources must still refuse. This is the regression guard
    that the change was scoped narrowly, not a blanket HIGH->LLM.

    stale_sources is a documented exception, NOT a regression from this
    change: resolve_route()'s cross-cutting CONF_STALE check fires before
    the risk-specific matrix is ever consulted, so (HIGH, stale) actually
    resolves to CLARIFICATION even though the matrix dict itself declares
    (HIGH, CONF_STALE): ROUTE_HUMAN_REVIEW — that matrix entry is dead code,
    pre-existing and unrelated to today's edit, already flagged separately."""
    for confidence in (CONF_LIMITED, CONF_INSUFFICIENT, CONF_CONFLICTING):
        decision = resolve_route(RISK_HIGH, confidence)
        assert decision.route == ROUTE_HUMAN_REVIEW, (
            f"HIGH + {confidence} should still be HUMAN_REVIEW, got {decision.route}"
        )
    assert resolve_route(RISK_HIGH, CONF_STALE).route == ROUTE_CLARIFICATION  # pre-existing, see docstring
    assert resolve_route(RISK_HIGH, CONF_RESTRICTED).route == ROUTE_REFUSAL
    print("test_high_risk_weaker_confidence_still_escalates: PASSED")


def test_cross_cutting_overrides_unchanged_for_medium_risk():
    """Deliberately NOT part of the 'all MEDIUM' change — conflicting/
    stale/restricted sources are a source-quality problem, not a risk-
    tolerance question, and still override risk level entirely. This is
    the regression guard for the narrower-scope interpretation."""
    assert resolve_route(RISK_MEDIUM, CONF_CONFLICTING).route == ROUTE_HUMAN_REVIEW
    assert resolve_route(RISK_MEDIUM, CONF_STALE).route == ROUTE_CLARIFICATION
    assert resolve_route(RISK_MEDIUM, CONF_RESTRICTED).route == ROUTE_REFUSAL
    print("test_cross_cutting_overrides_unchanged_for_medium_risk: PASSED")


def test_low_and_restricted_risk_unaffected():
    """Sanity check that the change was scoped to MEDIUM/HIGH only."""
    assert resolve_route(RISK_LOW, CONF_SUFFICIENT).route == ROUTE_LLM
    assert resolve_route(RISK_LOW, CONF_INSUFFICIENT).route == ROUTE_CLARIFICATION
    assert resolve_route(RISK_RESTRICTED, CONF_SUFFICIENT).route == ROUTE_REFUSAL
    print("test_low_and_restricted_risk_unaffected: PASSED")


def main():
    test_zero_risk_always_routes_to_llm_with_no_disclaimer()
    test_medium_risk_always_routes_to_llm_regardless_of_confidence()
    test_high_risk_sufficient_confidence_now_routes_to_llm_with_disclaimer()
    test_high_risk_weaker_confidence_still_escalates()
    test_cross_cutting_overrides_unchanged_for_medium_risk()
    test_low_and_restricted_risk_unaffected()
    print("All tests passed successfully!")


if __name__ == "__main__":
    main()
