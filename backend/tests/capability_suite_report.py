"""The capability suite (evals/capability_suite.json) through the real ask_kriton
pipeline, offline: only persistence, retrieval and the model are replaced
(tests/test_answer_status_pipeline.py). Not collected by the normal run:

    CAPABILITY_REPORT=report.json python -m pytest -q -s tests/capability_suite_report.py

Each conversation is sent as the frontend sends it (lib/clarification-reply.ts:
a reply carries reply_to, previous_query and clarification_cycle; history
replays the user's messages and the answers, not Kriton's questions). Graded
offline: the outcome (asked or answered), the question's content, a
deterministic answer's content, and the Task Contract's classification.
A "live" expectation (a figure from an official page) needs the integrated
application and is listed, never graded here."""
import json
import os
from collections import defaultdict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.schemas import AskKritonRequest, ConversationMessage
from app.orchestration.task_contract import build_task_contract
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

SUITE = Path(__file__).resolve().parents[1] / "evals" / "capability_suite.json"


def _question(response) -> str:
    return (response.next_action.message if response.next_action else "") or ""


def _contract_checks(query: str, expect: dict) -> list[str]:
    wanted = expect.get("contract")
    if not wanted:
        return []
    official = [r for r in build_task_contract(query).retrieval if r.needs_official]
    problems = []
    if "needs_official" in wanted and bool(official) != wanted["needs_official"]:
        problems.append(f"needs_official {bool(official)}")
    if official and "fact" in wanted and official[0].fact_type != wanted["fact"]:
        problems.append(f"fact {official[0].fact_type}")
    if official and "countries" in wanted and official[0].jurisdictions != wanted["countries"]:
        problems.append(f"countries {official[0].jurisdictions}")
    if official and "period" in wanted and official[0].period.kind != wanted["period"]:
        problems.append(f"period {official[0].period.kind}")
    return problems


async def _run_case(pipeline, case: dict) -> list[dict]:
    turns, history, exchange, results = case["turns"], [], [], []
    for turn in turns:
        expect = turn["expect"]
        fields = {"query": turn["query"], "conversation_history": list(history)}
        if exchange:
            # openClarification: the clarification turns since the last answer,
            # less a reply after which the same question was asked again.
            carried = [item for index, item in enumerate(exchange)
                       if index == 0 or item["question"] != exchange[index - 1]["question"]]
            fields.update(reply_to=exchange[-1]["query_id"], previous_query="\n".join(i["query"] for i in carried),
                          clarification_cycle=len(exchange))
        pipeline.agent.reset_mock()
        pipeline.answers(AgentOutcome(text="MODEL ANSWER PLACEHOLDER."))
        try:
            response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                                request=AskKritonRequest(**fields))
        except Exception as exc:  # noqa: BLE001
            results.append({"query": turn["query"], "passed": False, "problems": [f"error {type(exc).__name__}: {exc}"[:200]]})
            break
        asked = response.outcome == "clarification_required"
        text = (response.answer.text if response.answer else "") or ""
        problems = []
        if expect.get("outcome") == "ask" and not asked:
            problems.append(f"did not ask ({response.outcome}, model={bool(pipeline.agent.await_count)})")
        if expect.get("outcome") == "answer" and asked:
            problems.append(f"asked: {_question(response)[:110]}")
        if expect.get("ask_contains") and asked and expect["ask_contains"] not in _question(response):
            problems.append(f"question lacks {expect['ask_contains']!r}: {_question(response)[:110]}")
        if expect.get("answer_contains") and not asked and expect["answer_contains"] not in text:
            problems.append(f"answer lacks {expect['answer_contains']!r}: {text[:110]!r}")
        if expect.get("answer_excludes") and expect["answer_excludes"] in text:
            problems.append(f"answer contains {expect['answer_excludes']!r}")
        problems += [f"contract {p}" for p in _contract_checks(turn["query"], expect)]
        results.append({"query": turn["query"], "passed": not problems, "problems": problems, "live": expect.get("live"),
                        "outcome": response.outcome, "route": response.route, "model": bool(pipeline.agent.await_count)})
        history.append(ConversationMessage(role="user", content=turn["query"]))
        if asked:
            exchange.append({"query": turn["query"], "query_id": response.query_id, "question": _question(response)})
        else:
            exchange = []
            if text.strip():
                history.append(ConversationMessage(role="assistant", content=text[:4000]))
    return results


async def test_capability_suite(pipeline):
    cases = json.loads(SUITE.read_text())["cases"]
    report, matrix = [], defaultdict(lambda: [0, 0])
    for case in cases:
        turns = await _run_case(pipeline, case)
        passed = bool(turns) and all(t["passed"] for t in turns) and len(turns) == len(case["turns"])
        report.append({"id": case["id"], "domain": case["domain"], "category": case["category"], "passed": passed, "turns": turns})
        matrix[(case["domain"], case["category"])][0] += passed
        matrix[(case["domain"], case["category"])][1] += 1
    total = sum(r["passed"] for r in report)
    print(f"\nCAPABILITY SUITE: {total}/{len(report)} cases pass offline")
    for (domain, category), (ok, n) in sorted(matrix.items()):
        print(f"  {domain:9s} {category:13s} {ok}/{n}")
    for r in report:
        if not r["passed"]:
            print(f"  FAIL {r['id']}: " + " | ".join(p for t in r["turns"] for p in t["problems"])[:260])
    live = [(r["id"], t["live"]) for r in report for t in r["turns"] if t.get("live")]
    print(f"  live-only expectations (not graded offline): {len(live)}")
    out = os.environ.get("CAPABILITY_REPORT")
    if out:
        Path(out).write_text(json.dumps({"passed": total, "cases": len(report), "report": report,
                                         "matrix": {f"{d}/{c}": v for (d, c), v in matrix.items()}}, indent=1, ensure_ascii=False))
