"""Defects found in the 27 Oct 2026 evening re-test on 3000 (one chat, 14 questions).

Q6: after a clarification, a complete new question carried the previous
request (its VAT figures). Q7: "gross profit and margin" gave the profit only.
Q11: "discount rate 6%" in a lease statement fetched a year of UK Bank Rate.
(Q8 was found not to be a defect; see below.) Q13: "selling
at £25" was not read. Q14: the lease figures from an earlier turn were
removed as unverified although the prompt carried them. No model calls.
"""
import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import bank_of_england
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.schemas import ConversationMessage as M
from app.orchestration.service import _with_previous_context
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

VAT_QUESTION = ("UK company, VAT at 20%, figures exclude VAT: cost of sales £40,000, sales £100,000, "
                "purchases £50,000. Calculate VAT payable.")


# Q6 ---------------------------------------------------------------------------

def test_a_new_task_after_a_clarification_does_not_carry_the_previous_request():
    journal = ("Record the journal entry: Dr Right-of-use asset £133,650.60, Cr Lease liability £126,370.91. "
               "Check if it balances.")
    assert _with_previous_context(journal, VAT_QUESTION, clarification_cycle=1) == journal


@pytest.mark.parametrize("reply", ["Excluding VAT.", "All standard-rated.", "UK, year ending 2025.",
                                   "Sales are £100,000 and purchases £50,000.",
                                   "Calculate it with sales of £100,000 and purchases of £50,000."])
def test_a_reply_to_the_clarification_keeps_the_previous_request(reply):
    assert "Previous user request for context" in _with_previous_context(reply, VAT_QUESTION, clarification_cycle=1)


# Q7 ---------------------------------------------------------------------------

@pytest.mark.parametrize("question", [
    "Under IFRS 15, revenue £800,000 and cost of sales £500,000. What is the gross profit and margin?",
    "Revenue £800,000, cost of sales £500,000. Calculate gross profit and the margin.",
])
def test_gross_profit_and_margin_gives_both(question):
    outputs = {o.name: o.display_value for o in calculate_from_query(question).outputs}
    assert outputs["gross_profit"] == "£300,000.00" and outputs["gross_margin"] == "37.50%"


def test_gross_profit_alone_is_unchanged():
    outputs = {o.name for o in calculate_from_query("Revenue £800,000, cost of sales £500,000. "
                                                    "Calculate gross profit.").outputs}
    assert outputs == {"gross_profit"}


# Q8: not a defect. Bullets made only of instructions ("Verify …, Review …,
# Confirm …") read as a request, like a numbered task list; Kriton's how-to
# answer was reasonable. Pasted statements are still clarified
# (test_pasted_statement_detection_oct27.py).


# Q11 --------------------------------------------------------------------------

def test_a_supplied_discount_rate_does_not_fetch_bank_rate():
    lease = "We lease a warehouse: annual payments of £30,000 in arrears, discount rate 6%, lease term 4 years."
    assert bank_of_england._definition_for_query(lease) is None


@pytest.mark.parametrize("question", ["What is the current UK Bank Rate?", "Is the UK Bank Rate 4%?",
                                      "How has the UK interest rate changed over the last five years?"])
def test_asking_about_the_official_rate_still_fetches_it(question):
    assert bank_of_england._definition_for_query(question) == "IUDBEDR"


# Q13 --------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", ["selling at £25", "sold at £25", "sells at £25", "selling for £25"])
def test_break_even_reads_selling_at(phrase):
    result = calculate_from_query(f"What is the break-even point for a product {phrase} with variable cost £15 "
                                  f"and fixed costs £50,000?")
    assert result.status == "success"
    assert {o.name: o.value for o in result.outputs}["break_even_units"] == 5000


# Q14 --------------------------------------------------------------------------

async def test_figures_from_the_earlier_lease_turn_reach_the_figure_check(pipeline, monkeypatch):
    from app.orchestration import service
    from app.orchestration.websearch import WebSource
    history = [
        M(role="user", content="We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025."),
        M(role="assistant", content="Noted."),
        M(role="user", content="We lease a warehouse: annual payments of £30,000 in arrears, discount rate 6%, lease term 4 years."),
        M(role="assistant", content="Noted."),
        # As in the re-test chat: "that lease" links to this latest lease
        # message, so the £30,000 reaches the model only as an essential.
        M(role="user", content="the lease term is 5 years, not 4."),
        M(role="assistant", content="What would you like me to do with this text?"),
        M(role="user", content="Separately: break-even for a product selling at £25 with variable cost £15 and fixed costs £50,000?"),
        M(role="assistant", content="5,000 units."),
    ]
    seen = []
    real = service.unreconciled_figures

    def record(text, evidence, *args, **kwargs):
        result = real(text, evidence, *args, **kwargs)
        seen.append(result)
        return result

    monkeypatch.setattr(service, "unreconciled_figures", record)
    source = WebSource(title="IFRS 16 Leases", url="https://www.ifrs.org/ifrs16", snippet="A lessee measures the lease liability at the present value of the lease payments.")
    pipeline.answers(AgentOutcome(text="The lease liability is the present value of the lease payments [REF-1]. "
                                       "The annual payment is £30,000.", sources=[source]))
    # A follow-up the model answers (the lease calculator now computes "Now
    # calculate the lease liability for that lease" without a model answer).
    await pipeline.ask("Now explain how that lease is presented, using its figures.", history=history)
    assert seen, "the figure check did not run"
    assert all("£30,000" not in removed for removed in seen)
