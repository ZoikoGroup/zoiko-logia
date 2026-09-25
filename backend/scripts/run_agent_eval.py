"""Run the agent evaluation set (evals/agent_questions.json) against the live
agent loop and report tool selection, grounding checks and latency.

    cd backend
    .venv/bin/python scripts/run_agent_eval.py                  # all cases
    .venv/bin/python scripts/run_agent_eval.py --category calculation
    .venv/bin/python scripts/run_agent_eval.py --ids fx-01 calc-02 --concurrency 1

Calls the real model provider (GROQ_API_KEY from backend/.env) and the real
data connectors, so it costs provider tokens and needs network access. Writes
a JSON report next to the dataset (evals/reports/, git-ignored content).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from app.domains.model_gateway import service as gateway  # noqa: E402
from app.domains.model_gateway.agent import with_agent_instructions  # noqa: E402
from app.orchestration.websearch import build_web_grounded_prompt  # noqa: E402

DATASET = BACKEND / "evals" / "agent_questions.json"
REPORTS = BACKEND / "evals" / "reports"
REFUSAL_MARKER = "designed to answer questions related to accounting"


@dataclass
class CaseResult:
    id: str
    category: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)
    steps: int = 0
    stop_reason: str = ""
    seconds: float = 0.0
    answer_preview: str = ""


def score(case: dict, text: str, tools_called: list[str]) -> list[str]:
    failures: list[str] = []
    lowered = text.lower()
    called = set(tools_called)
    for tool in case.get("expect_tools", []):
        if tool not in called:
            failures.append(f"expected tool {tool} was not called")
    forbidden = case.get("forbid_tools", [])
    if "*" in forbidden and called:
        failures.append(f"no tools expected, called {sorted(called)}")
    for tool in forbidden:
        if tool != "*" and tool in called:
            failures.append(f"forbidden tool {tool} was called")
    for needle in case.get("must_contain", []):
        if needle.lower() not in lowered:
            failures.append(f"answer missing {needle!r}")
    for needle in case.get("must_not_contain", []):
        if needle.lower() in lowered:
            failures.append(f"answer contains {needle!r}")
    if case.get("refusal") and REFUSAL_MARKER not in lowered:
        failures.append("expected the off-domain refusal")
    return failures


async def run_case(case: dict) -> CaseResult:
    started = time.monotonic()
    # The same prompt production sends in agent mode (domain gate, formatting
    # rules, tool instructions) — with no pre-fetched web sources, so the
    # eval isolates what the agent fetches itself.
    prompt = with_agent_instructions(build_web_grounded_prompt(case["question"], []))
    try:
        outcome = await gateway.run_agentic_completion(prompt, granted_permissions=frozenset())
    except Exception as exc:  # the report must cover every case
        return CaseResult(
            id=case["id"], category=case["category"], passed=False,
            failures=[f"agent raised {type(exc).__name__}: {str(exc)[:200]}"],
            seconds=round(time.monotonic() - started, 1),
        )
    tools = [call.tool for call in outcome.tool_calls if call.error_code != "duplicate_call"]
    failures = score(case, outcome.text, tools)
    return CaseResult(
        id=case["id"], category=case["category"], passed=not failures, failures=failures,
        tools_called=tools,
        tool_errors=[f"{c.tool}:{c.error_code}" for c in outcome.tool_calls if c.error_code],
        steps=outcome.steps, stop_reason=outcome.stop_reason,
        seconds=round(time.monotonic() - started, 1),
        answer_preview=outcome.text.strip().replace("\n", " ")[:240],
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", action="append", help="only these categories (repeatable)")
    parser.add_argument("--ids", nargs="+", help="only these case ids")
    parser.add_argument("--concurrency", type=int, default=1, help="cases run at once")
    parser.add_argument(
        "--delay", type=float, default=8.0,
        help="seconds to pause after each case — keeps a run under the provider's tokens-per-minute limit",
    )
    args = parser.parse_args()

    cases = json.loads(DATASET.read_text())["cases"]
    if args.category:
        cases = [c for c in cases if c["category"] in args.category]
    if args.ids:
        cases = [c for c in cases if c["id"] in args.ids]
    if not cases:
        print("No cases selected.")
        return 2

    semaphore = asyncio.Semaphore(max(args.concurrency, 1))

    async def bounded(case: dict) -> CaseResult:
        async with semaphore:
            result = await run_case(case)
            mark = "PASS" if result.passed else "FAIL"
            print(f"[{mark}] {result.id:<13} {result.seconds:>5.1f}s  tools={result.tools_called}"
                  + (f"  ← {'; '.join(result.failures)}" if result.failures else ""), flush=True)
            await asyncio.sleep(args.delay)
            return result

    results = await asyncio.gather(*(bounded(case) for case in cases))

    print("\n── Summary by category ──")
    categories = sorted({r.category for r in results})
    for category in categories:
        group = [r for r in results if r.category == category]
        passed = sum(r.passed for r in group)
        avg = sum(r.seconds for r in group) / len(group)
        print(f"  {category:<12} {passed}/{len(group)} passed   avg {avg:.1f}s")
    total_passed = sum(r.passed for r in results)
    print(f"  {'TOTAL':<12} {total_passed}/{len(results)} passed")

    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORTS / f"agent_eval_{stamp}.json"
    report_path.write_text(json.dumps({
        "dataset_version": json.loads(DATASET.read_text())["version"],
        "run_at": stamp,
        "passed": total_passed,
        "total": len(results),
        "results": [r.__dict__ for r in results],
    }, indent=2))
    print(f"\nReport: {report_path.relative_to(BACKEND)}")
    return 0 if total_passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
