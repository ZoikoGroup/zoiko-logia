"""Stage 3: journal-total reconciliation and chart-selection safeguards (27 Oct 2026).

Journals: only tables were checked for balance. An unbalanced journal written
as text ("Dr Right-of-use asset £133,650.60 / Cr Lease liability
£126,370.91") passed, and a "Total" row that states a wrong total was never
compared with its lines. Correct journal totals must still be accepted by the
figure check, so a complete answer is not made partial.

Charts: a worked-calculation table ("Step | Calculation | Amount") was
offered as "Amount by step" bars, comparing a present value with a year's
interest. An audit-findings table with a row-number column ("No.") charted
that column as a measure.

VAT: "cost of sales £40,000" was read as sales, giving output VAT of £8,000
and a £2,000 refund where £10,000 was payable.

Line, bar, pie and grouped-bar offers must not change. No model, database or
network.
"""
import pytest

from app.orchestration.calculation_service import validate_answer_calculations
from app.orchestration.calculations.engine import vat_amounts
from app.orchestration.chart_offer import offer_chart
from app.orchestration.figure_reconciliation import unreconciled_figures

_BALANCED_TABLE = """| Account | Debit | Credit |
|---|---|---|
| Right-of-use asset | 133,650.60 | |
| Lease liability | | 126,370.91 |
| Cash | | 7,279.69 |
| **Total** | **133,650.60** | **133,650.60** |
"""


def _journal_failures(text):
    return [failure for failure in validate_answer_calculations(text) if failure.startswith("Journal")]


# --- journals: positives (flagged) ---

@pytest.mark.parametrize("text", [
    "Journal entry:\nDr Right-of-use asset £133,650.60\nCr Lease liability £126,370.91",
    "Debit Right-of-use asset $133,650.60\nCredit Lease liability $126,370.91",
    "- **Dr** Rent expense: £1,200\n- **Cr** Accruals: £1,000",
    "Dr Rent expense £1,200; Cr Accruals £1,000.",
    "| Account | Debit | Credit |\n|---|---|---|\n| Right-of-use asset | 133,650.60 | |\n| Lease liability | | 126,370.91 |\n",
])
def test_unbalanced_journal_is_flagged(text):
    assert any("does not balance" in failure for failure in _journal_failures(text))


def test_wrong_stated_total_is_flagged():
    text = _BALANCED_TABLE.replace("| **Total** | **133,650.60** | **133,650.60** |",
                                   "| Total | 133,650.60 | 126,370.91 |")
    failures = _journal_failures(text)
    assert failures == ["Journal total does not match its lines: the credit total is shown as 126370.91, "
                        "but the credit lines add up to 133650.6."]


def test_wrong_total_with_label_in_second_column_is_flagged():
    text = ("| Date | Account | Dr | Cr |\n|---|---|---|---|\n| 1 Jan | Right-of-use asset | 133,650.60 | |\n"
            "| 1 Jan | Lease liability | | 126,370.91 |\n| 1 Jan | Cash | | 7,279.69 |\n"
            "| | **Total** | 133,650.60 | 140,000.00 |\n")
    assert any("credit total is shown as 140000" in failure for failure in _journal_failures(text))


def test_second_text_entry_is_checked_separately():
    text = "Dr Cash £100\nCr Revenue £100\nDr Expense £50\nCr Cash £40"
    assert _journal_failures(text) == ["Journal entry does not balance: debits total 50, credits total 40."]


# --- journals: negatives (not flagged) ---

@pytest.mark.parametrize("text", [
    _BALANCED_TABLE,
    ("| Date | Account | Dr | Cr |\n|---|---|---|---|\n| 1 Jan | Right-of-use asset | 133,650.60 | |\n"
     "| 1 Jan | Lease liability | | 126,370.91 |\n| 1 Jan | Cash | | 7,279.69 |\n"
     "| | **Total** | 133,650.60 | 133,650.60 |\n"),
    "Journal entry:\nDr Right-of-use asset £133,650.60\nCr Lease liability £126,370.91\nCr Cash £7,279.69",
    "Dr Cash £100\nCr Revenue £100\n\nDr Expense £50\nCr Cash £50",
    # A working or a year in the line: too uncertain to judge, left alone.
    "Dr Interest expense (£126,370.91 × 6%) £7,582.25\nCr Lease liability £7,000",
    "Dr Lease liability 2024 £5,000\nCr Cash £4,000",
    # Indian "To" form and a person called Dr: not read as a journal.
    "Dr Cash £1,000\nTo Sales £900",
    "Dr. Smith reviewed the file and charged £500.",
    "Debit: the asset account increases.\nCredit: the liability account increases.",
])
def test_balanced_or_uncertain_journal_is_not_flagged(text):
    assert _journal_failures(text) == []


def test_correct_journal_totals_are_supported_by_the_figure_check():
    question = ("Record month-end accruals: rent £1,250. Separately, utilities were £430. "
                "Also wages owed of £2,980. And interest £315.")
    answer = ("| Account | Debit | Credit |\n|---|---|---|\n| Rent expense | £1,250 | |\n"
              "| Utilities expense | £430 | |\n| Wages expense | £2,980 | |\n| Interest expense | £315 | |\n"
              "| Accruals | | £4,975 |\n| **Total** | **£4,975** | **£4,975** |\n")
    assert unreconciled_figures(answer, question, "", question) == []


# --- charts ---

_WORKED = {
    "aro": "| Step | Calculation | Amount |\n|---|---|---|\n| Present value of ARO | $500,000 ÷ 1.05^10 | $306,957 |\n"
           "| Accretion year 1 | $306,957 × 5% | $15,348 |\n| Depreciation year 1 | $306,957 ÷ 10 | $30,696 |\n",
    "lease": "| Item | Working | Amount |\n|---|---|---|\n| Lease liability | PV of 5 × $30,000 at 6% | $126,370.91 |\n"
             "| Right-of-use asset | Liability + direct costs | $133,650.60 |\n| Interest year 1 | $126,370.91 × 6% | $7,582.25 |\n",
    "formula": "| Measure | Formula | Result |\n|---|---|---|\n| Gross profit | £800,000 − £500,000 | £300,000 |\n"
               "| Operating profit | £300,000 − £120,000 | £180,000 |\n| Tax | £180,000 × 25% | £45,000 |\n",
}


@pytest.mark.parametrize("name", sorted(_WORKED))
def test_no_chart_for_worked_calculation_tables(name):
    assert offer_chart(_WORKED[name]) is None


def test_worked_ratios_in_one_unit_are_still_offered():
    table = ("| Metric | Formula | Result (days) |\n|---|---|---|\n| DIO | (Avg Inv ÷ COGS) × 365 | 30.42 |\n"
             "| DSO | (Avg AR ÷ Sales) × 365 | 36.50 |\n| DPO | (Avg AP ÷ COGS) × 365 | 26.07 |\n")
    offer = offer_chart(table)
    assert offer.chart_type == "bar" and offer.chart["series"][0]["data"] == [30.42, 36.5, 26.07]


def test_row_number_column_is_not_a_measure_or_label():
    table = ("| No. | Finding | Severity | Instances |\n|---|---|---|---|\n| 1 | Unreconciled bank | High | 3 |\n"
             "| 2 | Missing approvals | Medium | 5 |\n| 3 | Late cut-off | Low | 2 |\n")
    offer = offer_chart(table)
    assert offer is not None and offer.title == "Instances by finding"
    assert [s["name"] for s in offer.chart["series"]] == ["Instances"]


def test_numbered_period_table_still_charts_the_periods():
    table = ("| No. | Year | Revenue |\n|---|---|---|\n| 1 | 2021 | £100 |\n| 2 | 2022 | £120 |\n"
             "| 3 | 2023 | £150 |\n| 4 | 2024 | £170 |\n")
    offer = offer_chart(table)
    assert (offer.chart_type, offer.title, offer.chart["categories"]) == (
        "line", "Revenue by year", ["2021", "2022", "2023", "2024"])


@pytest.mark.parametrize("table, kind, title", [
    ("| Year | Revenue |\n|---|---|\n| 2021 | £100,000 |\n| 2022 | £120,000 |\n| 2023 | £150,000 |\n| 2024 | £170,000 |\n",
     "line", "Revenue by year"),
    ("| Region | Sales |\n|---|---|\n| North | £100,000 |\n| South | £80,000 |\n| East | £60,000 |\n",
     "bar", "Sales by region"),
    ("| Cost | Amount |\n|---|---|\n| Rent | £30,000 |\n| Salaries | £50,000 |\n| Utilities | £20,000 |\n"
     "| Total | £100,000 |\n", "pie", "Amount by cost"),
    ("| Department | Budget | Actual |\n|---|---|---|\n| Sales | £50,000 | £52,000 |\n| Marketing | £20,000 | £18,500 |\n"
     "| IT | £30,000 | £33,000 |\n", "bar", "Budget and Actual by department"),
])
def test_ordinary_chart_offers_are_unchanged(table, kind, title):
    offer = offer_chart(table)
    assert (offer.chart_type, offer.title) == (kind, title)


# --- VAT: cost of sales is not sales ---

def test_vat_does_not_read_cost_of_sales_as_sales():
    result = vat_amounts("UK company, VAT at 20%, figures exclude VAT: cost of sales £40,000, sales £100,000, "
                         "purchases £50,000. Calculate VAT payable.")
    assert result.status == "success"
    assert [output.display_value for output in result.outputs] == ["£20,000.00", "£10,000.00", "£10,000.00"]


def test_vat_without_sales_is_not_calculated_from_cost_of_sales():
    result = vat_amounts("UK company, VAT at 20%, figures exclude VAT: cost of sales £40,000, purchases £50,000. "
                         "Calculate VAT payable.")
    assert result is None or result.status != "success" or all(
        item.name != "gross_sales" or item.value != 40000 for item in result.inputs)
