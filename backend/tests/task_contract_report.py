"""Task Contract, Stage A: how the shadow contract's understanding compares
with the expected understanding. Not collected by the normal test run; run it
explicitly:

    TASK_CONTRACT_REPORT=report.json python -m pytest -q tests/task_contract_report.py

Three sets, each replayed through the real pipeline with the model stubbed,
the contract taken from the kriton.task_contract log (stage "calculated", or
"understood" when the pipeline stopped earlier):
- evals/task_contract_expectations.json: hand-annotated defect classes and
  case studies (deliverables, message type, case scope, constraints);
- evals/regression_conversations.json: each turn's expected outcome;
- the everyday evaluation questions that record an expected outcome.
The pipeline's own outcome is reported beside the contract, so a contract
that merely agrees with a wrong pipeline is visible. No network or model.
"""
import glob
import json
import logging
import os
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.schemas import AskKritonRequest, ConversationMessage
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

EVALS = Path(__file__).resolve().parents[1] / "evals"


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[tuple[str, dict]] = []

    def emit(self, record):
        match = re.match(r"Task contract query=\S+ stage=(\w+) (\{.*\})$", record.getMessage())
        if match:
            self.records.append((match.group(1), json.loads(match.group(2))))

    def latest(self) -> dict | None:
        for stage in ("calculated", "understood"):
            for name, summary in reversed(self.records):
                if name == stage:
                    return summary
        return None


async def _ask(pipeline, capture, query, history, *, previous=None, cycle=0, reply_to=None):
    capture.records.clear()
    pipeline.answers(AgentOutcome(text="Model answer placeholder."))
    request = AskKritonRequest(query=query, conversation_history=history[-12:], previous_query=previous,
                               clarification_cycle=cycle, reply_to=reply_to)
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=request, clarification_cycle=cycle)
    return response, capture.latest()


def _check_annotated(expect: dict, c: dict) -> list[str]:
    problems = []
    kinds = c["deliverables"]
    if "message_type" in expect and c["message_type"] not in expect["message_type"]:
        problems.append(f"message_type {c['message_type']}, expected {expect['message_type']}")
    if "parts" in expect and len(c["parts"]) != expect["parts"]:
        problems.append(f"{len(c['parts'])} parts, expected {expect['parts']}")
    for kind in expect.get("deliverables_include", []):
        if kind not in kinds:
            problems.append(f"deliverable '{kind}' missing (has {sorted(set(kinds))})")
    for kind in expect.get("deliverables_exclude", []):
        if kind in kinds:
            problems.append(f"deliverable '{kind}' not asked for")
    if "deliverables_count" in expect and len(kinds) != expect["deliverables_count"]:
        problems.append(f"{len(kinds)} deliverables, expected {expect['deliverables_count']}")
    if expect.get("missing_inputs") == "none" and c["missing_inputs"]:
        problems.append(f"{c['missing_inputs']} missing input(s) recorded, none expected")
    if "statements_requested" in expect and c["constraints"]["statements_requested"] != expect["statements_requested"]:
        problems.append(f"statements_requested {c['constraints']['statements_requested']}, expected {expect['statements_requested']}")
    if "chart_requested" in expect and c["constraints"]["chart_requested"] != expect["chart_requested"]:
        problems.append(f"chart_requested {c['constraints']['chart_requested']}")
    if "case_id" in expect and c["case"]["case_id"] != expect["case_id"]:
        problems.append(f"case {c['case']['case_id']} ({c['case']['resolution_kind']}), expected {expect['case_id']}")
    if "facts_out_of_scope" in expect and c["facts_out_of_scope"] != expect["facts_out_of_scope"]:
        problems.append(f"{c['facts_out_of_scope']} out-of-scope history fact(s) other stages would add")
    in_scope = c["facts"]["history"] - c["facts_out_of_scope"]
    if "history_facts_in_scope" in expect and in_scope != expect["history_facts_in_scope"]:
        problems.append(f"{in_scope} history fact(s) treated as in scope, expected {expect['history_facts_in_scope']}")
    for name in expect.get("validations_exclude", []):
        if name in c["validations"]:
            problems.append(f"validation '{name}' would apply")
    if expect.get("calculation") and not any(expect["calculation"] in f for f in c["calculation"]):
        problems.append(f"calculation {c['calculation'] or 'none'}, expected {expect['calculation']}")
    return problems


def _check_outcome(expected: str, c: dict | None) -> list[str]:
    """What the contract implies about an outcome the dataset expects."""
    if c is None:
        return ["no contract recorded"]
    asks = c["missing_inputs"] > 0 or c["message_type"] in ("statement", "context", "correction") \
        or c["case"]["resolution_kind"] == "ambiguous" or c["calculation_status"] == "clarification_required"
    if expected == "acknowledged" and c["message_type"] not in ("context", "correction"):
        return [f"expected a context statement, contract says {c['message_type']}"]
    if expected == "clarification_required" and not asks:
        return ["expected a clarification, contract records nothing missing or ambiguous"]
    if expected == "answered" and (c["missing_inputs"] > 0 or c["calculation_status"] == "clarification_required"):
        return ["expected an answer, contract records a missing input"]
    return []


async def test_task_contract_report(pipeline):
    capture = _Capture()
    logger = logging.getLogger("kriton.task_contract")
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    report = {"annotated": [], "regression": [], "everyday": []}
    try:
        for case in json.load(open(EVALS / "task_contract_expectations.json"))["cases"]:
            history = [ConversationMessage(role="user", content=text) for text in case["history"]]
            response, c = await _ask(pipeline, capture, case["query"], history)
            problems = _check_annotated(case["expect"], c) if c else ["no contract recorded"]
            report["annotated"].append({"id": case["id"], "group": case["group"], "contract": c, "disagreements": problems,
                                        "pipeline_outcome": response.outcome,
                                        "pipeline_message": ((response.next_action.message if response.next_action else "") or "")[:140]})

        dataset = json.load(open(EVALS / "regression_conversations.json"))
        for conv in (c for c in dataset["cases"] if c["mode"] == "offline"):
            history, outcomes, clarified, last_id = [], [], [], None
            for index, turn in enumerate(conv["turns"], 1):
                if "live_expected" in turn["expect"]:
                    break
                cycle = 0
                for outcome in reversed(outcomes):
                    if outcome != "clarification_required":
                        break
                    cycle += 1
                previous = conv["turns"][index - 2]["user"] if index > 1 else None
                reply_to = None
                if turn["expect"].get("reply_to_clarification") and clarified:
                    carried = [u for i, (u, a) in enumerate(clarified) if i == 0 or a != clarified[i - 1][1]]
                    reply_to, previous = last_id, "\n".join(carried)
                response, c = await _ask(pipeline, capture, turn["user"], history, previous=previous, cycle=cycle, reply_to=reply_to)
                expected = turn["expect"].get("outcome") or ("answered" if turn["expect"].get("calculation") else None)
                problems = _check_outcome(expected, c) if expected else []
                if turn["expect"].get("calculation") and c and c["calculation_status"] != "success":
                    problems.append(f"expected a calculation, contract calculation_status {c['calculation_status']}")
                report["regression"].append({"case": conv["id"], "turn": index, "expected": expected,
                                             "pipeline_outcome": response.outcome, "contract": c, "disagreements": problems})
                history.append(ConversationMessage(role="user", content=turn["user"]))
                if response.answer and response.answer.text:
                    history.append(ConversationMessage(role="assistant", content=response.answer.text[:8000]))
                outcomes.append(response.outcome)
                asked = (response.next_action.message if response.next_action else "") or ""
                clarified = clarified + [(turn["user"], asked.strip())] if response.outcome == "clarification_required" else []
                last_id = response.query_id

        seen = set()
        for path in sorted(glob.glob(str(EVALS / "*.json"))):
            if any(name in path for name in ("regression_conversations", "task_contract_expectations")):
                continue
            try:
                data = json.load(open(path))
            except Exception:  # noqa: BLE001
                continue
            stack = [data]
            while stack:
                node = stack.pop()
                if isinstance(node, list):
                    stack.extend(node)
                elif isinstance(node, dict):
                    stack.extend(node.values())
                    question = node.get("question") or node.get("query")
                    expected = node.get("outcome") or (node.get("expect") or {}).get("outcome") if isinstance(node.get("expect"), dict) else node.get("outcome")
                    if isinstance(question, str) and isinstance(expected, str) and not node.get("turns") and question not in seen:
                        seen.add(question)
                        response, c = await _ask(pipeline, capture, question, [])
                        report["everyday"].append({"file": Path(path).name, "question": question[:160], "expected": expected,
                                                   "pipeline_outcome": response.outcome, "contract": c,
                                                   "disagreements": _check_outcome(expected, c)})
    finally:
        logger.removeHandler(capture)
    out = os.environ.get("TASK_CONTRACT_REPORT")
    if out:
        Path(out).write_text(json.dumps(report, indent=1, default=str))
