"""Stage 2: explicit message types (reply_to) and the "acknowledged" outcome.

A reply to Kriton's clarification is marked by the client (reply_to, with
previous_query carrying the request being clarified), so it is processed
together with that request instead of being guessed from its wording, and an
acknowledgement ("Noted — …") is its own outcome, never counted as a question.
Older clients that send no reply_to keep the inferred behaviour. No model,
database or network.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.orchestration import service
from app.orchestration.message_intent import CONTEXT_ACTIONS
from app.orchestration.schemas import AskKritonRequest, ConversationMessage as M
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

VAT = "UK company, VAT at 20%, figures exclude VAT: sales £100,000, purchases £50,000. Calculate VAT payable."
LEASE = "Calculate the lease liability for payments of £10,000 a year at 5% for 3 years."
VAN = "We lease a van: annual payments of £8,000 in arrears, discount rate 5%, lease term 3 years."
UK = "We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025."


async def _ask(query, history=(), *, previous=None, cycle=0, reply_to=None):
    request = AskKritonRequest(query=query, conversation_history=list(history), previous_query=previous,
                               clarification_cycle=cycle, reply_to=reply_to)
    return await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                    request=request, clarification_cycle=cycle)


def _values(response):
    return {o.name: o.display_value for o in response.calculation.outputs} if response.calculation else {}


async def test_a_marked_reply_completes_the_request_it_answers(pipeline):
    asked = await _ask(VAT)
    assert asked.outcome == "clarification_required"
    response = await _ask("All standard-rated.", [M(role="user", content=VAT)], previous=VAT, cycle=1,
                          reply_to=asked.query_id)
    assert _values(response)["vat_payable"] == "£10,000.00"
    assert not pipeline.agent.await_args


async def test_the_same_reply_unmarked_is_not_calculated(pipeline):
    # The older behaviour, kept for clients without reply_to: the reply alone
    # reaches no calculator (the defect stage 2 fixes for current clients).
    response = await _ask("All standard-rated.", [M(role="user", content=VAT)], previous=VAT, cycle=1)
    assert "vat_payable" not in _values(response)


async def test_a_marked_reply_with_a_timing_completes_the_lease(pipeline):
    asked = await _ask(LEASE)
    assert asked.outcome == "clarification_required"
    response = await _ask("In arrears.", [M(role="user", content=LEASE)], previous=LEASE, cycle=1, reply_to=asked.query_id)
    assert _values(response)["lease_liability"] == "£27,232.48"


async def test_a_marked_reply_is_never_acknowledged_as_new_context(pipeline):
    response = await _ask(VAN, [M(role="user", content=LEASE)], previous=LEASE, cycle=1, reply_to="qry-1")
    assert response.outcome != "acknowledged"
    assert not (response.next_action and (response.next_action.message or "").startswith("Noted"))


async def test_an_unmarked_statement_during_a_clarification_is_still_acknowledged(pipeline):
    # Older clients: the inferred rule (opens_new_context) still applies.
    response = await _ask(VAN, [M(role="user", content=LEASE)], previous=LEASE, cycle=1)
    assert response.outcome == "acknowledged"


async def test_reply_to_without_the_request_it_answers_is_treated_as_unmarked(pipeline):
    response = await _ask(VAN, [M(role="user", content=LEASE)], cycle=1, reply_to="qry-1")
    assert response.outcome == "acknowledged"


async def test_an_acknowledgement_is_its_own_outcome_with_its_actions(pipeline):
    response = await _ask(UK)
    assert response.outcome == "acknowledged" and response.route == "CLARIFICATION"
    assert response.next_action.type == "acknowledge_context"
    assert response.next_action.message.startswith("Noted")
    assert response.next_action.suggestions == CONTEXT_ACTIONS
    assert not pipeline.agent.await_args


async def test_a_real_question_keeps_its_outcome_and_type(pipeline):
    response = await _ask(VAT)
    assert response.outcome == "clarification_required"
    assert response.next_action.type == "ask_clarifying_question"


def test_reply_to_is_bounded():
    with pytest.raises(ValidationError):
        AskKritonRequest(query="x", reply_to="q" * 201)
