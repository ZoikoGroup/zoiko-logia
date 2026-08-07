"""Regression tests for the service.evaluate() -> risk_classifier.classify()
seam.

This seam was completely untested: every other risk test calls classify()
directly, and test_massarius_ordering.py only exercises
classify_after_bundle()'s bundle_attempted=False guard, which raises before
reaching evaluate(). So when ClassifyRequest gained a `history` field and
evaluate() started forwarding `history=request.history` without classify()
declaring that parameter, 1280 passing tests said nothing while every real
query that got past pre-screening returned 500:

    TypeError: classify() got an unexpected keyword argument 'history'

These run with db=None, which skips event logging/escalation entirely (see
_finalize), so they need no database.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.risk_safety import service as risk_safety_service
from app.domains.risk_safety.risk_classifier import classify
from app.domains.risk_safety.schemas import ClassifyRequest


def test_evaluate_reaches_the_classifier_without_a_signature_mismatch():
    """The exact call the /ask path makes. Any keyword evaluate() forwards
    that classify() does not declare fails here rather than in production."""
    decision = risk_safety_service.evaluate(
        ClassifyRequest(query="What is the VAT registration threshold?"),
        db=None,
    )
    assert decision.query_id
    assert decision.risk_level in {"LOW", "MEDIUM", "HIGH", "RESTRICTED"}
    assert decision.route


def test_evaluate_forwards_a_populated_history_without_raising():
    """history defaults to [], so an empty list alone would not have caught
    a mis-typed parameter. Populate it to exercise the real forward."""
    decision = risk_safety_service.evaluate(
        ClassifyRequest(
            query="What about the following year?",
            history=["What is the VAT registration threshold?"],
        ),
        db=None,
    )
    assert decision.query_id


def test_every_classify_request_field_evaluate_forwards_is_accepted():
    """Guards the seam generally rather than one field at a time: builds a
    request with every ClassifyRequest field set to a non-default value, so a
    future field that evaluate() forwards but classify() does not declare
    fails here immediately."""
    request = ClassifyRequest(
        query="Should my company restate last year's accounts?",
        user_id="user-1",
        role="Practitioner",
        tenant_id="tenant-1",
        jurisdiction="UK",
        mode="Review",
        source_confidence="SUFFICIENT",
        pre_bundle_state="OK",
        privacy_class="NONE",
        tenant_policy_conflict=True,
        tool_required=True,
        history=["Prior question one", "Prior question two"],
    )
    decision = risk_safety_service.evaluate(request, db=None)
    assert decision.query_id


def test_classify_ignores_history_until_contextual_intent_is_implemented():
    """Pins the deliberate no-op documented on classify(). `history` is
    accepted so the schema -> service -> classifier contract lines up, but it
    does not yet influence the decision.

    When contextual intent resolution is actually implemented, this test is
    expected to fail — that is the point. Update it deliberately, with the
    governance review that changing a follow-up's risk level deserves, rather
    than letting the behaviour change land silently."""
    query = "What about the following year?"
    without_history = classify(query, query_id="fixed-id")
    with_history = classify(
        query,
        query_id="fixed-id",
        history=["Is my company required to file a corporation tax return?"],
    )

    assert with_history["risk_level"] == without_history["risk_level"]
    assert with_history["route"] == without_history["route"]
    assert with_history["rules_applied"] == without_history["rules_applied"]


if __name__ == "__main__":
    test_evaluate_reaches_the_classifier_without_a_signature_mismatch()
    test_evaluate_forwards_a_populated_history_without_raising()
    test_every_classify_request_field_evaluate_forwards_is_accepted()
    test_classify_ignores_history_until_contextual_intent_is_implemented()
    print("All tests passed successfully!")
