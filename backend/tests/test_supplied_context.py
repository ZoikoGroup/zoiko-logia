"""A request about something the supplied text does not contain is answered
plainly ("the text contains no journal entries") instead of being searched,
which produced "not stated" or an invented Debit/Credit example."""
import pytest

from app.orchestration.supplied_context import missing_in_supplied_context

REVIEW = ("# Critical Analysis: IFRS Financial Statement Presentation Under IAS 1 and IFRS 18\n\n"
          "## 1. Overall Assessment\n\n**Verdict: broadly correct; IFRS 18 replaces IAS 1, effective 1 January 2027; "
          "a reclassification with a material effect needs a third balance sheet.**")
ENTRIES = "Dr Inventory 5,000\nCr Cost of sales 5,000\nThe purchase was expensed in error."


@pytest.mark.parametrize("ask, wanted", [
    ("Show the original, incorrect, and correcting entries together.", "journal entries"),
    ("Explain the downstream P&L and AR impact.", "figures"),
])
def test_a_follow_up_asking_for_what_the_text_lacks_is_answered_plainly(ask, wanted):
    gap = missing_in_supplied_context(f"{ask} Context: {REVIEW}")
    assert gap is not None and gap.wanted == wanted
    assert "Critical Analysis: IFRS Financial Statement Presentation Under IAS 1 and IFRS 18" in gap.message
    assert f"contains no {wanted}" in gap.message


@pytest.mark.parametrize("query, history", [
    ("Show the original, incorrect, and correcting entries together. Context: " + ENTRIES, []),
    ("Explain the downstream P&L and AR impact. Context: " + ENTRIES, []),
    ("Show these entries as a table", [ENTRIES]),
    ("Calculate the impact on profit of the figures above", ["Revenue £250,000, COGS £160,000"]),
    ("What are adjusting entries?", []),              # a general question
    ("What are adjusting entries?", [REVIEW]),         # general, even after unrelated text
    ("Summarize the confirmed rules as a checklist. Context: " + REVIEW, []),
])
def test_requests_the_material_can_answer_or_general_questions_pass(query, history):
    assert missing_in_supplied_context(query, history) is None


def test_a_request_pointing_back_at_earlier_messages_is_checked_against_them():
    gap = missing_in_supplied_context("Show these entries as a table", [REVIEW])
    assert gap is not None and gap.wanted == "journal entries"
