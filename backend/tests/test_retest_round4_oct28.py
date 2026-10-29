"""Second 28 Oct 2026 live re-test.

1. "Dr Right-of-use asset £133,650.60, Cr Lease liability £126,370.91. Check
   if it balances." was answered "a £7,279.69 debit is missing": the debits
   already exceed the credits, so balancing needs a further credit (Cr Cash
   for initial direct costs paid, for example). The checks proved the entry
   unbalanced but nothing checked the direction of the explanation.
2. A 4-year lease answer offered "Value by item" bars of the calculator's
   result table (liability, asset, interest, depreciation): the largest table
   won over the 4-year schedule, and the result table lists unlike measures.
No model, database or network.
"""
import pytest

from app.orchestration.accounting_validation import accounting_findings, accounting_review_note
from app.orchestration.calculations.engine import calculate_from_query, calculation_markdown
from app.orchestration.calculations.lease import lease_calculation
from app.orchestration.chart_offer import offer_chart

ENTRY = ("| Account | Debit (£) | Credit (£) |\n|---|---|---|\n| Right‑of‑use asset | 133 650.60 | – |\n"
         "| Lease liability | – | 126 370.91 |\n| Total | 133 650.60 | 126 370.91 |\n")


def _rules(text):
    return [finding.rule for finding in accounting_findings(text)]


# 1 ----------------------------------------------------------------------------

@pytest.mark.parametrize("claim", [
    "With the supplied figures, an additional debit of £7 279.69 must be recorded.",
    "The journal entry does not balance; a £7 279.69 debit is missing.",
    "A debit of £7,279.69 is required to balance it.",
])
def test_saying_the_larger_side_is_missing_is_flagged(claim):
    findings = accounting_findings(f"{ENTRY}\n{claim}")
    assert [f.rule for f in findings] == ["balancing_entry_wrong_side"]
    assert "needs a further credit of 7,279.69" in accounting_review_note(findings)


def test_a_text_journal_is_checked_the_same_way():
    assert _rules("Dr Right-of-use asset £133,650.60\nCr Lease liability £126,370.91\n\n"
                  "A missing debit of £7,279.69 explains the difference.") == ["balancing_entry_wrong_side"]


@pytest.mark.parametrize("text", [
    ENTRY + "\nThe entry does not balance; a further credit of £7,279.69 is needed (e.g. Cr Cash).",
    ENTRY + "\nA balancing credit to cash of £7,279.69 is required.",
    "Dr Expense £900\nCr Cash £1,000\n\nAn additional debit of £100 is required.",    # credits exceed: debit short
    "| Account | Debit | Credit |\n|---|---|---|\n| Cash | 100 | |\n| Revenue | | 100 |\n\nNo additional debit is needed.",
    "An additional debit to the suspense account is usual in such cases.",              # no journal shown
])
def test_correct_or_unverifiable_explanations_are_not_flagged(text):
    assert "balancing_entry_wrong_side" not in _rules(text)


# 2 ----------------------------------------------------------------------------

@pytest.mark.parametrize("years", [4, 5])
def test_a_lease_answer_offers_its_schedule_as_a_line(years):
    result = lease_calculation(f"Calculate the lease liability: annual payments of £20,000 in arrears, discount "
                               f"rate 5%, lease term {years} years.")
    offer = offer_chart(calculation_markdown(result))
    assert (offer.chart_type, offer.title) == ("line", "Closing liability by year")


def test_a_calculator_result_table_alone_is_not_offered():
    result = calculate_from_query("Prepare an income statement: revenue £800,000, cost of sales £480,000, operating "
                                  "expenses £200,000. Show gross and operating profit and margins.")
    assert offer_chart(calculation_markdown(result)) is None


def test_a_period_table_wins_over_a_larger_item_table():
    items = "| Region | Sales |\n|---|---|\n" + "".join(f"| R{i} | £{i}00 |\n" for i in range(1, 8))
    years = "| Year | Revenue |\n|---|---|\n" + "".join(f"| {y} | £{y - 2000}0,000 |\n" for y in range(2021, 2025))
    assert offer_chart(f"{items}\n\n{years}").chart_type == "line"


def test_an_ordinary_item_table_still_gets_bars():
    assert offer_chart("| Region | Sales |\n|---|---|\n| North | £100,000 |\n| South | £80,000 |\n"
                       "| East | £60,000 |\n").chart_type == "bar"


def test_space_grouped_journal_amounts_are_read_in_full():
    from app.orchestration.calculation_service import validate_answer_calculations
    balanced = ("| Account | Debit (£) | Credit (£) |\n|---|---|---|\n| Right‑of‑use asset | 133 650.60 | – |\n"
                "| Lease liability | – | 126 370.91 |\n| Cash | – | 7 279.69 |\n")
    assert [f for f in validate_answer_calculations(balanced) if f.startswith("Journal")] == []
    assert any("debits total 133650.6, credits total 126370.91" in f
               for f in validate_answer_calculations(ENTRY.replace("| Total | 133 650.60 | 126 370.91 |\n", "")))
