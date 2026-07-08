def check_promotion_eligibility(
    contamination_scan_status: str,
    zero_tolerance_passed: bool,
    config_hash_valid: bool,
    blockers_count: int
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

    return True
