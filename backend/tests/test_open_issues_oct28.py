"""Open issues from the 28 Oct 2026 re-tests.

1. A source's illustrative example became an input for the user's case: "the
   SME expects to recover only 20%" was applied to a customer in
   administration ("if the same expectation applies here … £15,000 × 20% =
   £3,000, impairment £12,000"); the user never gave a recovery. The figure
   check counted the example's 20% as evidence, so all three figures passed.
2. Pasted test instructions quoted Kriton's note ("you should now see
   'Accounting review needed: …'") and the model wrote that line into its
   answer, where it read as a check Kriton had run.
3. An acknowledgement was audited as a clarification with nothing to tell it
   from a question.
No model, database or network.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.accounting_validation import REVIEW_PREFIX
from app.orchestration.answer_formatting import remove_reserved_notes
from app.orchestration.figure_reconciliation import unreconciled_figures, without_example_figures
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

QUESTION = ("Explain the accounting treatment Context: The company has trade receivables of £120,000 at the year end. "
            "A customer owing £15,000 has gone into administration.")
ANSWER = ("For a defaulted customer the recoverable amount is usually the amount realised on liquidation. If the same "
          "expectation applies here, the recoverable amount = £15,000 × 20 % = £3,000.\n"
          "Impairment loss = £15,000 – £3,000 = £12,000.")
EXAMPLE = ("Example 3: An SME sells goods on credit. At the reporting date the customer is in liquidation and the "
           "SME expects to recover only 20 per cent of the amount owed.")


# 1 ----------------------------------------------------------------------------

def test_an_example_figure_is_not_evidence_for_the_users_case():
    assert unreconciled_figures(ANSWER, QUESTION + "\n" + without_example_figures(EXAMPLE), "", stated=QUESTION) \
        == ["20 %", "£3,000", "£12,000"]


def test_the_unmasked_example_was_what_let_them_through():
    assert unreconciled_figures(ANSWER, QUESTION + "\n" + EXAMPLE, "", stated=QUESTION) == []


def test_rule_text_before_an_example_keeps_its_figures():
    text = ("The VAT registration threshold is £90,000 of taxable turnover. In this example, the trader's turnover "
            "is £120,000.\n\nFrom 1 April 2024 the threshold applies to a rolling 12 months.")
    masked = without_example_figures(text)
    assert "£90,000" in masked and "£120,000" not in masked and "1 April 2024" in masked


def test_figure_evidence_masks_sources_not_the_users_documents():
    request = SimpleNamespace(query=QUESTION, conversation_history=[])
    evidence = service.figure_evidence_text(
        request, [SimpleNamespace(snippet=EXAMPLE)], [], [SimpleNamespace(snippet="Example 1: our customer owes £15,000.")],
        None)
    assert "20 per cent" not in evidence and "£15,000." in evidence


# 2 ----------------------------------------------------------------------------

def test_model_lines_in_the_form_of_kritons_notes_are_removed():
    text = ("The journal entry does not balance; the debit side exceeds the credit side by £7,279.69.\n\n"
            "Accounting review needed: the entry needs a further credit of £7,279.69, not a debit.\n"
            "**Calculation check:** all figures agree.\n"
            "- No source was cited for this answer.\n"
            "An accounting review needed by the auditor is a separate matter.")
    kept = remove_reserved_notes(text)
    assert "does not balance" in kept and "separate matter" in kept
    assert "Accounting review needed:" not in kept and "Calculation check" not in kept and "No source was cited" not in kept


async def test_the_copied_note_never_reaches_the_answer(pipeline):
    pipeline.answers(AgentOutcome(text="The journal entry does not balance; it needs a further credit of £7,279.69.\n\n"
                                       "Accounting review needed: the entry needs a further credit of £7,279.69, not a debit."))
    response, _ = await pipeline.ask("Dr Right-of-use asset £133,650.60, Cr Lease liability £126,370.91. Check if it balances.")
    assert response.answer and "does not balance" in response.answer.text
    assert REVIEW_PREFIX not in response.answer.text


# 3 ----------------------------------------------------------------------------

async def test_an_acknowledgement_is_audited_as_one(pipeline):
    with patch.object(service, "audit_clarification_returned", AsyncMock()) as audited:
        await pipeline.ask("We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025.")
        assert audited.await_args.kwargs["kind"] == "acknowledgement"
        await pipeline.ask("UK company, VAT at 20%, figures exclude VAT: sales £100,000, purchases £50,000. "
                           "Calculate VAT payable.")
        assert audited.await_args.kwargs["kind"] == "question"
