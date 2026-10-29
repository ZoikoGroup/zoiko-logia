"""Defects from the 28 Oct 2026 live re-test of the reliability remediation.

A. A statement right after an acknowledged one ("We lease equipment: …" after
   "We are a UK company …") was not acknowledged: the acknowledgement is sent
   as a clarification, so the next message was taken as a reply to it.
B. "…for that lease" with two leases in the chat calculated the first
   (£30,000) instead of the latest (£20,000).
C. The acknowledgement's "Explain the accounting treatment" action was
   refused as "the sources provided do not establish an answer".
D. A chart spec in a ```json fence was shown as raw text.
E. "**[REF-1]**" left "****" in the answer once the marker was removed.
Charts: "2025 (Yr 1)" years were offered as grouped bars, and a VAT result
(output, input, payable = their difference) as "Value by item" bars.
No model, database or network.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.answer_formatting import remove_visual_placeholders
from app.orchestration.chart_offer import offer_chart
from app.orchestration.message_intent import is_context_action
from app.orchestration.schemas import AskKritonRequest, ConversationMessage as M
from app.orchestration.verification_service import normalize_citations
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

UK = "We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025."
WAREHOUSE = ("We lease a warehouse: annual payments of £30,000 in arrears, discount rate 6%, lease term 5 years. "
             "Show the IFRS 16 accounting for the lessee, including the cash flow statement.")
EQUIPMENT = "We lease equipment: annual payments of £20,000 in arrears, discount rate 5%, lease term 4 years."
BREAK_EVEN = ("Separately: what is the break-even point for a product selling at £50 with variable cost £30 and "
              "fixed costs £40,000?")


async def _ask(query, history, clarification_cycle=0):
    # The web layer passes the cycle as an argument (router.py), not only on the request.
    return await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                    request=AskKritonRequest(query=query, conversation_history=history,
                                                             clarification_cycle=clarification_cycle),
                                    clarification_cycle=clarification_cycle)


def _values(response):
    return {o.name: o.display_value for o in response.calculation.outputs} if response.calculation else {}


# A ----------------------------------------------------------------------------

async def test_a_statement_after_an_acknowledgement_is_acknowledged(pipeline):
    # An older frontend counts the acknowledgement as a clarification (cycle 1)
    # and does not replay it in the history. Acknowledgements have their own
    # outcome since stage 2, so a current frontend no longer does.
    response = await _ask(EQUIPMENT, [M(role="user", content=UK)], clarification_cycle=1)
    assert response.outcome == "acknowledged"
    assert response.next_action.message.startswith("Noted") and "£20,000" in response.next_action.message
    assert not pipeline.agent.await_args


async def test_a_reply_to_a_real_clarification_is_still_a_reply(pipeline):
    vat = "UK company, VAT at 20%, figures exclude VAT: sales £100,000, purchases £50,000. Calculate VAT payable."
    response = await _ask("All standard-rated.", [M(role="user", content=vat)], clarification_cycle=1)
    assert not (response.next_action and (response.next_action.message or "").startswith("Noted"))


# B ----------------------------------------------------------------------------

async def test_that_lease_uses_the_latest_lease_in_the_chat(pipeline):
    history = [M(role="user", content=WAREHOUSE), M(role="assistant", content="Lease liability £126,370.91."),
               M(role="user", content=UK), M(role="user", content=EQUIPMENT),
               M(role="user", content=BREAK_EVEN), M(role="assistant", content="2,000 units.")]
    response, _ = await pipeline.ask("Now calculate the lease liability and first-year interest for that lease.",
                                     history=history)
    # Since the second 28 Oct re-test: always the latest lease, never a list to
    # choose from (a "which lease?" list of five appeared when one was meant).
    values = _values(response)
    assert values["lease_liability"] == "£70,919.01" and values["first_year_interest"] == "£3,545.95"


def test_a_correction_is_not_counted_as_a_lease():
    from app.orchestration.calculations.lease import distinct_leases
    assert distinct_leases([WAREHOUSE, EQUIPMENT, "the lease term is 5 years, not 4."]) == [WAREHOUSE, EQUIPMENT]


# C ----------------------------------------------------------------------------

STATEMENT = ("The company recognised revenue of £500,000 for the year. / Management believes the receivables are "
             "fully recoverable.")


@pytest.mark.parametrize("action", ["Explain the accounting treatment", "Calculate the figures",
                                    "Prepare the journal entries"])
def test_the_acknowledgement_actions_are_professional_explanations(action):
    assert is_context_action(f"{action} Context: {STATEMENT}")


@pytest.mark.parametrize("query", [
    "Explain the accounting treatment",                                                    # no context
    "What is the UK VAT threshold? Context: what is VAT",                                  # not an action
    "Explain the accounting treatment Context: Explain IFRS 16 revenue recognition.",      # context is a question
])
def test_other_messages_are_not_context_actions(query):
    assert not is_context_action(query)


async def test_the_explain_action_is_answered_without_requiring_sources(pipeline, monkeypatch):
    explanation = ("Revenue of £500,000 is recognised when control of the goods or services passes to the customer. "
                   "The receivables are then assessed for expected credit losses.")
    pipeline.answers(AgentOutcome(text=explanation))
    from types import SimpleNamespace
    monkeypatch.setattr(service.model_gateway_service, "run_test_prompt",
                        AsyncMock(return_value=(SimpleNamespace(id="prompt", name="Prompt"), explanation)))
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=explanation))
    response, _ = await pipeline.ask(f"Explain the accounting treatment Context: {STATEMENT}")
    assert response.outcome != "unavailable"
    assert response.answer is not None
    assert "do not establish an answer" not in response.answer.text
    assert "The retrieved evidence does not establish the requested answer." not in response.answer.limitations
    # Answered as a professional explanation of the user's own facts, labelled so.
    from app.orchestration.service import GENERAL_EXPLANATION_NOTE
    assert GENERAL_EXPLANATION_NOTE in response.answer.limitations


# D ----------------------------------------------------------------------------

FENCED_SPEC = ('Assumptions as above.\n\n```json\n{\n "type": "bar",\n "title": "Annual Lease Payments",\n '
               '"categories": ["Year 1", "Year 2"],\n "series": [{"name": "Lease Payment", "data":}],\n'
               ' "stacked": false\n}\n```\nNot fully verified.')


def test_a_fenced_json_chart_spec_is_removed():
    cleaned = remove_visual_placeholders(FENCED_SPEC)
    assert '"type"' not in cleaned and "```" not in cleaned
    assert cleaned.startswith("Assumptions as above.") and cleaned.rstrip().endswith("Not fully verified.")


def test_an_unlabelled_fence_with_a_chart_spec_is_removed_too():
    assert '"series"' not in remove_visual_placeholders(FENCED_SPEC.replace("```json", "```"))


# E ----------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Source: IFRS 16, paragraph 22 – **[REF-1]**.", "Source: IFRS 16, paragraph 22 – [REF-1]."),
    ("Shown separately **[REF-1] [REF-2]** in the notes.", "Shown separately [REF-1] [REF-2] in the notes."),
    ("Interest is shown separately – **[REF-9]**.", "Interest is shown separately – ."),     # invented ref dropped
])
def test_bold_around_source_markers_is_unwrapped(text, expected):
    assert normalize_citations(text, {"REF-1", "REF-2"}) == expected


def test_real_bold_text_is_untouched():
    assert normalize_citations("**Bottom line** [REF-1]", {"REF-1"}) == "**Bottom line** [REF-1]"


# Charts -----------------------------------------------------------------------

def test_years_with_a_note_are_periods_and_get_a_line():
    table = ("| Year | Opening liability | Interest (5 %) | Closing liability |\n|---|---|---|---|\n"
             "| 2025 (Yr 1) | £70,919.06 | £3,545.95 | £54,465.01 |\n| 2026 (Yr 2) | £54,465.01 | £2,723.25 | £37,188.26 |\n"
             "| 2027 (Yr 3) | £37,188.26 | £1,859.41 | £19,047.67 |\n| 2028 (Yr 4) | £19,047.67 | £952.38 | £0.00 |\n")
    assert offer_chart(table).chart_type == "line"


def test_a_result_beside_its_operands_gets_no_chart():
    table = ("| Item | Value |\n| --- | --- |\n| Output VAT on sales | £20,000.00 |\n"
             "| Input VAT on purchases | £10,000.00 |\n| VAT payable | £10,000.00 |\n")
    assert offer_chart(table) is None


def test_items_that_only_happen_to_differ_still_get_a_chart():
    table = ("| Region | Sales |\n|---|---|\n| North | £5,000 |\n| South | £3,000 |\n| East | £2,000 |\n")
    assert offer_chart(table).chart_type == "bar"
