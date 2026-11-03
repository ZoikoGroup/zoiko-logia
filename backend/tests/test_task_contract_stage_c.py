"""Task Contract, Stage C: two decisions read from the contract instead of
the raw message, and one shared question splitter.

- Financial statements are requested only when a part asks for them: "3.
  Explain how the single lease cost is presented in the income statement"
  added draft-statement notes ("Status: Draft…", "comparatives not
  provided") to a lease answer (defect class 3, 29 Oct 2026).
- The VAT inputs are asked for only when a VAT amount is to be produced: "What
  is the GST rate on job work services after the 2025 changes?" was asked
  whether its figures include VAT (defect class 1).
- Numbered tasks ("1. Calculate … 2. Prepare … 3. Explain …") are separate
  parts for the contract and for the per-question search alike.
No model, database or network.
"""
import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration.task_contract import build_task_contract
from app.orchestration.websearch import sub_questions, task_items
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

HARBOR = ("Harbor Freight Logistics Inc. leases a warehouse under a 4-year lease starting January 1, 2026. Annual "
          "payments of $50,000 are due at the end of each year. The company's incremental borrowing rate is 6%. The "
          "lease is an operating lease under ASC 842.\n\nTask for the Bot:\n1. Calculate the initial lease liability "
          "and right-of-use asset.\n2. Prepare the journal entry at commencement.\n3. Explain how the single lease "
          "cost is presented in the income statement for an operating lease.")


# Statements ---------------------------------------------------------------

def test_a_presentation_question_does_not_request_statements():
    assert not build_task_contract(HARBOR).output_constraints.statements_requested


@pytest.mark.parametrize("question", [
    "Prepare the income statement for the year from the trial balance below.",
    "Income statement for FY2025 from these figures: revenue £500,000, costs £300,000.",
    "Draft the statement of financial position at 31 March 2026 from these balances: cash £10,000, equity £10,000.",
])
def test_a_request_for_statements_still_requests_them(question):
    assert build_task_contract(question).output_constraints.statements_requested


async def test_the_lease_answer_carries_no_draft_statement_notes(pipeline):
    pipeline.answers(AgentOutcome(text="The lease liability is $173,255.28. Dr Right-of-use asset, Cr Lease liability. "
                                       "An operating lease shows a single straight-line lease cost."))
    response, _ = await pipeline.ask(HARBOR)
    notes = " ".join(response.answer.limitations if response.answer else [])
    assert "Status: Draft" not in notes and "comparative" not in notes.lower()


# VAT amount ---------------------------------------------------------------

@pytest.mark.parametrize("question", [
    "What is the GST rate on job work services for hides, skins and leather after the 2025 changes?",
    "What is the GST rate on renewable energy devices after the 2025 changes?",
])
async def test_a_rate_question_is_not_asked_for_vat_inputs(pipeline, question):
    assert not build_task_contract(question).output_constraints.vat_amount_requested
    pipeline.answers(AgentOutcome(text="Model answer placeholder."))
    response, _ = await pipeline.ask(question)
    assert not (response.next_action and (response.next_action.message or "").startswith("To work out the VAT I need"))


@pytest.mark.parametrize("question", [
    "UK company, VAT at 20%, figures exclude VAT: sales £100,000, purchases £50,000. Calculate VAT payable.",
    "What is 18% GST on ₹50,000?",
    "UK business: sales £100,000. How much VAT do I owe?",
])
def test_a_vat_amount_still_has_its_inputs_checked(question):
    contract = build_task_contract(question)
    assert contract.output_constraints.vat_amount_requested and contract.missing_inputs


# Shared splitter ----------------------------------------------------------

def test_numbered_tasks_are_separate_parts_for_search_and_contract():
    tasks = "1. Calculate the initial lease liability.\n2. Prepare the journal entry.\n3. Explain the presentation."
    assert task_items(tasks) == ["1. Calculate the initial lease liability.", "2. Prepare the journal entry.",
                                 "3. Explain the presentation."]
    assert len(sub_questions(tasks)) == 3
    assert len(build_task_contract(HARBOR).parts) == 3


def test_a_numbered_list_of_facts_is_not_split():
    facts = ("1. Capitalization vs. Revenue Expenditure: Apex booked ₹45 Lakhs as revenue expense.\n"
             "2. The company claimed ₹22 Lakhs of input tax credit on a passenger vehicle.")
    assert task_items(facts) == []
