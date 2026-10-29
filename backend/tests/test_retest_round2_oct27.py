"""Second 27 Oct 2026 re-test on 3000.

A. "Record the journal entry: Dr Right-of-use asset £133,650.60, Cr Lease
   liability £126,370.91. Check if it balances." was answered correctly ("does
   not balance") and then replaced by bare working: the journal check flagged
   the user's own unbalanced entry, repeated in the answer, as an error.
B. Chart JSON written into the answer as text was shown raw, its figures
   emptied ('"data":' and nothing after it).
C. An IFRS 16 lessee answer classified lease payments as operating cash flows.
No model calls.
"""
import pytest

from app.orchestration.accounting_validation import accounting_findings
from app.orchestration.answer_formatting import remove_visual_placeholders
from app.orchestration.calculation_service import validate_answer_calculations

ENTRY_TEXT = "Dr Right-of-use asset £133,650.60\nCr Lease liability £126,370.91"
ENTRY_TABLE = ("| Account | Debit | Credit |\n|---|---|---|\n| Right-of-use asset | 133,650.60 | |\n"
               "| Lease liability | | 126,370.91 |\n")


def _journal(text):
    return [failure for failure in validate_answer_calculations(text) if failure.startswith("Journal")]


# A ----------------------------------------------------------------------------

@pytest.mark.parametrize("entry", [ENTRY_TEXT, ENTRY_TABLE])
@pytest.mark.parametrize("verdict", ["The entry does not balance: debits exceed credits by £7,279.69.",
                                     "This journal is unbalanced by £7,279.69.",
                                     "It is out of balance by £7,279.69.", "It doesn't balance."])
def test_an_answer_that_says_the_entry_does_not_balance_is_not_an_error(entry, verdict):
    assert _journal(f"The entry as given:\n\n{entry}\n\n{verdict}") == []


@pytest.mark.parametrize("entry", [ENTRY_TEXT, ENTRY_TABLE])
def test_an_unbalanced_journal_presented_as_correct_is_still_flagged(entry):
    assert _journal(f"Record the lease as follows:\n\n{entry}\n\nThis records the right-of-use asset.")


# B ----------------------------------------------------------------------------

LEAKED = '''6. Visual illustration (bar chart)
The chart below shows the three key amounts for each of the five years:

{
 "type": "bar",
 "title": "Lease-related amounts over the 5-year term",
 "categories": ["Year 1", "Year 2", "Year 3", "Year 4", "Year 5"],
 "series": [
 {
 "name": "Lease payment",
 "data":
 }
 ],
 "stacked": false
}
(The interest-expense series is derived by applying the 6 % rate.)'''


def test_bare_chart_json_is_removed():
    cleaned = remove_visual_placeholders(LEAKED)
    assert '"type"' not in cleaned and '"series"' not in cleaned and "{" not in cleaned
    assert "6. Visual illustration" in cleaned and "derived by applying the 6 % rate" in cleaned


@pytest.mark.parametrize("text", [
    '```chart\n{"type": "bar", "title": "T", "categories": ["A", "B"], "series": [{"name": "S", "data": [1, 2]}]}\n```',
    # A JSON block that is not a chart spec. (A ```json chart spec is removed
    # since 28 Oct 2026: test_accounting_retest_oct28.py.)
    '```json\n{\n "account": "Rent",\n "amount": 1200\n}\n```',
    "The set {a, b} has two members.",
    '{\n "name": "not a chart",\n "data": [1, 2]\n}',
])
def test_fenced_charts_code_and_ordinary_braces_are_kept(text):
    assert remove_visual_placeholders(text) == text


# C ----------------------------------------------------------------------------

def _rules(answer):
    return [finding.rule for finding in accounting_findings(answer)]


def test_ifrs16_lease_payments_as_operating_cash_flows_are_flagged():
    answer = ("IFRS 16 lessee accounting.\n| Statement | Presentation |\n|---|---|\n"
              "| Statement of Cash Flows | Lease payments are classified within operating activities "
              "(IFRS 16 permits this treatment). |")
    assert "ifrs16_lease_payments_operating" in _rules(answer)


@pytest.mark.parametrize("answer", [
    "Under IFRS 16, short-term lease payments are classified within operating activities.",
    "Under IFRS 16 the principal part is financing; lease payments for interest are presented in operating "
    "activities under the entity's IAS 7 policy.",
    "Under ASC 842, operating lease payments are classified within operating activities.",
    "IFRS 16: the principal portion of lease payments is presented in financing activities.",
])
def test_correct_cash_flow_statements_are_not_flagged(answer):
    assert "ifrs16_lease_payments_operating" not in _rules(answer)
