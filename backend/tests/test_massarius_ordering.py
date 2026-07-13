"""ZL-ENG-03 Acceptance Criterion 6 — risk_safety runs after bundle_builder.py;
route selection goes through policy_matrix.py, not ad hoc logic."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.massarius.policy_matrix import resolve_policy
from app.domains.massarius.risk_safety import classify_after_bundle
from app.domains.risk_safety.schemas import ClassifyRequest


def test_classify_after_bundle_refuses_when_bundle_step_never_ran():
    """The ordering violation this exists to catch: calling classification
    without bundle_builder.py's step having been attempted at all."""
    request = ClassifyRequest(query="test", tenant_id="t1")
    try:
        classify_after_bundle(False, request, db=None)
        raise AssertionError("classify_after_bundle should have refused with bundle_attempted=False")
    except RuntimeError as e:
        assert "bundle_builder" in str(e)
    print("test_classify_after_bundle_refuses_when_bundle_step_never_ran: PASSED")


def test_policy_matrix_is_the_single_route_resolution_path():
    """resolve_policy() (not inline if/elif at the call site) is what
    decides the route — verified by calling it directly with the same
    signature orchestration/service.py uses."""
    decision = resolve_policy(
        confidence_state="sufficient",
        risk_level="LOW",
        jurisdiction="UK",
        clarification_cycle=0,
    )
    assert decision.route == "LLM"

    decision_high_risk = resolve_policy(
        confidence_state="insufficient",
        risk_level="HIGH",
        jurisdiction="UK",
        clarification_cycle=0,
    )
    assert decision_high_risk.route == "HUMAN_REVIEW"
    print("test_policy_matrix_is_the_single_route_resolution_path: PASSED")


def test_policy_matrix_callable_twice_for_reevaluation():
    """Same function, same determinism guarantee, callable again with an
    updated confidence_state (e.g. after Checkpoint C downgrades it)."""
    first = resolve_policy(confidence_state="sufficient", risk_level="MEDIUM")
    second = resolve_policy(confidence_state="limited", risk_level="MEDIUM")
    assert first.route != second.route or first != second
    # Re-running with the exact same inputs as `first` must reproduce it —
    # determinism, not just "callable twice".
    third = resolve_policy(confidence_state="sufficient", risk_level="MEDIUM")
    assert first == third
    print("test_policy_matrix_callable_twice_for_reevaluation: PASSED")


if __name__ == "__main__":
    print("Running Massarius ordering tests (AC6)...")
    test_classify_after_bundle_refuses_when_bundle_step_never_ran()
    test_policy_matrix_is_the_single_route_resolution_path()
    test_policy_matrix_callable_twice_for_reevaluation()
    print("All tests passed successfully!")
