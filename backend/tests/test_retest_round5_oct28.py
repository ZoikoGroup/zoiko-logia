"""Third 28 Oct 2026 live re-test (20 questions, one chat).

1. A quarterly lease answer was marked "a figure differs from the
   calculation": its own journal note "Dr Lease liability £20,000.00" (the
   year's payments) was read as the lease liability's balance.
2. The review note for a wrong balancing direction began "the figures add
   up", beside an entry that does not balance.
3. "Now calculate the lease liability for that lease" was given every lease
   in the chat: it asked "advance or arrears?" for a lease stated in arrears
   (another lease was in advance), and after a correction it asked which of
   five leases was meant.
4. "We lease a van: …" sent while a clarification question was open was
   taken as the reply to it and answered at length.
No model, database or network.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestration import service
from app.orchestration.accounting_validation import accounting_findings, accounting_review_note, calculation_discrepancies
from app.orchestration.calculations.engine import calculation_markdown
from app.orchestration.calculations.lease import lease_calculation
from app.orchestration.schemas import AskKritonRequest, ConversationMessage as M
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

# The leases asked earlier in the live chat, one of them paid in advance.
EARLIER = [
    "Calculate the IFRS 16 lease liability: annual payments of £12,000 in advance, discount rate 6%, lease term 5 years.",
    "Calculate the lease liability: quarterly payments of £5,000 in arrears, discount rate 8% a year, lease term 2 years.",
    "Under ASC 842, an operating lease has annual payments of $40,000 in arrears for 4 years at a 5% discount rate. "
    "Calculate the lease liability and the annual lease cost.",
    "Calculate the lease liability for payments of £10,000 a year at 5% for 3 years.",
]
INDIA = "We are an Indian company reporting under Ind AS for the year ending 31 March 2026."
OFFICE = "We lease office space: annual payments of ₹6,00,000 in arrears, discount rate 9%, lease term 3 years."
VAN = "We lease a van: annual payments of £8,000 in arrears, discount rate 5%, lease term 3 years."
THAT_LEASE = "Now calculate the lease liability for that lease."


def _history(*users):
    return [M(role="user", content=text) for text in users]


def _values(response):
    return {o.name: o.display_value for o in response.calculation.outputs} if response.calculation else {}


# 1 ----------------------------------------------------------------------------

def test_the_calculators_own_journal_postings_are_not_read_as_balances():
    result = lease_calculation(EARLIER[1])
    assert calculation_discrepancies(calculation_markdown(result), result) == []


@pytest.mark.parametrize("statement", ["The lease liability is £20,000.00 at commencement.",
                                       "Initial lease liability: £20,000.00"])
def test_a_wrong_stated_balance_is_still_caught(statement):
    result = lease_calculation(EARLIER[1])
    assert [d.rule for d in calculation_discrepancies(statement, result)] == ["calculation_mismatch"]


# 2 ----------------------------------------------------------------------------

def test_the_note_for_an_unbalanced_entry_does_not_say_the_figures_add_up():
    findings = accounting_findings("Dr Rent expense £1,200\nCr Accruals £1,000\n\n"
                                   "Identify the missing credit (or an additional debit).")
    note = accounting_review_note(findings)
    assert [f.rule for f in findings] == ["balancing_entry_wrong_side"]
    assert "figures add up" not in note and "needs a further credit of 200" in note


def test_other_review_notes_keep_their_wording():
    findings = accounting_findings("| Account | Debit | Credit |\n|---|---|---|\n| Revenue | 1,000 | |\n"
                                   "| Cash | | 1,000 |\n")
    assert accounting_review_note(findings).startswith("Accounting review needed: the figures add up, but")


# 3 ----------------------------------------------------------------------------

async def test_that_lease_uses_only_its_own_lease_among_others(pipeline):
    response, _ = await pipeline.ask(THAT_LEASE, history=_history(*EARLIER, INDIA, OFFICE))
    values = _values(response)
    assert values["lease_liability"] == "₹1,518,776.80" and values["first_year_interest"] == "₹136,689.91"


async def test_a_correction_after_the_lease_applies_to_that_lease_only(pipeline):
    history = _history(*EARLIER, INDIA, OFFICE, VAN, "Correction: the lease term is 4 years, not 3.")
    response, _ = await pipeline.ask(THAT_LEASE, history=history)
    assert _values(response)["lease_liability"] == "£28,367.60"          # £8,000, 5%, 4 years


async def test_a_correction_before_a_later_lease_is_not_applied_to_it(pipeline):
    history = _history(VAN, "Correction: the lease term is 4 years, not 3.", OFFICE)
    response, _ = await pipeline.ask(THAT_LEASE, history=history)
    assert _values(response)["lease_liability"] == "₹1,518,776.80"      # the office lease's own 3 years


# 4 ----------------------------------------------------------------------------

async def _ask(query, history, clarification_cycle):
    return await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                    request=AskKritonRequest(query=query, conversation_history=history,
                                                             clarification_cycle=clarification_cycle),
                                    clarification_cycle=clarification_cycle)


async def test_a_new_statement_during_a_clarification_is_acknowledged(pipeline):
    response = await _ask(VAN, _history(*EARLIER, INDIA, OFFICE, THAT_LEASE), clarification_cycle=1)
    assert response.outcome == "acknowledged"
    assert response.next_action.message.startswith("Noted") and "£8,000" in response.next_action.message
    assert not pipeline.agent.await_args


@pytest.mark.parametrize("reply", ["All standard-rated.", "Sales are £100,000 and purchases £50,000.",
                                   "Our turnover is £95,000 for the last 12 months."])
async def test_a_reply_to_the_clarification_is_still_a_reply(pipeline, reply):
    vat = "UK company, VAT at 20%, figures exclude VAT: sales £100,000, purchases £50,000. Calculate VAT payable."
    response = await _ask(reply, _history(vat), clarification_cycle=1)
    assert not (response.next_action and (response.next_action.message or "").startswith("Noted"))
