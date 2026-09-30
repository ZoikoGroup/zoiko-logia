"""Routing policy pm_1.3 — LOW (pm_1.1) and MEDIUM (pm_1.2) questions with no or
limited governed evidence answer with a caveat instead of an unanswerable
clarification or a reviewer queue; HIGH (pm_1.3) answers as general guidance
with the disclaimer; conflicting, stale and restricted keep their safeguards."""
from app.orchestration.routing_matrix import (
    CONF_CONFLICTING, CONF_INSUFFICIENT, CONF_LIMITED, CONF_RESTRICTED, CONF_STALE, CONF_SUFFICIENT,
    POLICY_VERSION,
    RISK_HIGH, RISK_LOW, RISK_MEDIUM, RISK_RESTRICTED,
    ROUTE_CLARIFICATION, ROUTE_HUMAN_REVIEW, ROUTE_LLM, ROUTE_REFUSAL, resolve_route,
)


def test_policy_version_recorded_for_the_change() -> None:
    assert POLICY_VERSION == "pm_1.3"


def test_low_risk_without_governed_evidence_answers_with_caveat() -> None:
    decision = resolve_route(RISK_LOW, CONF_INSUFFICIENT)
    assert decision.route == ROUTE_LLM
    assert decision.disclaimer_required is True
    assert decision.clarification_message is None


def test_low_risk_is_not_escalated_on_later_cycles() -> None:
    assert resolve_route(RISK_LOW, CONF_INSUFFICIENT, clarification_cycle=5).route == ROUTE_LLM


def test_medium_general_method_questions_answer_with_disclaimer() -> None:
    for confidence in (CONF_LIMITED, CONF_INSUFFICIENT):
        decision = resolve_route(RISK_MEDIUM, confidence)
        assert decision.route == ROUTE_LLM and decision.disclaimer_required is True


def test_high_risk_answers_as_general_guidance_with_disclaimer() -> None:
    """pm_1.3."""
    for confidence in (CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT):
        decision = resolve_route(RISK_HIGH, confidence)
        assert decision.route == ROUTE_LLM and decision.disclaimer_required is True


def test_riskier_or_restricted_cases_keep_their_safeguards() -> None:
    assert resolve_route(RISK_HIGH, CONF_CONFLICTING).route == ROUTE_HUMAN_REVIEW
    assert resolve_route(RISK_HIGH, CONF_STALE).route == ROUTE_CLARIFICATION
    assert resolve_route(RISK_HIGH, CONF_RESTRICTED).route == ROUTE_REFUSAL
    assert resolve_route(RISK_LOW, CONF_RESTRICTED).route == ROUTE_REFUSAL
    assert resolve_route(RISK_RESTRICTED, CONF_SUFFICIENT).route == ROUTE_REFUSAL


def test_unchanged_low_risk_rows() -> None:
    assert resolve_route(RISK_LOW, CONF_SUFFICIENT).route == ROUTE_LLM
    limited = resolve_route(RISK_LOW, CONF_LIMITED)
    assert limited.route == ROUTE_LLM and limited.disclaimer_required is True
