"""Pipeline reliability (root-cause round, 23 Oct 2026). No model calls.

Classes of failure this file guards, each traced to code or audit records:
1. live-data detection: three detectors, each with its own exceptions, so
   every new phrasing broke one ("currently pays … $1.20", "value today
   (Year 0)"). Now one rule, live_data_requested, used by all three;
2. budget: each call reserves up to its request size, and failed calls keep
   their reservation, so 16,000-token requests under a 64,000 budget stopped
   multi-step answers (token_budget) without any log saying why;
3. fallback: the agent replaced explanations with bare working and recorded
   neither the failed lines nor the reason;
4. leaks: long 【…】 tags, calculator arguments written as JSON, "\\DeltaDays".
"""
import asyncio
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace as N

import pytest

from app.domains.model_gateway.agent import AgentLimits, run_agent
from app.domains.model_gateway.agent_budget import GenerationBudget
from app.domains.model_gateway.tool_registry import ToolRegistry, build_default_registry
from app.orchestration.agent_plan import plan_request
from app.orchestration.answer_formatting import latex_to_plain
from app.orchestration.calculation_service import live_data_requested, needs_lookup
from app.orchestration.fx_profit import latest_fx_requested
from app.orchestration.verification_service import normalize_citations, requires_authoritative_evidence
from tests.answer_key import grade
from tests.test_agent_loop import ScriptedClient, _reply

REVIEW = json.loads((Path(__file__).parent / "fixtures" / "review_questions_20261022.json").read_text())
Q = REVIEW["questions"]


# ── 1. One live-data rule ─────────────────────────────────────────────────────

LIVE = [
    "What is the current EUR/USD exchange rate?",
    "Convert $5,000 to EUR at today's rate.",
    "Convert 10,000 INR into USD at the latest rate",
    "What is Apple's share price today and its P/E if EPS is 6.1?",
    "What is the current corporate tax rate in the UK?",
    "Show the latest CPI for India",
    "Calculate interest at the current repo rate on ₹10 lakh.",
    "What's the prevailing base rate?",
    "What is the gold price now?",
    "Which stocks are currently trading above their 52-week high?",
    "Which stocks are currently trading above $100?",
]
SUPPLIED = [
    "A high-growth technology company currently pays an annual dividend of $1.20 per share.",
    "Discount all intermediate cash flows and the terminal value back to evaluate the intrinsic current value "
    "per share today (Year 0).",
    "The current spot rate is 5.00 BRL per $1 USD.",
    "TargetCo's current TTM (Trailing Twelve Months) EBITDA is $2,000,000.",
    "Use the supplied rate without checking the current repo rate.",
    "The bonds are currently trading at $950 per bond.",
    "Our current interest rate is 7%; calculate annual interest on $500,000.",
    "Our costs this year: rent £36,000, salaries £210,000.",
    "My sales in the last 12 months were £87,000 and this month I expect £6,000 more.",
    "The comparative financials for Vertex Global present the following details:",
    "Design two procedures the team must now perform.",
]


@pytest.mark.parametrize("text", LIVE)
def test_a_time_word_on_a_fact_not_supplied_asks_for_live_data(text):
    assert live_data_requested(text)


@pytest.mark.parametrize("text", SUPPLIED)
def test_a_time_word_on_a_supplied_figure_or_a_computed_target_does_not(text):
    assert not live_data_requested(text)


def test_the_three_consumers_share_the_decision():
    dividend = Q["dividend"]
    assert not needs_lookup(dividend) and not requires_authoritative_evidence(dividend, dividend)
    assert "get_market_data" not in plan_request(dividend).tools
    assert not latest_fx_requested(Q["brazil"]) and latest_fx_requested("Convert 10,000 INR into USD at the latest rate")


@pytest.mark.parametrize("name", ["dividend", "hedge", "tdr", "level3", "inventory_count", "brazil"])
def test_the_retest_scenarios_need_no_live_data(name):
    question = Q[name]
    tools = plan_request(question).tools
    assert not requires_authoritative_evidence(question, question)
    assert not {"get_market_data", "get_economic_indicator", "get_exchange_rate"} & set(tools)
    assert "calculate" in tools


def test_a_rate_to_compute_is_not_an_indicator_to_fetch():
    assert "get_economic_indicator" not in plan_request(
        "Calculate the new effective interest rate for subsequent periods on the restructured note of $1,500,000 "
        "at 4%.").tools
    assert "get_economic_indicator" in plan_request("Show US interest rate trend since 2020").tools


# ── 2. Budget: limits that fit, and reservations that can be explained ────────

def test_a_failed_call_logs_the_reservation_it_keeps(caplog):
    class Failing:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    raise RuntimeError("tool_use_failed")

    budget = GenerationBudget(max_total_tokens=64_000, max_request_tokens=8_000)
    caplog.set_level(logging.INFO, logger="app.domains.model_gateway.agent_budget")
    with pytest.raises(RuntimeError):
        asyncio.run(budget.create(Failing, seconds=5, model="m", messages=[{"role": "user", "content": "hi"}]))
    assert budget.estimated_tokens > 0
    assert any("reserved tokens kept" in record.getMessage() for record in caplog.records)


async def test_a_run_budget_too_small_for_its_request_size_is_reported(monkeypatch, caplog):
    from app.core import config
    from app.domains.model_gateway.execution import request_execution_scope
    monkeypatch.setattr(config, "get_settings", lambda: N(
        AGENT_MAX_TOKENS=64_000, AGENT_MAX_COMPLETION_TOKENS=8_192, AGENT_MAX_REQUEST_TOKENS=16_000,
        AGENT_MAX_COST_USD=0.0, MODEL_PRICE_PER_MILLION_TOKENS=0.0, MODEL_REQUEST_MAX_CALLS=20,
        ASK_KRITON_TIMEOUT_SECONDS=60))
    caplog.set_level(logging.WARNING, logger="app.domains.model_gateway.execution")

    @request_execution_scope
    async def ask():
        return "ok"

    assert await ask() == "ok"
    assert any("fewer than 6 requests" in record.getMessage() for record in caplog.records)


def test_the_batched_calculator_is_off_by_default_and_available_by_setting():
    single = build_default_registry().get("calculate").args_model.model_json_schema()["properties"]
    batched = build_default_registry(batch_calculations=True).get("calculate").args_model.model_json_schema()
    assert "expressions" not in single and "expressions" in batched["properties"]
    from app.core.config import Settings
    assert Settings.model_fields["AGENT_BATCH_CALCULATIONS"].default is False


# ── 3. Fallback: failed lines and the reason are recorded ─────────────────────

QUESTION = "Fixed costs are £780,000 and the contribution margin ratio is 55%. Explain break-even revenue."


async def _agent(text):
    client = ScriptedClient([_reply(text)] * 3)
    return await run_agent(client, model="m", system_prompt="sys", user_prompt=QUESTION, registry=ToolRegistry(),
                           granted_permissions=frozenset(), limits=AgentLimits(), stated_facts=QUESTION)


async def test_a_removed_line_is_recorded_with_its_failure():
    outcome = await _agent("Break-even revenue is where contribution covers fixed costs.\n"
                           "Break-even revenue = £780,000 ÷ 0.55 = £1,560,000.\n"
                           "Above it every pound of revenue adds 55p of contribution.")
    assert outcome.validation["fallback"] == "removed_statements"
    assert any("1560000" in line for line in outcome.validation["failed_lines"])


async def test_a_fallback_to_working_records_why():
    outcome = await _agent("Break-even revenue = £780,000 ÷ 0.55 = £1,560,000.")
    assert outcome.validation["fallback"] == "verified_working"
    assert outcome.validation["reason"] == "nothing substantive left"


async def test_the_validation_record_is_audited(monkeypatch):
    from app.orchestration import audit_events
    seen = {}

    async def emit(db, name, *args, **kwargs):
        seen[name] = args[-1] if args else kwargs

    monkeypatch.setattr(audit_events, "_emit", emit)
    await audit_events.audit_agent_completed(
        None, query_id="q", correlation_id="c", tenant_id="t", audit_chain_id="a", actor_id="u", steps=3,
        stop_reason="final_answer", tool_call_count=1, fell_back=False,
        validation={"fallback": "removed_statements", "failed_lines": ["x"]})
    assert seen["agent_completed"]["validation"]["fallback"] == "removed_statements"


# ── 4. Leaks ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("leaked, clean", [
    ("Ratio = $900,000 / $750,000 = 1.20 (120 %)【calculate Misstatement to materiality ratio】.",
     "Ratio = $900,000 / $750,000 = 1.20 (120 %)."),
    ('Calculation\n\n{\n "expression": "120000 + 45000",\n "label": "Total inventory to remove"\n}\nResult: $165,000.',
     "Calculation\n\n\nResult: $165,000."),
    ('```json\n{"expression": "85000 + 120000 + 45000", "label": "x"}\n```\nResult: $250,000.', "\nResult: $250,000."),
])
def test_tool_output_never_reaches_the_reader(leaked, clean):
    assert normalize_citations(leaked, set()) == clean


@pytest.mark.parametrize("prose", [
    'Use the {"key": "value"} format; the expression "a+b" stays.',
    "Interest = 10,00,000 × 6.5% × 0.75 = 48,750.",
])
def test_ordinary_text_is_kept(prose):
    assert normalize_citations(prose, set()) == prose


@pytest.mark.parametrize("latex, plain", [
    (r"\DeltaDays = 30.42 - 25", "ΔDays = 30.42 - 25"),
    (r"\Delta t and \tau x", "Δ t and τ x"),
])
def test_a_greek_letter_before_a_word_is_converted(latex, plain):
    assert latex_to_plain(latex) == plain


# ── Accounting answer keys (awaiting accountant review) ───────────────────────

SAVED_WRONG = {
    "inventory_count": "Lot X: Include in the client's year-end inventory provided the bill-and-hold criteria are "
                       "satisfied.\nLot Y: Exclude from the client's inventory on 31 Dec 2026.\nTotal $165,000.",
    "level3": "Known vs. projected misstatement: Known misstatement. Under PCAOB guidance (AS 3105) the auditor must "
              "inform the Audit Committee. Misstatement $900,000.",
    "hedge": "Derivative fair value loss: (79-75)*100000 = 400000",
}


@pytest.mark.parametrize("name", list(SAVED_WRONG))
def test_the_grader_flags_the_saved_answers_errors(name):
    result = grade(SAVED_WRONG[name], name)
    assert result.contradictions and not result.passed


def test_a_correct_level3_answer_passes():
    answer = ("Approaches: test management's process; develop an independent expectation; evaluate events "
              "occurring after the measurement date (subsequent events). Misstatement $900,000, which exceeds "
              "$750,000 materiality. It is a judgmental misstatement, communicated to the audit committee under "
              "AS 1301.")
    assert grade(answer, "level3").passed


def test_every_key_with_a_judgement_is_marked_for_accountant_review():
    status = REVIEW["review_status"]
    for name in ("hedge", "level3", "inventory_count", "brazil", "pension", "segments", "tdr"):
        assert status[name]["status"] == "awaiting accountant review"
        assert re.search(r"\b(?:ASC|AS|PCAOB|PPP)\b", status[name]["assumption"])
