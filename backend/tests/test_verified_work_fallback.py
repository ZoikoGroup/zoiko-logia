"""When the model provider times out or fails after calculations were already
verified, Kriton returns that verified work instead of nothing.

Live verification 2026-10-16 (FX scenario analysis): every scenario was
computed with the calculator, the agent ran out of time, the exception
discarded all of it, a second model call timed out too, and after 281 s the
user got "could not compose a response". Failures here are deterministic
mocks; nothing depends on a live outage."""
import asyncio
from types import SimpleNamespace as N
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from app.domains.model_gateway.agent import AgentOutcome, run_agent
from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec
from app.orchestration import service
from app.orchestration.websearch import WebSource
from tests.test_agent_loop import _call, _reply
from tests.test_answer_status_pipeline import pipeline  # noqa: F401 — full-pipeline fixture

QUESTION = ("We expect to pay US$125,000 in 60 days. Our budget rate is £1 = US$1.25. Calculate the sterling cost "
            "at the budget rate and at £1 = US$1.20 and £1 = US$1.30, and give a scenario table.")


class _Args(BaseModel):
    expression: str = ""


def registry(*, fx_ok: bool = True) -> ToolRegistry:
    async def calculate(args):
        if "bad" in args.expression:
            return ToolResult.failure("invalid_expression", "Could not evaluate the expression.")
        value = {"125000/1.25": "100000", "125000/1.2": "104166.67", "125000/1.3": "96153.85"}[args.expression]
        return ToolResult(ok=True, content=f"{args.expression} = {value} (computed by the application, verified)")

    async def rate(args):
        if not fx_ok:
            return ToolResult.failure("provider_unavailable", "The exchange-rate service did not respond.")
        return ToolResult(ok=True, content="GBP/USD reference rate 1.3247 (ECB, 2026-10-15) [REF-1]",
                          sources=(WebSource(title="ECB GBP/USD", url="https://www.ecb.europa.eu/x",
                                             snippet="GBP/USD 1.3247 on 2026-10-15", provider="ECB", freshness="daily"),))
    reg = ToolRegistry()
    for name, handler in (("calculate", calculate), ("get_exchange_rate", rate)):
        reg.register(ToolSpec(name=name, version="1", description=name, args_model=_Args, handler=handler,
                              data_source="t", risk_level="low", timeout_seconds=1.0))
    return reg


class FailingAfter:
    """Scripted replies, then the given failure on every later model call."""

    def __init__(self, replies, failure):
        self.replies, self.failure = list(replies), failure
        self.chat = N(completions=N(create=self._create))

    async def _create(self, **kwargs):
        if self.replies:
            return self.replies.pop(0)
        raise self.failure


CALCS = [_call("calculate", {"expression": "125000/1.25"}, "c1"), _call("calculate", {"expression": "125000/1.2"}, "c2"),
         _call("calculate", {"expression": "125000/1.3"}, "c3")]


async def run(client, *, fx_ok=True):
    return await run_agent(client, model="m", system_prompt="", user_prompt=QUESTION, registry=registry(fx_ok=fx_ok),
                           granted_permissions=frozenset())


# 1. Normal path unchanged.
async def test_calculations_and_a_normal_answer():
    client = FailingAfter([_reply(tool_calls=CALCS), _reply("Budget cost £100,000; at 1.20 £104,166.67; at 1.30 £96,153.85.")],
                          RuntimeError("not reached"))
    outcome = await run(client)
    assert outcome.text.startswith("Budget cost £100,000") and outcome.incomplete_reason == ""


# 2. Calculations done, then the model times out.
async def test_a_model_timeout_after_calculations_returns_the_verified_work():
    outcome = await run(FailingAfter([_reply(tool_calls=CALCS)], asyncio.TimeoutError("Agent deadline exhausted")))
    assert "did not respond in time" in outcome.text and outcome.incomplete_reason
    for line in ("125000/1.25 = 100000", "125000/1.2 = 104166.67", "125000/1.3 = 96153.85"):
        assert line in outcome.text
    assert "| # | Working |" in outcome.text and outcome.stop_reason == "time_budget"


# 3. The provider fails (not a timeout) after calculations were verified.
async def test_a_provider_failure_after_calculations_returns_the_verified_work():
    class APIConnectionError(Exception):
        __module__ = "groq"
    outcome = await run(FailingAfter([_reply(tool_calls=CALCS)], APIConnectionError("connection reset")))
    assert "the AI model service failed" in outcome.text and outcome.stop_reason == "provider_error"


# 5. The live rate cannot be retrieved; the user's own rates are enough.
async def test_a_failed_market_rate_leaves_the_users_scenarios_and_says_nothing_was_sourced():
    calls = [*CALCS, _call("get_exchange_rate", {"expression": ""}, "c4")]
    outcome = await run(FailingAfter([_reply(tool_calls=calls)], asyncio.TimeoutError()), fx_ok=False)
    assert "125000/1.25 = 100000" in outcome.text
    assert "Retrieved data" not in outcome.text                     # no market figure is presented
    assert outcome.sources == []


async def test_a_retrieved_market_rate_keeps_its_source_and_date():
    calls = [*CALCS, _call("get_exchange_rate", {"expression": ""}, "c4")]
    outcome = await run(FailingAfter([_reply(tool_calls=calls)], asyncio.TimeoutError()))
    assert "**Retrieved data (sourced)**" in outcome.text and "2026-10-15" in outcome.text
    assert outcome.sources and outcome.sources[0].freshness == "daily"


# 6. Only some calculations are available.
async def test_only_the_calculations_that_succeeded_are_shown():
    calls = [CALCS[0], _call("calculate", {"expression": "bad"}, "c9")]
    outcome = await run(FailingAfter([_reply(tool_calls=calls)], asyncio.TimeoutError()))
    assert "125000/1.25 = 100000" in outcome.text and "bad" not in outcome.text


# 7. Nothing verified: nothing invented; the failure is raised as before.
async def test_with_no_verified_calculation_the_failure_is_not_hidden():
    with pytest.raises(asyncio.TimeoutError):
        await run(FailingAfter([_reply(tool_calls=[_call("calculate", {"expression": "bad"}, "c9")])],
                               asyncio.TimeoutError()))


async def test_a_programming_error_is_never_turned_into_an_answer():
    with pytest.raises(KeyError):
        await run(FailingAfter([_reply(tool_calls=CALCS)], KeyError("bug")))


# 8 + 4. Through the pipeline: table kept, sources distinguished, honest status, audit agrees,
# and a database timeout during retrieval does not stop it.
async def test_the_pipeline_keeps_the_verified_work_with_an_honest_status(pipeline, monkeypatch):
    monkeypatch.setattr(service, "build_source_bundle", AsyncMock(side_effect=TimeoutError("database timeout")))
    ecb = WebSource(title="ECB GBP/USD", url="https://www.ecb.europa.eu/x", snippet="GBP/USD 1.3247 on 2026-10-15",
                    provider="ECB", freshness="daily")
    text = ("The full written answer could not be completed because the AI model did not respond in time. Here is "
            "the verified work already done.\n\n**Calculations from the figures provided**\n\n| # | Working |\n| --- | --- |\n"
            "| 1 | 125000/1.25 = 100000 |\n| 2 | 125000/1.2 = 104166.67 |\n\n**Retrieved data (sourced)**\n\n"
            "- GBP/USD reference rate 1.3247 (ECB, 2026-10-15) [REF-1]\n\n"
            "Explanations and recommendations were not completed; ask again for them.")
    pipeline.answers(AgentOutcome(text=text, sources=[ecb], incomplete_reason="the AI model did not respond in time",
                                  stop_reason="time_budget",
                                  calculation_receipts=[
                                      {"calculation_id": "calc-1", "formula_version": "expression-evaluator-1.0",
                                       "expression": "125000/1.25", "result": "100000"},
                                      {"calculation_id": "calc-2", "formula_version": "expression-evaluator-1.0",
                                       "expression": "125000/1.2", "result": "104166.67"}]))
    response, audited = await pipeline.ask(QUESTION)
    assert response.outcome == "answered" and "| 1 | 125000/1.25 = 100000 |" in response.answer.text
    assert any(item.startswith("Incomplete answer: the AI model did not respond in time") for item in response.answer.limitations)
    assert response.answer.completeness == audited.completeness == "partial"
    assert [c.title for c in response.answer.citations] == ["ECB GBP/USD"]   # the market rate keeps its source
