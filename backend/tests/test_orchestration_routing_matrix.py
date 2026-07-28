"""
Tests for app/orchestration/routing_matrix.py::resolve_route() — the matrix
actually wired into orchestration/service.py's ask_kriton() (via
massarius/policy_matrix.py::resolve_policy()). Previously untested: the only
existing routing-matrix test file (tests/test_routing_matrix.py) covers a
different, parallel matrix (app/domains/risk_safety/routing_matrix.py) that
is NOT the one that determines real request routing — that gap in coverage
is exactly how the real matrix's HIGH-risk-always-escalates behavior went
unnoticed (masked separately by FORCE_DIRECT_ANSWER=true for a long time).

Run locally (from backend/, venv active):
    python3 tests/test_orchestration_routing_matrix.py
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.orchestration.routing_matrix import (
    resolve_route,
    RISK_ZERO, RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_RESTRICTED,
    CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT, CONF_CONFLICTING, CONF_STALE, CONF_RESTRICTED,
    ROUTE_LLM, ROUTE_HUMAN_REVIEW, ROUTE_REFERRAL, ROUTE_REFUSAL, ROUTE_CLARIFICATION,
    MAX_CLARIFICATION_CYCLES,
)

_ALL_RISK_LEVELS = (RISK_ZERO, RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_RESTRICTED)
_ALL_CONFIDENCE_STATES = (CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT, CONF_CONFLICTING, CONF_STALE, CONF_RESTRICTED)


def test_every_combination_resolves():
    for risk_level in _ALL_RISK_LEVELS:
        for confidence_state in _ALL_CONFIDENCE_STATES:
            decision = resolve_route(risk_level, confidence_state)
            assert decision is not None
            assert decision.route is not None
    print("test_every_combination_resolves: PASSED")


def test_high_risk_sufficient_confidence_answers_directly():
    """The actual fix (2026-07-20): HIGH risk + CONF_SUFFICIENT must reach
    the LLM route with a mandatory disclaimer, not auto-escalate — a
    HIGH-risk-classified question with genuinely strong sources should be
    answerable, not routed straight to a human every time."""
    decision = resolve_route(RISK_HIGH, CONF_SUFFICIENT)
    assert decision.route == ROUTE_LLM
    assert decision.disclaimer_required is True
    print("test_high_risk_sufficient_confidence_answers_directly: PASSED")


def test_high_risk_still_degrades_without_strong_sources():
    """Every confidence state weaker than CONF_SUFFICIENT must still
    degrade from a normal confident answer — the fix only opens the door
    for genuinely strong sources, it doesn't make HIGH risk universally
    answerable. 2026-07-22 (product vision doc item 3): degrading no
    longer means HUMAN_REVIEW — LIMITED still has real (if weak) sources,
    so it gets a hedged LLM answer with a forced disclaimer + professional
    referral; INSUFFICIENT has nothing to hedge from, so it's a REFERRAL
    with no composition attempt."""
    limited = resolve_route(RISK_HIGH, CONF_LIMITED)
    assert limited.route == ROUTE_LLM
    assert limited.disclaimer_required is True
    assert limited.professional_referral_required is True

    insufficient = resolve_route(RISK_HIGH, CONF_INSUFFICIENT)
    assert insufficient.route == ROUTE_REFERRAL
    assert insufficient.professional_referral_required is True
    print("test_high_risk_still_degrades_without_strong_sources: PASSED")


def test_high_risk_restricted_source_refuses():
    decision = resolve_route(RISK_HIGH, CONF_RESTRICTED)
    assert decision.route == ROUTE_REFUSAL
    print("test_high_risk_restricted_source_refuses: PASSED")


def test_restricted_risk_always_refuses_regardless_of_confidence():
    for confidence_state in _ALL_CONFIDENCE_STATES:
        decision = resolve_route(RISK_RESTRICTED, confidence_state)
        assert decision.route == ROUTE_REFUSAL, f"expected REFUSAL for ({RISK_RESTRICTED}, {confidence_state})"
    print("test_restricted_risk_always_refuses_regardless_of_confidence: PASSED")


def test_low_and_medium_risk_unaffected_by_the_fix():
    """Confirms the HIGH-risk change didn't accidentally alter LOW/MEDIUM
    behavior — LOW answers regardless of confidence (with caveats), MEDIUM
    answers with a disclaimer at sufficient confidence."""
    assert resolve_route(RISK_LOW, CONF_SUFFICIENT).route == ROUTE_LLM
    assert resolve_route(RISK_LOW, CONF_LIMITED).route == ROUTE_LLM
    assert resolve_route(RISK_LOW, CONF_INSUFFICIENT).route == ROUTE_CLARIFICATION

    medium_sufficient = resolve_route(RISK_MEDIUM, CONF_SUFFICIENT)
    assert medium_sufficient.route == ROUTE_LLM
    assert medium_sufficient.disclaimer_required is True
    # MEDIUM + weaker-than-sufficient confidence asks for clarification first
    # rather than escalating straight to a referral — MAX_CLARIFICATION_CYCLES
    # (see test_clarification_cycle_escalates_to_referral) still escalates
    # to REFERRAL if that doesn't resolve it within 2 rounds.
    assert resolve_route(RISK_MEDIUM, CONF_LIMITED).route == ROUTE_CLARIFICATION
    print("test_low_and_medium_risk_unaffected_by_the_fix: PASSED")


def test_cross_cutting_confidence_overrides_apply_to_high_risk_too():
    """CONF_CONFLICTING/CONF_STALE/CONF_RESTRICTED are cross-cutting
    overrides checked before the per-risk-level matrix lookup — must still
    apply even now that HIGH+sufficient is answerable. 2026-07-22: sources
    that genuinely conflict no longer create a human-review case — that's
    exactly the "can't confidently answer" case REFERRAL exists for."""
    assert resolve_route(RISK_HIGH, CONF_CONFLICTING).route == ROUTE_REFERRAL
    assert resolve_route(RISK_HIGH, CONF_STALE).route == ROUTE_CLARIFICATION
    assert resolve_route(RISK_HIGH, CONF_RESTRICTED).route == ROUTE_REFUSAL
    print("test_cross_cutting_confidence_overrides_apply_to_high_risk_too: PASSED")


def test_clarification_cycle_escalates_to_referral():
    """2026-07-22 (product vision doc item 3): two unresolved clarification
    rounds used to escalate to HUMAN_REVIEW; it now resolves to REFERRAL —
    Kriton genuinely can't narrow the question down itself at that point,
    which is what REFERRAL is for, not a signal to queue it for a human."""
    decision = resolve_route(RISK_LOW, CONF_INSUFFICIENT, clarification_cycle=MAX_CLARIFICATION_CYCLES)
    assert decision.route == ROUTE_REFERRAL
    print("test_clarification_cycle_escalates_to_referral: PASSED")


def test_zero_risk_answers_directly_like_low():
    """ZERO is the newest, safest tier (small talk / navigational content)
    — same permissive shape as LOW: sufficient/limited confidence both
    answer, insufficient asks for clarification rather than escalating."""
    assert resolve_route(RISK_ZERO, CONF_SUFFICIENT).route == ROUTE_LLM
    assert resolve_route(RISK_ZERO, CONF_LIMITED).route == ROUTE_LLM
    assert resolve_route(RISK_ZERO, CONF_INSUFFICIENT).route == ROUTE_CLARIFICATION
    print("test_zero_risk_answers_directly_like_low: PASSED")


def test_advice_signal_forces_referral_on_high_risk_even_when_sufficient():
    """A HIGH-risk query naming the reader's own situation ("my company",
    "should I file") must always get a forced disclaimer + professional
    referral, regardless of how strong the sources are — this is the
    actual behavior change from wiring risk_classifier.py's
    has_advice_signal through to this matrix, since it was previously
    computed but never read anywhere in the live flow. 2026-07-22 (product
    vision doc item 3): the target outcome changed from HUMAN_REVIEW to a
    safe referral without generating personalized professional advice."""
    without_signal = resolve_route(RISK_HIGH, CONF_SUFFICIENT, advice_signal=False)
    assert without_signal.route == ROUTE_LLM
    assert without_signal.professional_referral_required is False

    with_signal = resolve_route(RISK_HIGH, CONF_SUFFICIENT, advice_signal=True)
    assert with_signal.route == ROUTE_REFERRAL
    assert with_signal.disclaimer_required is True
    assert with_signal.professional_referral_required is True
    print("test_advice_signal_forces_hedged_referral_on_high_risk_even_when_sufficient: PASSED")


def test_advice_signal_only_overrides_high_risk():
    """advice_signal is a HIGH-risk-specific override, not a blanket
    escalation switch — ZERO/LOW/MEDIUM must resolve exactly the same
    whether or not the signal fired, so a query that merely mentions "my
    company" in an otherwise LOW-risk factual question doesn't get bumped
    into human review it doesn't need."""
    for risk in (RISK_ZERO, RISK_LOW, RISK_MEDIUM):
        without_signal = resolve_route(risk, CONF_SUFFICIENT, advice_signal=False)
        with_signal = resolve_route(risk, CONF_SUFFICIENT, advice_signal=True)
        assert without_signal.route == with_signal.route == ROUTE_LLM
    print("test_advice_signal_only_overrides_high_risk: PASSED")


def test_advice_signal_does_not_override_licence_restriction():
    """A restricted-licence source must still refuse even when the query
    also carries an advice signal — licensing is a harder boundary than
    the advice-signal override, checked first."""
    decision = resolve_route(RISK_HIGH, CONF_RESTRICTED, advice_signal=True)
    assert decision.route == ROUTE_REFUSAL
    print("test_advice_signal_does_not_override_licence_restriction: PASSED")


if __name__ == "__main__":
    test_every_combination_resolves()
    test_high_risk_sufficient_confidence_answers_directly()
    test_high_risk_still_degrades_without_strong_sources()
    test_high_risk_restricted_source_refuses()
    test_restricted_risk_always_refuses_regardless_of_confidence()
    test_low_and_medium_risk_unaffected_by_the_fix()
    test_cross_cutting_confidence_overrides_apply_to_high_risk_too()
    test_clarification_cycle_escalates_to_referral()
    test_zero_risk_answers_directly_like_low()
    test_advice_signal_forces_hedged_referral_on_high_risk_even_when_sufficient()
    test_advice_signal_only_overrides_high_risk()
    test_advice_signal_does_not_override_licence_restriction()
    print("All tests passed successfully!")
