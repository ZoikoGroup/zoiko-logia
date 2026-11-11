"""Question-bank cases (statements-1 Document 01) that had no test of their
own, checked where Kriton computes the answer instead of the model: A04, B01,
B02, B06, C04, E03, F01, H04, J02. The F0 figures are copied inline from
F0_NB-FIN-v1.xlsx (USD thousands); the statements-1 files stay out of the repo."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestration import service
from app.orchestration.accounting_methods import accounting_method_guidance
from app.orchestration.document_figures import verified_document_figures
from app.orchestration.schemas import AskKritonRequest
from app.orchestration.websearch import WebSource
from tests.test_statement_rules import pipeline  # noqa: F401 - the shared pipeline fixture

F0_STATEMENTS = "\n".join([
    "NB-FIN-v1  Northbridge Analytics Inc.  synthetic financial dataset (F0)  USD thousands",
    "Measure\tFY2024 / Opening\tFY2025 / Closing", "Revenue\t8000\t10000", "Cost of goods sold\t5000\t6200",
    "Operating expenses, excl. depreciation\tNot prescribed\t2100", "Depreciation\tNot prescribed\t400",
    "Interest expense\tNot prescribed\t100", "Income tax expense\tNot prescribed\t300", "Cash\t700\t1200",
    "Accounts receivable\t950\t1250", "Inventory\t800\t1100", "Net PP&E\t3300\t3700", "Other assets\t250\t250",
    "Accounts payable\t700\t1000", "Tax payable\t200\t300", "Long-term borrowings\t2100\t2200",
    "Deferred revenue\t300\t400", "Equity\t2700\t3600"])
F0_CASH = "\n".join([
    "Item\tFY2025 (USD thousands)", "Operating cash flow\t1200", "Investing cash flow\t-800",
    "Financing cash flow\t100", "Net change in cash\t500", "Capital expenditures\t800", "Debt proceeds\t600",
    "Debt repayments\t500", "Dividends\t0", "Opening equity\t2700", "Net income\t900", "Closing equity\t3600"])
F0 = [WebSource(title="F0_NB-FIN-v1.xlsx — 'Statements'!1:18", url="", snippet=F0_STATEMENTS, source_id="d1"),
      WebSource(title="F0_NB-FIN-v1.xlsx — 'Cash flow and equity'!1:12", url="", snippet=F0_CASH, source_id="d1")]


def test_b01_b02_gross_profit_and_the_ebitda_bridge_are_computed():
    block = verified_document_figures(F0, "Reconcile F0 EBITDA to net income using all intermediate subtotals.")
    assert "gross profit = revenue 10,000 − cost of goods sold 6,200 = 3,800 (gross margin = 3,800 ÷ 10,000 = 38.00%)" in block
    assert "EBITDA = 3,800 − operating expenses, excl. depreciation 2,100 = 1,700" in block
    assert "EBIT = 1,700 − depreciation 400 = 1,300" in block            # not the "excl. depreciation" line
    assert "profit before tax = 1,300 − interest expense 100 = 1,200; net income = 1,200 − income tax expense 300 = 900" in block


def test_b06_thousands_convert_to_whole_dollars_and_millions():
    block = verified_document_figures(F0, "Convert F0 FY2025 revenue from USD thousands to whole USD and millions.")
    assert "revenue 10,000 is 10,000,000 in whole units and 10.0 million" in block


def test_h02_chart_title_and_printed_total_are_both_converted():
    """Live run (11 Nov 2026): "$11 million" and "$10 million" for a chart in
    USD thousands were removed as unverified figures."""
    chart = WebSource(title="H02_chart_total_11000.jpeg — image", url="", source_id="d1", snippet=(
        "[Chart read by position: the value printed above each category label is Q1 2,100; Q2 2,300; Q3 2,500; "
        "Q4 3,100; the printed values add up to 10,000 (worked out from the values; the chart prints no total).]\n"
        "NorthbridgeFY2025Revenue-$11,000 (USD 000s)"))
    block = verified_document_figures([chart], "What is inconsistent in this document?")
    assert ("revenue 11,000 is 11,000,000 in whole units and 11.0 million; the printed values' total 10,000 is "
            "10,000,000 in whole units and 10.0 million; the difference 1,000 is 1,000,000 in whole units and "
            "1.0 million.") in block
    assert ("H02_chart_total_11000.jpeg: the title states 11,000; the printed values add up to 10,000; they "
            "differ by 1,000. Report the difference.") in block
    agreeing = WebSource(title="c.png — image", url="", source_id="d2",
                         snippet="the printed values add up to 10,000\nFY2025 Revenue $10,000")
    assert "Report the difference" not in verified_document_figures([agreeing], "Check this chart")


def test_g03_the_files_own_stale_marking_is_passed_on():
    sheet = WebSource(title="M04.xlsx — 'Stale Legacy Summary'!1:3", url="", source_id="d1", snippet=(
        "Metric\tLegacy displayed\tRecalculated\tDifference\nQ4 FY2025 (USD 000s)\t3200\t3100\t=B2-C2 => 100\n"
        "Release state\tINTENTIONALLY STALE\tDO NOT USE\tFAIL EXPECTED"))
    block = verified_document_figures([sheet], "Show whether summary-sheet formulas and displayed values agree.")
    assert ('M04.xlsx marks its own values: "Release state, INTENTIONALLY STALE, DO NOT USE, FAIL EXPECTED"'
            in block)
    bank = WebSource(title="bank.csv — rows", url="", source_id="d2",
                     snippet="Item\tAmount\nStale cheques written back\t300\nObsolete inventory provision\t200")
    assert "marks its own values" not in verified_document_figures([bank], "Reconcile the bank")


def test_f04_a_pdf_chart_not_read_as_a_picture_is_said_so():
    pages = [WebSource(title="NB.pdf — Page 1", url="", source_id="d1", snippet="INCOME STATEMENT\nRevenue\n10,000"),
             WebSource(title="NB.pdf — Page 3", url="", source_id="d1",
                       snippet="NOTES & GRAPH\nQuarterly revenue comparison\nNote 2. Q1 revenue\n2,100")]
    asked = verified_document_figures(pages, "Describe the embedded quarterly revenue chart and confirm its values.")
    assert "- Chart: NB.pdf — Page 3 names a chart or graph, but its picture was not read" in asked
    assert "- Chart:" not in verified_document_figures(pages, "What is FY2025 revenue?")


def test_c04_liquidity_leverage_and_return_on_average_assets():
    block = verified_document_figures(F0, "Show current ratio, debt-to-equity and average-asset ROA for F0.")
    # Each amount is given: named only, the answer used opening cash 700 (app retest, 7 Nov 2026).
    assert ("current ratio = current assets (Cash 1,200 + Accounts receivable 1,250 + Inventory 1,100 = 3,550) ÷ "
            "current liabilities (Accounts payable 1,000 + Tax payable 300 + Deferred revenue 400 = 1,700) = 2.09x") in block
    assert "debt-to-equity = debt (Long-term borrowings 2,200 = 2,200) ÷ equity 3,600 = 0.61x" in block
    assert "copy the workings, do not recompute" in block
    assert "return on average assets = net income 900 ÷ average total assets 6,750" in block and "= 13.33%" in block


@pytest.mark.parametrize("answer, finding", [
    # App retest of 7 Nov 2026: thousands grouped by spaces and "2.09 ×" were not read.
    ("(700 + 1 250 + 1 100) ÷ (1 000 + 300 + 400) = 2 090 ÷ 1 700 = 2.09 ×", "2,090 ÷ 1,700 equals 1.23, not 2.09"),
    ("Current assets = 700 + 1 250 + 1 100 = 2 090", "equals 3050, not 2090"),
    ("700 + 1 250 + 1 100 = 2 090", "equals 3050, not 2090"),
])
def test_c04_a_wrong_sum_written_with_spaced_thousands_is_caught(answer, finding):
    from app.orchestration.calculation_service import validate_answer_calculations
    assert any(finding in failure for failure in validate_answer_calculations(answer))


@pytest.mark.parametrize("answer", [
    "1 200 + 1 250 + 1 100 = 3 550", "Ratio = 3,550 / 1,700 = 2.09 ×", "300 × 4 = 1,200", "2 × (3 + 4) = 14",
    "In 2025 300 units were sold; 300 × 4 = 1 200", "Values: 100 200 300 400",
])
def test_correct_or_unrelated_figures_are_not_flagged(answer):
    from app.orchestration.calculation_service import validate_answer_calculations
    assert validate_answer_calculations(answer) == []


def test_computed_figures_are_labelled_as_kriton_s_not_the_file_s():
    # App retest of 7 Nov 2026: "EBITDA (as reported)" and ratios "taken from the
    # 'Ratios, FY2025 / Closing' section of" the file, which states neither.
    block = verified_document_figures(F0, "Why did cash increase by 500 although net income was 900?")
    for line in ("- Income statement subtotals", "- Ratios", "- Change in cash"):
        row = next(item for item in block.splitlines() if item.startswith(line))
        assert "computed by Kriton from the file's lines, not stated in the file" in row, line


def test_the_calculators_own_call_is_kept_out_of_the_answer():
    from app.orchestration.answer_formatting import without_tool_trace
    text = ("Ratio = 3,550 / 1,700 = 2.088235… → rounded to 2.09 ×\n"
            "exact calculation input: \"3550 / 1700\" → 2.088235294117647 (rounded to 2.09)\n"
            "- Calculation input: `900 / 6750 * 100` → 13.33\n"
            "Debt-to-equity = 2,200 / 3,600 = 0.61 ×")
    assert without_tool_trace(text) == ("Ratio = 3,550 / 1,700 = 2.088235… → rounded to 2.09 ×\n"
                                        "Debt-to-equity = 2,200 / 3,600 = 0.61 ×")
    assert without_tool_trace("Calculation inputs are listed below.") == "Calculation inputs are listed below."


def test_b03_the_balance_sheet_check_is_an_equation_to_state():
    # Live run of 7 Nov 2026: B03 checked cash and equity, never assets = liabilities + equity.
    block = verified_document_figures(F0, "Confirm that F0 balance sheet, cash-flow ending cash, and equity "
                                          "roll-forward reconcile.")
    assert ("Check: assets 7,500 = liabilities 3,900 + equity 3,600; state it whenever the balance sheet's "
            "balancing or reconciliation is asked") in block


def test_b03_a_balance_sheet_check_the_answer_left_out_is_added():
    # Live run of 7 Nov 2026: B03 answered on cash and equity only, twice.
    question = "Confirm that F0 balance sheet, cash-flow ending cash, and equity roll-forward reconcile."
    figures = verified_document_figures(F0, question)
    note = service._missing_balance_check(question, "Cash reconciles; equity reconciles.", figures)
    assert note == ("Balance sheet check (computed by Kriton from the file): FY2024 / Opening: assets 6,000 = "
                    "liabilities 3,300 + equity 2,700; FY2025 / Closing: assets 7,500 = liabilities 3,900 + equity 3,600.")
    assert service._missing_balance_check(question, "Total assets 7,500 equal liabilities plus equity.", figures) is None
    assert service._missing_balance_check("What is FY2025 revenue?", "Revenue is 10,000.", figures) is None


def test_the_currency_note_keeps_the_files_scale():
    # Live run of 7 Nov 2026: F0 ("USD thousands") was answered "Amounts are in USD."
    from app.orchestration.statement_rules import source_scale, without_currency_symbols
    assert source_scale(F0) == "thousands"
    assert source_scale([WebSource(title="tb.csv — s", url="", snippet="Revenue\t10000", source_id="d")]) is None
    assert without_currency_symbols("Revenue was $10,000.", "USD", "thousands") == (
        "Revenue was 10,000.\n\nAmounts are in USD thousands.", [])
    assert without_currency_symbols("Revenue was 10,000 (USD thousands).", "USD", "thousands") == (
        "Revenue was 10,000 (USD thousands).", [])
    assert without_currency_symbols("Rent was £96,000.", "GBP") == ("Rent was 96,000.\n\nAmounts are in GBP.", [])


def test_j02_the_change_in_cash_is_bridged_from_the_three_flows():
    block = verified_document_figures(F0, "Why did cash increase by 500 although net income was 900?")
    assert ("operating 1,200 + investing -800 + financing 100 = 500; it agrees with the stated net change in cash 500"
            in block)


def test_h04_a_receipt_total_is_checked_once():
    receipt = WebSource(title="receipt.jpg — image", url="", snippet="Subtotal $80.00\nTax $8.00\nTotal $88.00",
                        source_id="d1")
    assert "subtotal 80 + tax 8 = 88; stated total 88: agrees. The tax is counted once" in verified_document_figures([receipt])
    invoice = WebSource(title="inv.pdf — p1", url="", snippet="Subtotal 1,000.00\nVAT (20%) 200.00\nTotal due 1,250.00",
                        source_id="d1")
    assert "subtotal 1,000 + tax 200 = 1,200; stated total 1,250: differs by 50" in verified_document_figures([invoice])


def test_a04_paying_an_accrued_bill_does_not_book_the_expense_again():
    note = accounting_method_guidance(
        "Explain how paying last month's previously accrued $2,000 electricity bill affects profit now.")
    assert "debit the accrued liability (accruals) and credit cash" in note and "never booked again" in note
    assert "accrued liability" not in accounting_method_guidance("How do I pay a supplier invoice?")


def test_e03_the_statements_data_flow_follows_the_controls():
    note = accounting_method_guidance(
        "Draw the data flow from source trial balance to published financial statements.")
    for step in ("source checks", "approved adjustments", "reconciliation", "independent review and approval",
                 "publication of the approved version", "traces back"):
        assert step in note


async def test_f01_net_income_from_a_pdf_is_placed_by_its_page(pipeline, monkeypatch):  # noqa: F811
    page = WebSource(title="NB-STATEMENTS_RELEASED.pdf — Page 1", url="",
                     snippet="Income statement (USD 000s)\nRevenue 10,000\nNet income 900", source_id="d1")
    monkeypatch.setattr(service, "retrieve_document_sources", AsyncMock(return_value=[page]))
    await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                             request=AskKritonRequest(query="What is FY2025 net income?",
                                                      document_ids=["d1"]))
    assert "(Income statement, page 1)" in str(pipeline.await_args)
