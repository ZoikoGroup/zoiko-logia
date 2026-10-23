"""Acceptance checks for the 22 Oct 2026 fixes, before any new PR.

Offline: the model is scripted; prompts and request sizes are measured from
what the pipeline would send. Numerical correctness of live answers is not
assessed here (no model calls); hand-derived answers are in the review doc.
xfail(strict=True) marks a check that fails today because its fix does not
exist yet — measured, not hidden.
"""
import json
import logging
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.domains.model_gateway.errors import ProviderResponseIncomplete
from app.orchestration import service
from app.orchestration.schemas import ConversationMessage
from tests.test_answer_status_pipeline import pipeline  # noqa: F401  (fixture)

QUESTIONS = json.loads((Path(__file__).parent / "fixtures" / "acceptance_questions_20261022.json").read_text())
ORDER = list(QUESTIONS)


def _capture(pipeline, monkeypatch, answer="Scripted answer."):
    prompts: list[str] = []

    async def agentic(prompt, *args, **kwargs):
        prompts.append(prompt)
        return AgentOutcome(text=answer)

    async def standard(*args, **kwargs):
        prompts.append(" ".join(a for a in args if isinstance(a, str)))
        return answer

    pipeline.agent.side_effect = agentic
    monkeypatch.setattr(service.model_gateway_service, "run_test_prompt", AsyncMock(side_effect=standard))
    return prompts


def _user(text):
    return ConversationMessage(role="user", content=text)


def _assistant(text="Answered."):
    return ConversationMessage(role="assistant", content=text)


# 1. Two unrelated questions in one chat: the second does not inherit the first's figures.
async def test_an_unrelated_second_question_does_not_inherit_the_first_questions_figures(pipeline, monkeypatch):
    prompts = _capture(pipeline, monkeypatch)
    await pipeline.ask(QUESTIONS["lcnrv"], history=[_user(QUESTIONS["nexus"]), _assistant()])
    assert prompts and "$180,000" not in prompts[-1] and "$120,000" not in prompts[-1]
    assert "$150" in prompts[-1]


# 2. A genuine follow-up keeps the figure it refers to.
async def test_a_genuine_follow_up_keeps_the_prior_figure(pipeline, monkeypatch):
    prompts = _capture(pipeline, monkeypatch)
    history = [_user("Our company's taxable profit for 2026 is $180,000."), _assistant("Noted: $180,000.")]
    await pipeline.ask("Now calculate the tax on that amount at 25%.", history=history)
    assert prompts and "$180,000" in prompts[-1]


async def test_a_follow_up_naming_a_company_introduced_with_a_suffix_keeps_its_scenario(pipeline, monkeypatch):
    prompts = _capture(pipeline, monkeypatch)
    history = [_user(QUESTIONS["fx"]), _assistant(), _user(QUESTIONS["benford"]), _assistant()]
    await pipeline.ask("For EuroTech, what changes if the settlement rate is $1.15 instead?", history=history)
    assert prompts and "€500,000" in prompts[-1] and "2,800" not in prompts[-1]


async def test_a_follow_up_naming_a_company_with_a_lowercase_suffix_keeps_its_scenario(pipeline, monkeypatch):
    prompts = _capture(pipeline, monkeypatch)
    history = [_user(QUESTIONS["vie"]), _assistant()]
    await pipeline.ask("What are Titan Development's reporting consequences if the guarantee is removed?", history=history)
    assert prompts and "$1,900,000" in prompts[-1]


# 3. Every scenario alone, and all of them in one chat: standalone, nothing trimmed.
def _sizes(caplog):
    for record in caplog.records:
        found = re.search(r"estimated_input_before=(\d+) estimated_input_after=(\d+)", record.getMessage())
        if found:
            return int(found.group(1)), int(found.group(2))
    return None


@pytest.mark.parametrize("name", ORDER)
async def test_each_scenario_alone_fits_without_trimming(pipeline, monkeypatch, caplog, name):
    _capture(pipeline, monkeypatch)
    caplog.set_level(logging.INFO, logger="kriton.requests")
    await pipeline.ask(QUESTIONS[name])
    before, after = _sizes(caplog)
    assert before == after and after <= 5_500, (name, before, after)


async def test_all_scenarios_in_one_chat_stay_standalone_and_untrimmed(pipeline, monkeypatch, caplog):
    _capture(pipeline, monkeypatch, answer="Scripted answer of realistic length. " * 40)
    caplog.set_level(logging.INFO, logger="kriton.requests")
    history: list[ConversationMessage] = []
    for name in ORDER:
        caplog.clear()
        await pipeline.ask(QUESTIONS[name], history=history[-12:])
        kinds = [re.search(r"kind=(\w+)", r.getMessage()).group(1) for r in caplog.records
                 if "Conversation resolution" in r.getMessage()]
        before, after = _sizes(caplog)
        assert kinds and kinds[-1] in {"first_turn", "standalone"}, (name, kinds)
        assert before == after and after <= 5_500, (name, before, after)
        history += [_user(QUESTIONS[name]), _assistant("Scripted answer of realistic length. " * 40)]


# 5. A truncated answer is a labelled partial result, never a false "no answer".
async def test_a_truncated_agent_answer_is_shown_as_partial(pipeline):
    pipeline.agent.side_effect = None
    pipeline.agent.return_value = AgentOutcome(
        text="Allocated price: server $108,000; maintenance $54,000; support $18,000. Revenue in 2026",
        incomplete_reason="the model reached its output token limit")
    response, audited = await pipeline.ask(QUESTIONS["nexus"])
    assert response.answer is not None and response.answer.completeness == "partial"
    assert any("output token limit" in item for item in response.answer.limitations)


async def test_a_truncated_standard_answer_is_shown_as_partial(pipeline, monkeypatch):
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: False)
    finished = ("Return on equity uses average equity of $1,750,000 and net income of $468,000, giving 26.74%. "
                "Net profit margin is 9.00%, asset turnover 1.677 and the equity multiplier 1.771.\n\n"
                "Interpretation: the margin rose from 8.00% and")
    monkeypatch.setattr(service.model_gateway_service, "run_test_prompt",
                        AsyncMock(side_effect=ProviderResponseIncomplete(partial_text=finished)))
    response, _ = await pipeline.ask(QUESTIONS["dupont"])
    assert response.answer is not None and response.answer.completeness == "partial"


# 6. No raw tool-call syntax reaches the user.
async def test_tool_calls_written_as_text_never_reach_the_user(pipeline):
    pipeline.agent.side_effect = None
    pipeline.agent.return_value = AgentOutcome(text=(
        "| Obligation | Allocated |\n|---|---|\n"
        '| Support | $18,000【calculate: expression="180000 * 20000 / 200000", label="Allocated price"}】 |\n'
        '| Maintenance | $54,000【calculate: expression="180000 * 60000 / 200000", label="Maintenance"} |'))
    response, _ = await pipeline.ask(QUESTIONS["nexus"])
    text = response.answer.text if response.answer else ""
    assert "【" not in text and "calculate:" not in text and "expression=" not in text
