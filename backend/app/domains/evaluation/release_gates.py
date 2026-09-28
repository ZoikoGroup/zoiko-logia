def check_promotion_eligibility(
    contamination_scan_status: str,
    zero_tolerance_passed: bool,
    config_hash_valid: bool,
    blockers_count: int,
    run_complete: bool = True,
    reviewed_case_count: int | None = None,
    expected_case_count: int | None = None,
) -> bool:
    """
    Enforces the QA release gates for promoting models/policies.

    A result pack is eligible for production promotion ONLY when:
      1. Contamination scan status is 'PASSED' (gold dataset leakage prevented).
      2. Zero-tolerance safety criteria are completely satisfied.
      3. Configuration hashes match perfectly (no silent drift/untested changes).
      4. Zero blocker bugs or zero-tolerance threshold violations exist.
    """
    if contamination_scan_status != "PASSED":
        return False

    if not zero_tolerance_passed:
        return False

    if not config_hash_valid:
        return False

    if blockers_count > 0:
        return False

    if not run_complete:
        return False

    if (
        reviewed_case_count is not None
        and expected_case_count is not None
        and reviewed_case_count != expected_case_count
    ):
        return False

    return True
