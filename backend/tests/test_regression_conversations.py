"""The regression conversations (evals/regression_conversations.json), offline.

Built from the 27-28 Oct 2026 test chats. Each conversation is replayed turn by
turn the way the frontend sends it: the earlier user messages and answers as
history, the clarification cycle counted from the trailing "clarification
required" turns, and the previous message as previous_query. The model is
stubbed: an offline turn checks what Kriton decides without it (routes,
calculations, acknowledgements, clarifications, chart offers); a 'recorded'
case applies Kriton's checks to an answer the model actually wrote; a 'live'
case needs retrieval or live data and is skipped here.

An expectation with target_stage above the dataset's implemented_stage is a
later stage's agreed behaviour: it is reported as pending (xfail), not passed.
REGRESSION_DATASET points at another copy of the dataset; REGRESSION_REPORT
names a JSON-lines file for a per-turn report. No model, database or network.
"""
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.schemas import AskKritonRequest, ConversationMessage
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

DATASET_PATH = Path(os.environ.get("REGRESSION_DATASET")
                    or Path(__file__).resolve().parents[1] / "evals" / "regression_conversations.json")
DATASET = json.loads(DATASET_PATH.read_text())
IMPLEMENTED = DATASET["implemented_stage"]
CASES = {case["id"]: case for case in DATASET["cases"]}
MODEL_PLACEHOLDER = "Model answer placeholder."


def _report(case_id, turn, status, problems):
    path = os.environ.get("REGRESSION_REPORT")
    if path:
        with open(path, "a") as handle:
            handle.write(json.dumps({"case": case_id, "turn": turn, "status": status, "problems": problems},
                                    ensure_ascii=False) + "\n")


def _outputs(response):
    return {o.name: o.display_value for o in response.calculation.outputs} if response.calculation else {}


def _message(response):
    return (response.next_action.message if response.next_action else "") or ""


def _check_offline(expect, response, model_called, prompt):
    """The problems found for one turn's expectations (empty when it passes)."""
    problems = []
    message, answer = _message(response), (response.answer.text if response.answer else "") or ""
    limitations = list(response.answer.limitations) if response.answer else []
    if "outcome" in expect and response.outcome != expect["outcome"]:
        problems.append(f"outcome {response.outcome!r}, expected {expect['outcome']!r}")
    if "route" in expect and response.route != expect["route"]:
        problems.append(f"route {response.route!r}, expected {expect['route']!r}")
    for name, value in (expect.get("calculation") or {}).items():
        if _outputs(response).get(name) != value:
            problems.append(f"{name} {_outputs(response).get(name)!r}, expected {value!r}")
    if expect.get("no_calculation") and _outputs(response):
        problems.append(f"calculated {_outputs(response)} although an input was missing or ambiguous")
    if expect.get("no_vat_calculation") and "vat_payable" in _outputs(response):
        problems.append("carried the earlier VAT calculation into a new task")
    if expect.get("model_not_called") and model_called:
        problems.append("reached the model")
    if "message_starts" in expect and not message.startswith(expect["message_starts"]):
        problems.append(f"message {message[:80]!r} does not start {expect['message_starts']!r}")
    if "message_not_starts" in expect and message.startswith(expect["message_not_starts"]):
        problems.append(f"message starts {expect['message_not_starts']!r}: {message[:80]!r}")
    for text in expect.get("message_contains", []):
        if text.lower() not in message.lower():
            problems.append(f"message lacks {text!r}: {message[:100]!r}")
    for text in expect.get("prompt_not_contains", []):
        if prompt and text in prompt:
            problems.append(f"model prompt contains {text!r}")
    if "chart_offer" in expect:
        offered = response.chart_offer.chart_type if response.chart_offer else "none"
        if offered != expect["chart_offer"]:
            problems.append(f"chart offer {offered!r}, expected {expect['chart_offer']!r}")
    if expect.get("no_calculation_check_flag") and any(l.startswith("Calculation check") for l in limitations):
        problems.append("flagged its own calculation as differing")
    return problems


def _check_recorded(user, expect):
    from app.orchestration.accounting_validation import (
        accounting_findings, accounting_review_note, calculation_discrepancies)
    from app.orchestration.answer_formatting import remove_visual_placeholders
    from app.orchestration.calculation_service import validate_answer_calculations
    problems = []
    if expect.get("recorded_answer_is_calculator_output"):
        from app.orchestration.calculations.engine import calculation_markdown
        from app.orchestration.calculations.lease import lease_calculation
        result = lease_calculation(user)
        if expect.get("no_discrepancy") and calculation_discrepancies(calculation_markdown(result), result):
            problems.append("the calculator's own answer was flagged as a figure mismatch")
        return problems
    answer = expect["recorded_answer"]
    rules = [f.rule for f in accounting_findings(answer)]
    note = accounting_review_note(accounting_findings(answer)) or ""
    for rule in expect.get("findings_include", []):
        if rule not in rules:
            problems.append(f"finding {rule!r} not raised (got {rules})")
    for rule in expect.get("findings_exclude", []):
        if rule in rules:
            problems.append(f"finding {rule!r} raised on a correct answer")
    for text in expect.get("note_contains", []):
        if text not in note:
            problems.append(f"review note lacks {text!r}: {note[:120]!r}")
    for text in expect.get("note_not_contains", []):
        if text in note:
            problems.append(f"review note contains {text!r}")
    if "journal_failures" in expect:
        failed = bool([f for f in validate_answer_calculations(answer) if f.startswith("Journal")])
        if failed != expect["journal_failures"]:
            problems.append(f"journal check {'flagged' if failed else 'passed'} the answer")
    shown = remove_visual_placeholders(answer)
    for text in expect.get("displayed_not_contains", []):
        if text in shown:
            problems.append(f"displayed answer still contains {text!r}")
    return problems


def _split(expect):
    """(current expectations, pending ones) by target_stage."""
    if expect.get("target_stage", 0) > IMPLEMENTED:
        return {}, {k: v for k, v in expect.items() if k != "target_stage"}
    return {k: v for k, v in expect.items() if k != "target_stage"}, {}


@pytest.mark.parametrize("case_id", [c["id"] for c in DATASET["cases"] if c["mode"] == "recorded"])
def test_recorded(case_id):
    case = CASES[case_id]
    failures = []
    for index, turn in enumerate(case["turns"], 1):
        problems = _check_recorded(turn["user"], turn["expect"])
        _report(case_id, index, "fail" if problems else "pass", problems)
        failures += [f"turn {index}: {p}" for p in problems]
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("case_id", [c["id"] for c in DATASET["cases"] if c["mode"] == "live"])
def test_live(case_id):
    _report(case_id, 1, "live-only", [CASES[case_id]["turns"][0]["expect"].get("live_expected", "")])
    pytest.skip("needs retrieval or live data: run live, with approval")


@pytest.mark.parametrize("case_id", [c["id"] for c in DATASET["cases"] if c["mode"] == "offline"])
async def test_offline(pipeline, case_id):
    case = CASES[case_id]
    history: list[ConversationMessage] = []
    outcomes: list[str] = []
    # The open clarification: (user message, Kriton's question after it), in order.
    clarified: list[tuple[str, str]] = []
    last_query_id = None
    failures, pending = [], []
    for index, turn in enumerate(case["turns"], 1):
        current, later = _split(turn["expect"])
        if "live_expected" in turn["expect"]:
            _report(case_id, index, "live-only", [turn["expect"]["live_expected"]])
            break               # later turns would depend on a model answer
        pipeline.answers(AgentOutcome(text=MODEL_PLACEHOLDER))
        pipeline.agent.reset_mock()
        cycle = 0
        for outcome in reversed(outcomes):
            if outcome != "clarification_required":
                break
            cycle += 1
        previous_query = case["turns"][index - 2]["user"] if index > 1 else None
        reply_to = None
        if turn["expect"].get("reply_to_clarification") and clarified:
            # As the current frontend sends a reply to Kriton's question
            # (lib/clarification-reply.ts): its id, and the request with the
            # replies that changed Kriton's question. Other turns send no
            # reply_to, so they exercise the older-client path.
            carried = [user for i, (user, asked) in enumerate(clarified) if i == 0 or asked != clarified[i - 1][1]]
            reply_to, previous_query = last_query_id, "\n".join(carried)
        # The frontend sends at most the last 12 messages (schemas: max_length=12).
        request = AskKritonRequest(query=turn["user"], conversation_history=list(history)[-12:],
                                   previous_query=previous_query, clarification_cycle=cycle, reply_to=reply_to)
        response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                            request=request, clarification_cycle=cycle)
        called = pipeline.agent.await_count > 0
        prompt = pipeline.agent.await_args.args[0] if called else ""
        problems = _check_offline(current, response, called, prompt)
        waiting = _check_offline(later, response, called, prompt) if later else []
        _report(case_id, index, "fail" if problems else ("pending" if waiting else "pass"), problems + waiting)
        failures += [f"turn {index}: {p}" for p in problems]
        pending += [f"turn {index}: {p}" for p in waiting]
        history.append(ConversationMessage(role="user", content=turn["user"]))
        if response.answer and response.answer.text:
            history.append(ConversationMessage(role="assistant", content=response.answer.text[:8000]))
        outcomes.append(response.outcome)
        asked = (response.next_action.message if response.next_action else "") or ""
        clarified = clarified + [(turn["user"], asked.strip())] if response.outcome == "clarification_required" else []
        last_query_id = response.query_id
    assert not failures, "\n".join(failures)
    if pending:
        pytest.xfail("pending a later stage: " + "; ".join(pending))
