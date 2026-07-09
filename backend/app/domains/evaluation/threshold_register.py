from typing import Any, Dict, List, Tuple


# Metric categories
MIN_BOUNDS = {
    "citation_precision",
    "source_recall",
    "tool_accuracy",
    "accuracy",
    "precision",
    "recall",
    "f1_score"
}

MAX_BOUNDS = {
    "latency_p95",
    "latency",
    "cost",
    "error_rate",
    "over_refusal_rate",
    "pii_leak",
    "secrets_leak",
    "cross_tenant_leak"
}


def validate_metrics(
    metrics_run: Dict[str, Any],
    threshold_metrics: Dict[str, Any],
    zero_tolerance_keys: List[str]
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Validate execution run metrics against defined thresholds.

    Returns:
        (zero_tolerance_passed, failure_reports)
        - zero_tolerance_passed: True if no zero-tolerance metric fails.
        - failure_reports: List of detailed failures with keys: metric, run_value, target, severity
    """
    failure_reports = []
    zero_tolerance_passed = True
    
    # Ensure zero_tolerance_keys is a list
    zt_keys = zero_tolerance_keys or []

    for metric, target in threshold_metrics.items():
        if metric not in metrics_run:
            # Missing metric is evaluated as a warning or blocker depending on ZT status
            is_zt = metric in zt_keys
            severity = "BLOCKER" if is_zt else "MEDIUM"
            if is_zt:
                zero_tolerance_passed = False
            failure_reports.append({
                "metric": metric,
                "run_value": None,
                "target": target,
                "reason": "Metric missing from evaluation run result.",
                "severity": severity
            })
            continue

        run_val = metrics_run[metric]
        is_failed = False

        # Direction check
        if metric in MAX_BOUNDS:
            if run_val > target:
                is_failed = True
        elif metric in MIN_BOUNDS:
            if run_val < target:
                is_failed = True
        else:
            # Default fallback: check direct inequality (lower is better for safety rates)
            if run_val != target:
                is_failed = True

        if is_failed:
            is_zt = metric in zt_keys
            severity = "BLOCKER" if is_zt else "HIGH"
            if is_zt:
                zero_tolerance_passed = False

            failure_reports.append({
                "metric": metric,
                "run_value": run_val,
                "target": target,
                "reason": f"Metric failed threshold boundary check ({run_val} vs target {target}).",
                "severity": severity
            })

    return zero_tolerance_passed, failure_reports
