"""Kriton offers the chart that fits an answer's figures and draws it only if
the user accepts (chart_offer.py). No model calls."""
import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration.chart_offer import chart_declined, chart_from_answer, offer_chart
from app.orchestration.schemas import ConversationMessage
from app.orchestration.supplied_charts import build_supplied_chart
from tests.test_answer_status_pipeline import pipeline  # noqa: F401  (fixture)

# Tables as the 23 Oct 2026 live answers wrote them.
DIVIDEND = """**1. Projected dividends per share**

| Year | Growth applied | Exact dividend ( $ ) |
|---|---|---|
| 0 (today) | – | 1.20 |
| 1 | 20 % | 1.44 = 1.20 × 1.20 |
| 2 | 20 % | 1.728 = 1.44 × 1.20 |
| 3 | 20 % | 2.0736 = 1.728 × 1.20 |
| 4 | 12 % | 2.322432 = 2.0736 × 1.12 |
| 5 | 5 % (maturity) | 2.438554 = 2.322432 × 1.05 |
"""
BRAZIL = """| Year | Cash flow (BRL) | Exchange rate (BRL / USD) | Cash flow (USD) |
|---|---|---|---|
| 1 | 3,500,000 | 5.170732 | 676,886.754138 → 676,886.75 |
| 2 | 3,500,000 | 5.347293 | 654,536.790858 → 654,536.79 |
| 3 | 3,500,000 | 5.529884 | 632,924.668944 → 632,924.67 |
| 4 | 3,500,000 | 5.718709 | 612,026.245784 → 612,026.25 |
"""
CCC = """| Metric | Formula | Result (days) |
|---|---|---|
| Days Inventory Outstanding (DIO) | (Avg Inv ÷ COGS) × 365 | 30.42 |
| Days Sales Outstanding (DSO) | (Avg AR ÷ Sales) × 365 | 36.50 |
| Days Payable Outstanding (DPO) | (Avg AP ÷ COGS) × 365 | 26.07 |
"""
BUDGET = """| Department | Budget ($) | Actual ($) |
|---|---|---|
| Sales | 120,000 | 135,000 |
| Marketing | 40,000 | 38,500 |
| Operations | 90,000 | 97,200 |
"""
ALLOCATION = """| Asset | Impairment allocated ($) |
|---|---|
| Building | 600,000 |
| Machinery | 300,000 |
| Office equipment | 50,000 |
| **Total** | **950,000** |
"""
JOURNAL = """| Date | Account | Debit | Credit |
|---|---|---|---|
| 31 Dec 2026 | Derivative – Fair Value | $400 000 | – |
| 31 Dec 2026 | OCI – Cash-flow hedge reserve | – | $400 000 |
"""
RULES = """| Item | Treatment | Rationale |
|---|---|---|
| Lot X | Exclude | Bill-and-hold criteria met |
| Lot Y | Include | FOB destination, arrived |
"""


# ── Which chart fits which data ───────────────────────────────────────────────

def test_a_series_over_time_is_offered_as_a_line():
    offer = offer_chart(DIVIDEND)
    assert offer.chart_type == "line" and offer.question == "Show this as a line chart."
    assert offer.chart["categories"] == ["0 (today)", "1", "2", "3", "4", "5"]
    # The worked cell's result, not its operands: 1.44 from "1.44 = 1.20 × 1.20".
    assert offer.chart["series"][0]["data"] == [1.2, 1.44, 1.728, 2.0736, 2.322432, 2.438554]


def test_the_result_column_is_charted_and_rows_numbered_by_period_are_labelled():
    offer = offer_chart(BRAZIL)
    assert offer.chart_type == "line" and offer.chart["categories"] == ["Year 1", "Year 2", "Year 3", "Year 4"]
    # Rounded result after "→", in US dollars; not the BRL amount or the rate.
    assert offer.chart["series"] == [{"name": "Cash flow (USD)", "data": [676886.75, 654536.79, 632924.67, 612026.25]}]


def test_separate_items_are_offered_as_bars():
    offer = offer_chart(CCC)
    assert offer.chart_type == "bar" and offer.chart["series"][0]["data"] == [30.42, 36.5, 26.07]


def test_two_measures_of_the_same_items_are_grouped_bars():
    offer = offer_chart(BUDGET)
    assert offer.chart_type == "bar" and [s["name"] for s in offer.chart["series"]] == ["Budget ($)", "Actual ($)"]


def test_parts_of_a_stated_total_are_offered_as_a_pie():
    offer = offer_chart(ALLOCATION)
    assert offer.chart_type == "pie"
    assert [slice_["name"] for slice_ in offer.chart["data"]] == ["Building", "Machinery", "Office equipment"]


def test_a_few_periods_are_bars_not_a_line():
    table = "| Year | Revenue ($) |\n|---|---|\n| 2025 | 4,000,000 |\n| 2026 | 5,200,000 |\n"
    assert offer_chart(table).chart_type == "bar"


@pytest.mark.parametrize("text", [
    JOURNAL, RULES,
    "The NPV is $49,839, so the project should be accepted.",
    "| Item | Amount |\n|---|---|\n| Revenue | $100,000 |\n",           # one row is not a chart
    "| Item | Amount |\n|---|---|\n| UK sales | £100,000 |\n| US sales | $90,000 |\n",  # mixed currencies
    "| Item | Note |\n|---|---|\n| A | see above |\n| B | n/a |\n",
])
def test_nothing_is_offered_for_what_a_chart_cannot_show(text):
    assert offer_chart(text) is None


@pytest.mark.parametrize("question, declined", [
    ("Explain the dividend model. No chart please.", True),
    ("Give me the figures in a table only.", True),
    ("Don't include any graphs.", True),
    ("Explain how ineffectiveness is treated if the correlation was not perfect.", False),
    ("Calculate the NPV.", False),
])
def test_a_request_for_no_chart_is_respected_and_a_condition_is_not_a_refusal(question, declined):
    assert chart_declined(question) is declined


# ── Accepting the offer draws exactly the offered chart ───────────────────────

@pytest.mark.parametrize("table", [DIVIDEND, BRAZIL, CCC, BUDGET])
def test_accepting_draws_the_offered_chart_from_the_previous_answer(table):
    offer = offer_chart(table)
    history = [ConversationMessage(role="user", content="Calculate it."),
               ConversationMessage(role="assistant", content="Here is the working.\n\n" + table)]
    drawn = build_supplied_chart(offer.question, history)
    assert drawn is not None and drawn.chart is not None
    assert drawn.chart["type"] == offer.chart_type
    assert drawn.chart["categories"] == offer.chart["categories"]
    assert drawn.chart["series"] == offer.chart["series"]


def test_accepting_a_pie_offer_draws_the_pie():
    offer = offer_chart(ALLOCATION)
    history = [ConversationMessage(role="assistant", content=ALLOCATION)]
    drawn = build_supplied_chart(offer.question, history)
    assert drawn.chart["type"] == "pie"
    assert [(s["name"], s["value"]) for s in drawn.chart["data"]] == [
        (s["name"], s["value"]) for s in offer.chart["data"]]


def test_the_same_figures_can_be_asked_for_as_another_type():
    history = [ConversationMessage(role="assistant", content=BRAZIL)]
    drawn = build_supplied_chart("Show this as a bar chart.", history)
    assert drawn.chart["type"] == "bar" and drawn.chart["series"][0]["data"][0] == 676886.75


# ── Through the pipeline ──────────────────────────────────────────────────────

QUESTION = ("A company currently pays a dividend of $1.20 per share, growing 20% for 3 years, 12% in Year 4 and "
            "5% thereafter. Ke is 9%. Calculate the dividends for Years 1 to 5.")


async def test_an_answer_with_a_chartable_table_carries_the_offer(pipeline):
    pipeline.answers(AgentOutcome(text=DIVIDEND))
    response, _ = await pipeline.ask(QUESTION)
    assert response.outcome == "answered" and response.visualization is None
    assert response.chart_offer is not None and response.chart_offer.chart_type == "line"
    assert response.chart_offer.question == "Show this as a line chart."
    assert "```chart" not in response.answer.text   # offered, not drawn


async def test_no_offer_when_the_user_declined_charts(pipeline):
    pipeline.answers(AgentOutcome(text=DIVIDEND))
    response, _ = await pipeline.ask(QUESTION + " Text only, no chart.")
    assert response.chart_offer is None


async def test_no_offer_for_an_answer_without_a_dataset(pipeline):
    pipeline.answers(AgentOutcome(text="The intrinsic value is $49.21 per share."))
    response, _ = await pipeline.ask(QUESTION)
    assert response.chart_offer is None


async def test_accepting_draws_the_chart_without_a_model_call(pipeline):
    history = [ConversationMessage(role="user", content=QUESTION),
               ConversationMessage(role="assistant", content=DIVIDEND)]
    response, _ = await pipeline.ask("Show this as a line chart.", history=history)
    assert response.outcome == "answered"
    pipeline.agent.assert_not_awaited()
    drawn = response.visualization
    assert drawn is not None or "```chart" in (response.answer.text or "")
    assert response.chart_offer is None   # a chart was drawn: nothing left to offer


def test_the_chosen_table_is_the_largest_one():
    two_tables = CCC + "\n\n" + DIVIDEND
    kind, chart, _reason = chart_from_answer(two_tables)
    assert kind == "line" and len(chart["categories"]) == 6
