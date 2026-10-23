"""v10 offline fixes (23 Oct 2026). No model calls.

1. A wrong result in a step with a power ("1.728/(1.09**2) = 1.60") was never
   checked: every step containing ** or ^ was skipped.
2. A later reference to a current price the question already gave ("based on
   the current underlying stock price" after "the current market price … is
   $48") was read as a live lookup: strict sourcing and a market-data fetch.
3. The chart reader did not read thin-space grouping ("400 000" with U+2009).
4. Repeated-search rule: a search with fewer words is broader and still runs.
"""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.orchestration.agent_plan import plan_request
from app.orchestration.calculation_service import (
    live_data_requested, needs_lookup, supplied_fact_kinds, validate_answer_calculations,
)
from app.orchestration.chart_offer import _value
from app.orchestration.verification_service import requires_authoritative_evidence
from tests.test_retest_fixes_oct23 import HEDGE_1, _call, _reply, _run, _search_registry

QUESTIONS = json.loads((Path(__file__).parent / "fixtures" / "review_questions_20261022.json").read_text())["questions"]


# ── 1. Steps with powers are checked ──────────────────────────────────────────

@pytest.mark.parametrize("wrong", [
    "PV2 = 1.728/(1.09**2) = 1.60",
    "(150,000 ÷ 100,000)^(1/3) − 1 = 0.25",
    "FV = 10,000 × (1 + 0.05)^2 = 12,000",
    "Discount factor = 1 / (1.1 ** 4) = 0.75",
])
def test_a_wrong_result_with_a_power_is_caught(wrong):
    assert validate_answer_calculations(wrong)


@pytest.mark.parametrize("right", [
    "PV2 = 1.728/(1.09**2) = 1.454423",
    "(150,000 ÷ 100,000)^(1/3) − 1 = 0.144714",
    "FV = 10,000 × (1 + 0.05)^2 = 11,025",
    "PV = 60000/(1+0.08) + 60000/(1+0.08)**2 + (60000+1500000)/(1+0.08)**3 = 1,345,374.18",
    "Discount factor = 1 / (1.1 ** 4) = 0.683013",
])
def test_a_correct_result_with_a_power_passes(right):
    assert validate_answer_calculations(right) == []


@pytest.mark.parametrize("formula", [
    "Revenue × (1.05)^2 = 1,102,500",                 # an unknown in the step
    "CAGR = (end/start)^(1/n) - 1 = 12%",             # words, not arithmetic
])
def test_a_step_with_words_is_still_not_judged(formula):
    assert validate_answer_calculations(formula) == []


def test_a_wrong_last_step_after_a_power_is_still_caught():
    assert validate_answer_calculations("FV = 10,000 × (1 + 0.05)^2 = 10,000 × 1.1025 = 10,025")


# ── 2. A later reference to a supplied current price is that price ────────────

def test_the_convertible_question_needs_no_market_lookup_or_strict_sourcing():
    question = QUESTIONS["convertible"]
    assert plan_request(question).tools == ("calculate",)
    assert not needs_lookup(question) and not requires_authoritative_evidence(question, question)


def test_what_the_question_supplies_is_recorded_by_kind():
    assert supplied_fact_kinds("The current market price of the stock is $48 per share.") == {"price"}
    assert supplied_fact_kinds("The current spot rate is 5.00 BRL per $1.") == {"rate"}
    assert supplied_fact_kinds("What is the current price?") == set()


@pytest.mark.parametrize("text, live", [
    ("The current spot rate is 1.35. Translate the balance at the current spot rate.", False),
    ("The current price is $48. Compute parity at the current stock price.", False),
    # A different kind of figure, or nothing supplied: still live.
    ("The current price is $48. What is the current market cap?", True),
    ("The current repo rate is 6.5%. Is the current inflation level above target?", True),
    ("What is the current EUR/USD exchange rate?", True),
    ("Compute parity at the current stock price.", True),
])
def test_a_reference_back_is_supplied_and_anything_else_is_live(text, live):
    assert live_data_requested(text) is live


@pytest.mark.parametrize("question", [
    "What is Apple's share price today and its P/E if EPS is 6.1?",
    "Microsoft market cap vs Google",
    "The stock price is $48 and EPS is $4. Compare it with the current share price of Microsoft.",
])
def test_real_market_lookups_still_plan_the_fetch(question):
    assert "get_market_data" in plan_request(question).tools


# ── 3. Thin-space grouping in the chart reader ────────────────────────────────

@pytest.mark.parametrize("cell, value", [
    ("$400 000", Decimal("400000")),
    ("400 000", Decimal("400000")),
    ("7 900 000", Decimal("7900000")),
    ("400 000", Decimal("400000")),
    ("1,234.5", Decimal("1234.5")),
])
def test_every_grouping_space_is_read(cell, value):
    assert _value(cell) == value


# ── 4. A broader search after an empty one still runs ─────────────────────────

async def test_a_search_with_fewer_words_after_an_empty_one_runs():
    executed = []
    broader = "ASC 815 cash flow hedge"
    # Nothing is found for either query here: the point is that the broader
    # one is sent at all, not what it returns.
    _client, outcome = await _run([
        _reply(tool_calls=[_call("search_web", {"query": HEDGE_1}, "c1")]),
        _reply(tool_calls=[_call("search_web", {"query": broader}, "c2")]),
        _reply("Done."),
    ], _search_registry(executed))
    assert [query for _, query in executed] == [HEDGE_1, broader]
    assert [r.error_code for r in outcome.tool_calls] == ["no_data", "no_data"]


async def test_the_same_search_reworded_is_skipped_in_the_loop():
    executed = []
    _client, outcome = await _run([
        _reply(tool_calls=[_call("search_web", {"query": HEDGE_1}, "c1")]),
        _reply(tool_calls=[_call("search_web", {"query": "journal entries: forecasted purchases, cash flow hedges, "
                                                          "ASC 815"}, "c2")]),
        _reply("Done."),
    ], _search_registry(executed))
    assert len(executed) == 1 and [r.error_code for r in outcome.tool_calls] == ["no_data", "repeat_search"]
