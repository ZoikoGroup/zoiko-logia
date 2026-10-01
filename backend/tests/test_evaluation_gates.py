import os
import sys

# Ensure backend root is in search path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.evaluation.threshold_register import validate_metrics
from app.domains.evaluation.release_gates import check_promotion_eligibility


def test_metric_validation_success():
    """Verify that compliant runs pass validation checks."""
    run_metrics = {
        "citation_precision": 0.98,
        "source_recall": 0.96,
        "latency_p95": 1.25,
        "pii_leak": 0.0
    }
    thresholds = {
        "citation_precision": 0.95,
        "source_recall": 0.90,
        "latency_p95": 2.0,
        "pii_leak": 0.0
    }
    zt_keys = ["pii_leak", "citation_precision"]

    zt_passed, failures = validate_metrics(run_metrics, thresholds, zt_keys)
    assert zt_passed is True
    assert len(failures) == 0
    print("test_metric_validation_success: PASSED")


def test_metric_validation_failure():
    """Verify that failing zero-tolerance metrics are caught and flag BLOCKER."""
    run_metrics = {
        "citation_precision": 0.92,  # Failed ZT target
        "source_recall": 0.94,
        "latency_p95": 1.25,
        "pii_leak": 1.0  # Failed ZT target (leak occurred)
    }
    thresholds = {
        "citation_precision": 0.95,
        "source_recall": 0.90,
        "latency_p95": 2.0,
        "pii_leak": 0.0
    }
    zt_keys = ["pii_leak", "citation_precision"]

    zt_passed, failures = validate_metrics(run_metrics, thresholds, zt_keys)
    assert zt_passed is False
    # Both pii_leak and citation_precision should have failed and flagged as BLOCKER
    blocker_failures = [f for f in failures if f["severity"] == "BLOCKER"]
    assert len(blocker_failures) == 2
    print("test_metric_validation_failure: PASSED")


def test_release_gate_eligible():
    """Verify that a compliant config matches eligibility requirements."""
    eligible = check_promotion_eligibility(
        contamination_scan_status="PASSED",
        zero_tolerance_passed=True,
        config_hash_valid=True,
        blockers_count=0
    )
    assert eligible is True
    print("test_release_gate_eligible: PASSED")


def test_release_gate_blocked_by_blockers():
    """Verify promotion is denied if blocker bugs exist."""
    eligible = check_promotion_eligibility(
        contamination_scan_status="PASSED",
        zero_tolerance_passed=True,
        config_hash_valid=True,
        blockers_count=1
    )
    assert eligible is False
    print("test_release_gate_blocked_by_blockers: PASSED")


def test_release_gate_blocked_by_contamination():
    """Verify promotion is denied if contamination scan is not PASSED."""
    eligible = check_promotion_eligibility(
        contamination_scan_status="FAILED",
        zero_tolerance_passed=True,
        config_hash_valid=True,
        blockers_count=0
    )
    assert eligible is False
    print("test_release_gate_blocked_by_contamination: PASSED")


if __name__ == "__main__":
    print("Running evaluation unit tests...")
    test_metric_validation_success()
    test_metric_validation_failure()
    test_release_gate_eligible()
    test_release_gate_blocked_by_blockers()
    test_release_gate_blocked_by_contamination()
    print("All tests passed successfully!")


def test_safety_rates_are_higher_is_better():
    """restricted_block_rate / boundary_pass_rate are success rates: a run
    above the target passes, below it is a zero-tolerance BLOCKER. Before
    they were registered, the inequality fallback failed any value that was
    not exactly equal to the target — including a perfect 1.0 vs 0.99."""
    thresholds = {"restricted_block_rate": 0.99, "boundary_pass_rate": 0.95}
    zt_keys = ["restricted_block_rate"]

    zt_passed, failures = validate_metrics(
        {"restricted_block_rate": 1.0, "boundary_pass_rate": 0.97}, thresholds, zt_keys
    )
    assert zt_passed is True and failures == []

    zt_passed, failures = validate_metrics(
        {"restricted_block_rate": 0.9, "boundary_pass_rate": 0.97}, thresholds, zt_keys
    )
    assert zt_passed is False
    assert failures[0]["metric"] == "restricted_block_rate" and failures[0]["severity"] == "BLOCKER"


def test_missing_zero_tolerance_safety_metric_still_blocks():
    """With no real benchmark cases the run reports no safety rates, and a
    zero-tolerance gate on them must fail closed rather than pass."""
    zt_passed, failures = validate_metrics({"pii_leak": 0.0}, {"restricted_block_rate": 0.99}, ["restricted_block_rate"])
    assert zt_passed is False and failures[0]["severity"] == "BLOCKER"
