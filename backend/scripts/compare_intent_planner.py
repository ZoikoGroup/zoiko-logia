"""Shadow evaluation of the intent planner against the live rule router.

Reads a benchmark report from scripts/run_baseline_eval.py (what the router
actually did for each case, run through the live pipeline), asks the planner
for its proposal on the same question and earlier user turns, and compares
both with the case labels. The planner's proposals are never executed.

    .venv/bin/python scripts/compare_intent_planner.py evals/reports/<run>.json --label planner-shadow
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(BACKEND / ".env")

from app.orchestration import intent_planner  # noqa: E402

EVALS = BACKEND / "evals"
REPORTS = EVALS / "reports"
SECURITY_CATEGORIES = {"security"}


def labelled_cases() -> dict[str, dict]:
    cases = {}
    for name in ("intelligence_questions.json", "planner_shadow_questions.json"):
        for case in json.loads((EVALS / name).read_text())["cases"]:
            cases[case["id"]] = case
    return cases


def router_intent(result: dict) -> str:
    if result.get("outcome") == "refused" or result.get("route") == "REFUSAL":
        return "off_domain"
    return result.get("rule_intent") or "explanation"


def router_tools(result: dict) -> set[str]:
    tools = set(result.get("tools_used") or [])
    if result.get("route") == "CALCULATION" and result.get("outcome") == "answered":
        tools.add("calculate")   # the deterministic calculator, which is not an agent tool call
    return tools


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1) if ordered else 0.0


async def plan_all(results: list[dict], cases: dict[str, dict]) -> dict[str, intent_planner.PlanResult]:
    gate = asyncio.Semaphore(3)

    async def one(result):
        case = cases[result["id"]]
        history = [{"role": "user", "content": turn} for turn in case.get("turns", [])]
        async with gate:
            plan = await intent_planner.propose_plan(case["question"], history, has_documents=bool(case.get("attach")))
        return result["id"], intent_planner.apply_policy_invariants(plan, case["question"])

    return dict(await asyncio.gather(*(one(result) for result in results)))


def evaluate(results: list[dict], plans: dict, cases: dict) -> dict:
    rows = []
    for result in results:
        case = cases[result["id"]]
        planned = plans[result["id"]]
        plan = planned.plan
        gold = case.get("expect_intent")
        router = router_intent(result)
        used = router_tools(result)
        proposed = set(plan.tools) if plan else set()
        forbid, need = set(case.get("forbid_tools", [])), set(case.get("expect_tools", []))
        sub_gold = set(case.get("expect_sub_intents", []))
        sub_plan = {task.kind for task in plan.sub_tasks} if plan else set()
        rows.append({
            "id": case["id"], "group": result.get("group"), "category": case.get("category"),
            "gold_intent": gold, "router_intent": router, "planner_intent": plan.intent if plan else None,
            "router_correct": intent_planner.same_intent(router, gold),
            "planner_correct": bool(plan) and intent_planner.same_intent(plan.intent, gold),
            "agree": bool(plan) and intent_planner.same_intent(plan.intent, router),
            "router_unneeded_tools": sorted(used & forbid), "planner_unneeded_tools": sorted(proposed & forbid),
            "router_missing_tools": sorted(need - used), "planner_missing_tools": sorted(need - proposed),
            "router_tools": sorted(used), "planner_tools": sorted(proposed),
            "sub_intents_expected": sorted(sub_gold),
            "planner_sub_intents": sorted(sub_plan),
            "planner_covers_sub_intents": (not sub_gold) or all(
                any(intent_planner.same_intent(kind, want) for kind in sub_plan) for want in sub_gold),
            "invalid_case": case.get("category") == "invalid_input" and gold == "clarification",
            "planner_flags_invalid": bool(plan and plan.invalid_inputs),
            "expect_uses_conversation": case.get("expect_uses_conversation"),
            "planner_uses_conversation": plan.uses_conversation if plan else None,
            "router_route": result.get("route"), "router_outcome": result.get("outcome"),
            "router_seconds": result.get("seconds"), "router_tokens": result.get("tokens") or 0,
            "benchmark_passed": result.get("passed"), "benchmark_failures": result.get("failures", []),
            "planner_latency_ms": round(planned.latency_ms), "planner_tokens": planned.tokens,
            "planner_failure": planned.failure, "invariants_applied": planned.invariants_applied,
            "planner_missing_inputs": plan.missing_inputs if plan else [],
            "planner_invalid_inputs": plan.invalid_inputs if plan else [],
        })
    return summarise(rows)


def summarise(rows: list[dict]) -> dict:
    available = [r for r in rows if r["planner_intent"]]
    n = len(rows)

    def rate(items, key):
        return round(100 * sum(1 for r in items if r[key]) / len(items), 1) if items else None

    by_category = defaultdict(lambda: {"cases": 0, "router_correct": 0, "planner_correct": 0, "agree": 0})
    for r in rows:
        bucket = by_category[r["category"]]
        bucket["cases"] += 1
        bucket["router_correct"] += r["router_correct"]
        bucket["planner_correct"] += r["planner_correct"]
        bucket["agree"] += r["agree"]
    invalid = [r for r in rows if r["invalid_case"]]
    convo = [r for r in rows if r["expect_uses_conversation"] is not None and r["planner_intent"]]
    mixed = [r for r in rows if r["sub_intents_expected"]]
    security = [r for r in rows if r["category"] in SECURITY_CATEGORIES]
    latencies = [r["planner_latency_ms"] for r in available]
    router_seconds = [r["router_seconds"] for r in rows if r["router_seconds"] is not None]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases": n, "planner_available": len(available),
        "planner_failures": Counter(r["planner_failure"] for r in rows if r["planner_failure"]),
        "intent_accuracy_router_pct": rate(rows, "router_correct"),
        "intent_accuracy_planner_pct": rate(rows, "planner_correct"),
        "planner_router_agreement_pct": rate(available, "agree"),
        "router_wrong_planner_right": [r["id"] for r in rows if not r["router_correct"] and r["planner_correct"]],
        "planner_wrong_router_right": [r["id"] for r in rows if r["router_correct"] and not r["planner_correct"]],
        "both_wrong": [r["id"] for r in rows if not r["router_correct"] and not r["planner_correct"]],
        "router_unneeded_tool_cases": {r["id"]: r["router_unneeded_tools"] for r in rows if r["router_unneeded_tools"]},
        "planner_unneeded_tool_cases": {r["id"]: r["planner_unneeded_tools"] for r in rows if r["planner_unneeded_tools"]},
        "router_missing_tool_cases": {r["id"]: r["router_missing_tools"] for r in rows if r["router_missing_tools"]},
        "planner_missing_tool_cases": {r["id"]: r["planner_missing_tools"] for r in rows if r["planner_missing_tools"]},
        "invalid_inputs": {"cases": len(invalid), "planner_flagged": sum(r["planner_flags_invalid"] for r in invalid),
                           "router_clarified": sum(r["router_intent"] == "clarification" for r in invalid)},
        "uses_conversation": {"cases": len(convo), "planner_correct": sum(
            r["planner_uses_conversation"] == r["expect_uses_conversation"] for r in convo)},
        "mixed_requests": {"cases": len(mixed), "planner_covers_all_parts": sum(r["planner_covers_sub_intents"] for r in mixed)},
        "security": {"cases": len(security), "router_refused_or_off_domain": sum(r["router_intent"] == "off_domain" for r in security),
                     "planner_off_domain": sum(r["planner_intent"] == "off_domain" for r in security),
                     "planner_tools_on_security_cases": {r["id"]: r["planner_tools"] for r in security if r["planner_tools"]}},
        "policy_invariants_applied": Counter(item.split(":")[0] for r in rows for item in r["invariants_applied"]),
        "latency": {"planner_ms_median": pct(latencies, 0.5), "planner_ms_p90": pct(latencies, 0.9),
                    "planner_tokens_total": sum(r["planner_tokens"] for r in rows),
                    "router_request_s_median": pct(router_seconds, 0.5), "router_request_s_p90": pct(router_seconds, 0.9),
                    "router_tokens_total": sum(r["router_tokens"] for r in rows)},
        "benchmark_pass_rate_pct": rate(rows, "benchmark_passed"),
        "by_category": dict(by_category),
        "rows": rows,
    }


def markdown(summary: dict, source: str) -> str:
    lines = [f"# Intent planner — shadow evaluation", "", f"Router results: `{source}`", "",
             f"- Cases: {summary['cases']} (planner answered {summary['planner_available']})",
             f"- Intent accuracy — router {summary['intent_accuracy_router_pct']}%, planner {summary['intent_accuracy_planner_pct']}%",
             f"- Planner/router agreement: {summary['planner_router_agreement_pct']}%",
             f"- Planner latency median {summary['latency']['planner_ms_median']} ms, p90 {summary['latency']['planner_ms_p90']} ms",
             "", "| Case | Gold | Router | Planner | Router tools | Planner tools |", "|---|---|---|---|---|---|"]
    for r in summary["rows"]:
        if not (r["router_correct"] and r["planner_correct"]):
            lines.append(f"| {r['id']} | {r['gold_intent']} | {r['router_intent']} | {r['planner_intent']} | "
                         f"{', '.join(r['router_tools']) or '—'} | {', '.join(r['planner_tools']) or '—'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", help="benchmark report JSON from run_baseline_eval.py")
    parser.add_argument("--label", default="planner-shadow")
    args = parser.parse_args()
    data = json.loads(Path(args.report).read_text())
    results = data["results"] if isinstance(data, dict) else data
    cases = labelled_cases()
    results = [r for r in results if r["id"] in cases]
    plans = asyncio.run(plan_all(results, cases))
    summary = evaluate(results, plans, cases)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = REPORTS / f"{args.label}-{stamp}"
    out.with_suffix(".json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    out.with_suffix(".md").write_text(markdown(summary, args.report))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rows", "by_category")}, indent=2, default=str))
    print("wrote", out.with_suffix(".json"))


if __name__ == "__main__":
    main()
