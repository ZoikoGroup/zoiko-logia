"""Task Contract, Stage B: case scope from the contract (defect class 4).

A pasted Brightwater audit case after a Northwind case was resolved as its
follow-up ("the company breached a loan covenant" read as pointing back), the
model was given Northwind's facts and the answer cited "the absence of a
covenant waiver from the bank", a Northwind fact (29 Oct 2026). A message
that sets out a case of its own now starts a new case; anything else keeps
the conversation's scope. No model, database or network.
"""
from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration.schemas import ConversationMessage as M
from app.orchestration.task_contract import build_task_contract, starts_new_case
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

NORTHWIND = ("Northwind Retail Ltd operates 25 stores in the UK and reports under FRS 102. Its bank loan of £15 million "
             "has a covenant requiring net debt to EBITDA of no more than 3.0x; the year-end ratio was 3.4x. The bank "
             "has not yet issued a waiver. The auditor's report is due on 30 June 2026.")
BRIGHTWATER = ("Brightwater Hotels plc – Audit Planning\n\nBrightwater Hotels plc owns 12 hotels and reports under IFRS. "
               "Occupancy fell from 78% to 54% in the year ended 31 December 2026, and the company breached a loan "
               "covenant in November 2026.\n\nRequired:\n1. Identify the going concern indicators and explain the "
               "auditor's responsibilities under ISA (UK) 570.")
CLOUD = ("CloudLedger Ltd – Quarter-End Review\n\nThe Background:\n\nOn 1 July 2026 CloudLedger signed a £120,000 contract "
         "for a licence (sold alone for £100,000) and 12 months of support (sold alone for £50,000 a year).\n\n"
         "Questions to Answer:\n\n• Q1: Allocate the £120,000 transaction price.")


def test_a_pasted_case_after_another_starts_a_new_case():
    assert starts_new_case(BRIGHTWATER, [M(role="user", content=NORTHWIND)])
    contract = build_task_contract(BRIGHTWATER, history=[M(role="user", content=NORTHWIND)])
    assert contract.case.new_case and contract.case.case_id == "current" and contract.case.relevant_turns == []
    assert not [fact for fact in contract.facts if fact.source == "history"]


async def test_the_new_case_reaches_the_model_without_the_earlier_cases_facts(pipeline):
    pipeline.answers(AgentOutcome(text="Going concern indicators: falling occupancy and the covenant breach."))
    response, _ = await pipeline.ask(BRIGHTWATER, history=[M(role="user", content=NORTHWIND)])
    prompt = str(pipeline.agent.await_args)
    assert response.outcome == "answered"
    assert "Northwind" not in prompt and "£15 million" not in prompt and "waiver" not in prompt


def test_a_case_that_points_back_keeps_the_conversation():
    pointing = BRIGHTWATER.replace("Brightwater Hotels plc owns", "Using the same company as above, Brightwater Hotels plc owns")
    assert not starts_new_case(pointing, [M(role="user", content=NORTHWIND)])


def test_a_follow_up_question_is_not_a_new_case():
    history = [M(role="user", content=CLOUD)]
    assert not starts_new_case("Now what if the support contract was for 24 months instead of 12?", history)
    contract = build_task_contract("Now what if the support contract was for 24 months instead of 12?", history=history)
    assert not contract.case.new_case


def test_the_first_message_and_plain_questions_are_unaffected():
    assert not starts_new_case(BRIGHTWATER, [])                                       # nothing earlier
    assert not starts_new_case("What is IFRS 16?", [M(role="user", content=NORTHWIND)])  # no case of its own
