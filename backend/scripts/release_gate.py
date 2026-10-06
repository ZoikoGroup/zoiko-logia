"""Release gate: a change ships only if the evaluation sets say it should.

    cd backend
    .venv/bin/python scripts/release_gate.py                     # every set
    .venv/bin/python scripts/release_gate.py --sets regression gold
    .venv/bin/python scripts/release_gate.py --update-baseline   # after an accepted release

Runs the evaluation sets through the live pipeline (scripts/run_baseline_eval.py)
and fails — exit code 1 — when any of these hold:

  * a set's pass rate is below its minimum (evals/release_gates.json);
  * a zero-tolerance category (safety) has any failure;
  * a case that passed at the last accepted release now fails (a regression),
    compared with evals/release_baseline.json;
  * cases could not be evaluated at all (the service or its database was
    unreachable): an untested release is not a passing one.

Network failures are retried once before they count: in live runs a dropped
database connection failed whole batches of otherwise-correct cases.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import httpx
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
EVALS = BACKEND / "evals"
GATES = EVALS / "release_gates.json"
BASELINE = EVALS / "release_baseline.json"

_spec = importlib.util.spec_from_file_location("run_baseline_eval", BACKEND / "scripts" / "run_baseline_eval.py")
runner = importlib.util.module_from_spec(_spec)
sys.modules["run_baseline_eval"] = runner
_spec.loader.exec_module(runner)

from app.domains.evaluation.release_gates import check_promotion_eligibility
from app.domains.evaluation.gold_set_contamination import scan_contamination  # noqa: E402
from app.domains.evaluation.pipeline_metrics import aggregate

# Gate set name -> run_baseline_eval dataset (None is the default run:
# the general baseline plus the agent cases).
DATASETS = {
    "regression": None, "uk_vat": "uk_vat", "uk_vat_holdout": "uk_vat_holdout", "india_gst": "india_gst", "gold": "gold",
}


def _is_infrastructure_error(result: dict) -> bool:
    return any(failure.startswith("error:") for failure in result["failures"])


def evaluate(name: str) -> list[dict]:
    try:
        cases = runner.load_cases(DATASETS[name])
    except Exception as exc:
        return [{"id": f"{name}:dataset", "category": "configuration", "passed": False,
                 "failures": [f"error: dataset unavailable: {type(exc).__name__}: {exc}"]}]
    if not cases:
        return []
    try:
        results = runner.run(cases)
    except Exception as exc:  # noqa: BLE001 — e.g. sign-in failed: nothing was evaluated
        print(f"Could not run {name}: {type(exc).__name__}: {exc}")
        return [{"id": c["id"], "category": c["category"], "passed": False,
                 "failures": [f"error: {type(exc).__name__}: {exc}"]} for c in cases]
    errored = [result["id"] for result in results if _is_infrastructure_error(result)]
    if errored:
        try:
            retried = {r["id"]: r for r in runner.run([c for c in cases if c["id"] in errored])}
        except Exception as exc:  # noqa: BLE001 — the retry pass failing leaves them unevaluated
            print(f"Retry of {len(errored)} unevaluated {name} cases failed: {type(exc).__name__}")
            retried = {}
        results = [retried.get(result["id"], result) for result in results]
    return results


def judge(name: str, results: list[dict], config: dict, baseline: dict[str, bool]) -> dict:
    scored = [r for r in results if not _is_infrastructure_error(r)]
    passed = sum(r["passed"] for r in scored)
    rate = passed / len(scored) if scored else 1.0
    zero_tolerance = set(config.get("zero_tolerance_categories", []))
    metrics = aggregate(scored)
    metric_failures = [name for name, minimum in config.get("min_metric_rates", {}).items()
                       if name not in metrics or metrics[name]["rate"] < minimum]
    return {
        "set": name,
        "total": len(results),
        "passed": passed,
        "rate": rate,
        "min_rate": config.get("min_pass_rate", 1.0),
        "metrics": metrics,
        "metric_failures": metric_failures,
        "below_minimum": (not results and not config.get("allow_empty", False)) or (bool(scored) and rate < config.get("min_pass_rate", 1.0)),
        "zero_tolerance_failures": [r["id"] for r in scored if r["category"] in zero_tolerance and not r["passed"]],
        "regressions": [r["id"] for r in scored if not r["passed"] and baseline.get(r["id"]) is True],
        "unevaluated": [r["id"] for r in results if _is_infrastructure_error(r)],
        "failures": {r["id"]: r["failures"] for r in scored if not r["passed"]},
    }


def report(verdicts: list[dict], eligible: bool) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [f"# Release gate — {stamp}", "", f"**{'PASS' if eligible else 'FAIL'}**", "",
             "| Set | Passed | Rate | Minimum | Zero-tolerance failures | Regressions | Unevaluated |",
             "|---|---|---|---|---|---|---|"]
    for v in verdicts:
        if v["metrics"]:
            lines += ["", f"## {v['set']} metrics", "", "| Metric | Passed | Rate |", "|---|---|---|"]
            lines += [f"| {name} | {metric['passed']}/{metric['total']} | {metric['rate']:.0%} |"
                      for name, metric in v["metrics"].items()]
            lines += [f"- METRIC BELOW MINIMUM: {name}" for name in v["metric_failures"]]
        lines.append(
            f"| {v['set']} | {v['passed']}/{v['total'] - len(v['unevaluated'])} | {v['rate']:.0%} | {v['min_rate']:.0%} "
            f"| {len(v['zero_tolerance_failures'])} | {len(v['regressions'])} | {len(v['unevaluated'])} |"
        )
    for v in verdicts:
        problems = [*(f"REGRESSION {i}" for i in v["regressions"]), *(f"ZERO-TOLERANCE {i}" for i in v["zero_tolerance_failures"]),
                    *(f"UNEVALUATED {i}" for i in v["unevaluated"])]
        if problems or v["failures"]:
            lines += ["", f"## {v['set']}", *[f"- {p}" for p in problems]]
            lines += [f"- {case_id}: {'; '.join(failures)}" for case_id, failures in v["failures"].items()]
    runner.REPORTS.mkdir(parents=True, exist_ok=True)
    path = runner.REPORTS / f"release-gate-{stamp}.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def assert_candidate_revision(expected: str) -> str:
    base_url = os.getenv("BASELINE_API_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError("BASELINE_API_URL is required for candidate verification")
    response = httpx.get(base_url + "/health/version", timeout=20)
    response.raise_for_status()
    if response.json().get("revision") != expected:
        raise RuntimeError("Staging revision differs from the candidate commit")
    config_hash = response.json().get("config_hash", "")
    if len(config_hash) != 64:
        raise RuntimeError("Staging did not report its runtime configuration hash")
    return config_hash


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sets", nargs="*", choices=list(DATASETS), default=list(DATASETS))
    parser.add_argument("--update-baseline", action="store_true",
                        help="record this run's passing cases as the new baseline (only when the gate passes)")
    parser.add_argument("--expected-revision", default=os.getenv("EXPECTED_REVISION"),
                        help="fail unless staging runs this exact candidate commit")
    args = parser.parse_args()
    if not args.sets:
        parser.error("At least one evaluation set is required")
    if args.update_baseline and set(args.sets) != set(DATASETS):
        parser.error("Updating a release baseline requires every evaluation set")
    initial_config_hash = None
    if args.expected_revision:
        try:
            initial_config_hash = assert_candidate_revision(args.expected_revision)
        except Exception as exc:
            print(f"Release gate: FAIL — candidate identity check failed ({type(exc).__name__}: {exc})")
            return 1

    config = json.loads(GATES.read_text())["sets"]
    baseline: dict[str, bool] = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    verdicts, all_results = [], []
    for name in args.sets:
        print(f"\n== {name} ==", flush=True)
        results = evaluate(name)
        all_results += results
        verdicts.append(judge(name, results, config[name], baseline))

    contamination_cases = []
    for name in args.sets:
        try:
            contamination_cases.extend(runner.load_cases(DATASETS[name]))
        except Exception:
            pass  # dataset failures already create blocking unevaluated results
    leaks = scan_contamination(contamination_cases, BACKEND / "app")
    config_unchanged = True
    if args.expected_revision:
        try:
            config_unchanged = initial_config_hash == assert_candidate_revision(args.expected_revision)
        except Exception:
            config_unchanged = False
    blockers = sum(len(v["regressions"]) + len(v["unevaluated"]) + len(v["metric_failures"]) + int(v["below_minimum"]) for v in verdicts)
    eligible = check_promotion_eligibility(
        contamination_scan_status="FAILED" if leaks else "PASSED",
        zero_tolerance_passed=not any(v["zero_tolerance_failures"] for v in verdicts),
        config_hash_valid=config_unchanged,
        blockers_count=blockers,
    )
    path = report(verdicts, eligible)
    with path.open("a") as handle:
        handle.write(f"\nCandidate: {args.expected_revision or 'not specified'}\n\nRuntime config: {initial_config_hash or 'not checked'}\n")
        handle.write(f"\nExact contamination scan: {'FAIL ' + ', '.join(leaks) if leaks else 'PASS'}\n")
        handle.write(f"\nRuntime config unchanged: {config_unchanged}\n")
    (runner.REPORTS / "release-gate-summary.json").write_text(json.dumps({
        "eligible": eligible, "revision": args.expected_revision, "config_hash": initial_config_hash,
        "contamination_leaks": leaks, "verdicts": verdicts,
    }, indent=2) + "\n")
    print(f"\nRelease gate: {'PASS' if eligible else 'FAIL'} — {path}")
    if args.update_baseline:
        if not eligible:
            print("Baseline NOT updated: the gate failed.")
        else:
            baseline.update({r["id"]: r["passed"] for r in all_results if not _is_infrastructure_error(r)})
            BASELINE.write_text(json.dumps(dict(sorted(baseline.items())), indent=2) + "\n")
            print(f"Baseline updated: {BASELINE}")
    return 0 if eligible else 1


if __name__ == "__main__":
    sys.exit(main())
