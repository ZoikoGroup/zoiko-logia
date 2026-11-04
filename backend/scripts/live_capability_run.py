"""The capability suite against the live stack, in-process (3 Nov 2026).

Real: the answer pipeline, the model (Groq), web search, official-page reads,
live-data connectors, and governed-library reads for the evaluation account.
Not exercised: the HTTP sign-in layer (no evaluation password is configured).
Nothing is written: every turn's database work is rolled back, and audit,
review and finalisation writes are stubbed.

Each conversation is sent as the frontend sends it (reply_to, previous_query,
clarification_cycle, history of user turns and answers). A turn passes when
its offline expectations hold and, for a "live" expectation, the figure is
in the answer and the authority among its citations.

    python3 scripts/live_capability_run.py OUT.json [case-id-prefix ...]
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import config  # noqa: E402,F401  (loads .env)
from app.core.database import AsyncSessionLocal, SessionLocal  # noqa: E402
from app.orchestration import learned_answers, review, service  # noqa: E402
from app.orchestration.schemas import AskKritonRequest, ConversationMessage  # noqa: E402

SUITE = Path(__file__).resolve().parents[1] / "evals" / "capability_suite.json"
ACTOR, TENANT = "57533e2f-%", "5d2d63b4-%"   # resolved from the evaluation account below


def _normal(text: str) -> str:
    return re.sub(r"[\s£$€₹,]|rs\.?", "", (text or "").lower())


async def _account() -> tuple[str, str]:
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text("select id, tenant_id from users where email='dashboard@zoikologia.com' limit 1"))).first()
        await db.rollback()
    return str(row[0]), str(row[1])


async def run_case(case: dict, actor: str, tenant: str) -> list[dict]:
    history, exchange, results = [], [], []
    for turn in case["turns"]:
        expect = turn["expect"]
        fields = {"query": turn["query"], "conversation_history": list(history), "conversation_id": f"cap-{case['id']}"}
        if exchange:
            carried = [i for n, i in enumerate(exchange) if n == 0 or i["question"] != exchange[n - 1]["question"]]
            fields.update(reply_to=exchange[-1]["query_id"], previous_query="\n".join(i["query"] for i in carried),
                          clarification_cycle=len(exchange))
        request = AskKritonRequest(**fields)
        started = time.monotonic()
        async with AsyncSessionLocal() as db:
            sync_db = SessionLocal()
            try:
                response = await asyncio.wait_for(service.ask_kriton(
                    db, sync_db, actor_id=actor, tenant_id=tenant, role="ACCOUNTANT", request=request,
                    clarification_cycle=request.clarification_cycle, conversation_id=request.conversation_id), timeout=150)
            except Exception as exc:  # noqa: BLE001
                results.append({"query": turn["query"], "passed": False, "problems": [f"error {type(exc).__name__}: {str(exc)[:160]}"]})
                await db.rollback(); sync_db.rollback(); sync_db.close()
                break
            await db.rollback(); sync_db.rollback(); sync_db.close()
        asked = response.outcome == "clarification_required"
        question = (response.next_action.message if response.next_action else "") or ""
        text = (response.answer.text if response.answer else "") or ""
        cited = [c.url or "" for c in (response.answer.citations if response.answer else [])]
        problems = []
        if expect.get("outcome") == "ask" and not asked:
            problems.append(f"did not ask ({response.outcome})")
        if expect.get("outcome") == "answer" and asked:
            problems.append(f"asked: {question[:120]}")
        if expect.get("ask_contains") and asked and expect["ask_contains"] not in question:
            problems.append(f"question lacks {expect['ask_contains']!r}")
        if expect.get("answer_contains") and not asked and expect["answer_contains"] not in text:
            problems.append(f"answer lacks {expect['answer_contains']!r}")
        if expect.get("answer_excludes") and expect["answer_excludes"] in text:
            problems.append(f"answer contains {expect['answer_excludes']!r}")
        live = expect.get("live") or {}
        if live.get("figure") and not asked and _normal(live["figure"]) not in _normal(text):
            problems.append(f"live figure {live['figure']!r} not in answer")
        if live.get("authority") and not asked:
            host = live["authority"].split()[0].split("/")[0]
            if not any(host in url for url in cited):
                problems.append(f"live authority {host!r} not cited (cited: {[u.split('/')[2] for u in cited if '//' in u][:4]})")
        completeness = response.answer.completeness if response.answer else None
        results.append({"query": turn["query"], "passed": not problems, "problems": problems, "outcome": response.outcome,
                        "completeness": completeness, "route": response.route, "seconds": round(time.monotonic() - started, 1),
                        "question": question[:300], "answer": text[:700], "citations": cited[:6],
                        "limitations": list(response.answer.limitations)[:4] if response.answer else []})
        history.append(ConversationMessage(role="user", content=turn["query"]))
        if asked:
            exchange.append({"query": turn["query"], "query_id": response.query_id, "question": question})
        else:
            exchange = []
            if text.strip():
                history.append(ConversationMessage(role="assistant", content=text[:4000]))
    return results


async def main(out: str, prefixes: list[str]):
    for name in dir(service):
        if name.startswith("audit_"):
            setattr(service, name, AsyncMock())
    service._finalise_and_return = AsyncMock()
    review.record_answer = AsyncMock()
    learned_answers.record_feedback = AsyncMock() if hasattr(learned_answers, "record_feedback") else None
    actor, tenant = await _account()
    cases = [c for c in json.loads(SUITE.read_text())["cases"] if not prefixes or any(c["id"].startswith(p) for p in prefixes)]
    report = []
    for case in cases:
        turns = await run_case(case, actor, tenant)
        passed = bool(turns) and len(turns) == len(case["turns"]) and all(t["passed"] for t in turns)
        report.append({"id": case["id"], "domain": case["domain"], "category": case["category"], "passed": passed, "turns": turns})
        print(("PASS " if passed else "FAIL ") + case["id"] + ("" if passed else "  " + " | ".join(p for t in turns for p in t["problems"])[:220]),
              flush=True)
        Path(out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(f"LIVE CAPABILITY SUITE: {sum(r['passed'] for r in report)}/{len(report)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
