"""Question-bank cases (statements-1 Document 01) that had no test of their
own, checked where Kriton computes the answer instead of the model: A04, B01,
B02, B06, C04, E03, F01, H04, J02. The F0 figures are copied inline from
F0_NB-FIN-v1.xlsx (USD thousands); the statements-1 files stay out of the repo."""
from unittest.mock import AsyncMock, MagicMock

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
    assert "revenue 10,000 there is 10,000,000 in whole units and 10.0 million" in block


def test_c04_liquidity_leverage_and_return_on_average_assets():
    block = verified_document_figures(F0, "Show current ratio, debt-to-equity and average-asset ROA for F0.")
    assert ("current ratio = current assets 3,550 (Cash, Accounts receivable, Inventory) ÷ current liabilities 1,700 "
            "(Accounts payable, Tax payable, Deferred revenue) = 2.09x") in block
    assert "debt-to-equity = long-term borrowings 2,200 ÷ equity 3,600 = 0.61x" in block
    assert "return on average assets = net income 900 ÷ average total assets 6,750" in block and "= 13.33%" in block


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
