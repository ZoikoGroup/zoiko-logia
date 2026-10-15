"""Verified figures from attached documents' tables (orchestration/document_figures.py):
every file type, the real rejected financial-statements case, and the
service hook that always uses the complete documents."""
import io
from types import SimpleNamespace

import pytest

from app.domains.kriton_workspace.documents import extract_document
from app.orchestration import service
from app.orchestration.document_figures import tables_from_sources, verified_document_figures
from app.orchestration.figure_reconciliation import unreconciled_figures
from app.orchestration.websearch import WebSource

HEADER = "Customer\tCategory\tRevenue_USD\tCost_USD\tStatus"
ROWS = [
    "Summit Capital\tSoftware\t205,000\t67,000\tCompleted",
    "Pioneer Logistics\tHardware\t189,000\t90,000\tCompleted",
    "Horizon Bank\tSoftware\t176,000\t60,000\tIn Progress",
    "Nova Healthcare\tServices\t162,000\t80,000\tCompleted",
    "Kappa Manufacturing\tHardware\t156,000\t70,000\tCompleted",
]


def _src(snippet: str, title="sales.xlsx — 'Sales'!1:6") -> WebSource:
    return WebSource(title=title, url="", snippet=snippet)


def test_workbook_figures_cover_totals_groups_shares_top_n_and_remainders():
    block = verified_document_figures([_src("\n".join([HEADER, *ROWS]))])
    assert "Total Revenue_USD = 888,000" in block
    assert "Cost_USD as a share of Revenue_USD = 41.33%" in block
    assert "Revenue_USD by Category: Software = 381,000 (42.91%)" in block
    assert "Top 3 Customer by Revenue_USD together = 570,000 (64.19%); the other 2 together = 318,000 (35.81%)" in block
    assert "Rows by Status: Completed = 4; In Progress = 1" in block


def test_ranges_of_one_sheet_merge_and_the_repeated_header_and_total_rows_are_dropped():
    first = _src("\n".join([HEADER, *ROWS[:3]]), "sales.xlsx — 'Sales'!1:4")
    second = _src("\n".join([HEADER, *ROWS[3:], "Total\t\t888,000\t367,000\t"]), "sales.xlsx — 'Sales'!5:7")
    [table] = tables_from_sources([first, second])
    assert len(table.rows) == 6                         # 5 rows + the Total row, header dropped
    assert "Total Revenue_USD = 888,000" in verified_document_figures([first, second])   # Total row not double counted


def test_the_rejected_answer_now_reconciles_and_its_wrong_figure_does_not():
    # The real case: the model wrote "top 3 customers = 570,000 (25.2%)" and
    # "other 10 customers = 658,000". 570,000 / 25.2% are right but were
    # unverifiable; 658,000 was simply wrong (the other 10 total 722,000).
    rows = ["Summit Capital\t205000", "Pioneer Logistics\t189000", "Horizon Bank\t176000", "Nova Healthcare\t162000",
            "Kappa Manufacturing\t156000", "Core Systems\t145000", "Jupiter Energy\t134000", "River Utilities\t132000",
            "Apex Corp\t125000", "Fusion Labs\t118000", "Metro Telecom\t100000", "Delta Finance\t90000",
            "Alpha Retail\t85000", "Beta Media\t80000", "Gamma Foods\t75000", "Omega Travel\t70000",
            "Sigma Auto\t65000", "Theta Pharma\t60000", "Zeta Labs\t52000", "Lambda Group\t45000"]
    source = _src("\n".join(["Customer\tRevenue_USD", *rows]))
    evidence = source.snippet + verified_document_figures([source])
    assert unreconciled_figures("The top three customers contributed USD 570,000 (25.2 % of total revenue).", evidence) == []
    assert unreconciled_figures("The other 10 customers contributed 722,000.", evidence) == []
    assert unreconciled_figures("The other 10 customers contributed 658,000.", evidence) == ["658,000"]


def test_csv_word_and_powerpoint_tables_are_read_through_the_real_extractors():
    from docx import Document
    from pptx import Presentation
    from pptx.util import Inches

    csv_blocks = extract_document("ledger.csv", ("Account,Debit,Credit\nCash,1500,0\nSales,0,1200\nVAT,0,300\n").encode())
    doc = Document()
    doc.add_paragraph("Quarterly expenses")
    table = doc.add_table(rows=4, cols=2)
    for row, (label, amount) in zip(table.rows, [("Expense", "Amount"), ("Rent", "12,000"), ("Salaries", "48,000"), ("Utilities", "3,000")]):
        row.cells[0].text, row.cells[1].text = label, amount
    docx_bytes = io.BytesIO()
    doc.save(docx_bytes)
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    grid = slide.shapes.add_table(4, 2, Inches(1), Inches(1), Inches(4), Inches(2)).table
    for r, (label, amount) in enumerate([("Region", "Sales"), ("North", "40,000"), ("South", "25,000"), ("West", "35,000")]):
        grid.cell(r, 0).text, grid.cell(r, 1).text = label, amount
    pptx_bytes = io.BytesIO()
    deck.save(pptx_bytes)

    for name, data, expected in (
        ("ledger.csv", None, "Total Debit = 1,500"),
        ("costs.docx", docx_bytes.getvalue(), "Total Amount = 63,000"),
        ("deck.pptx", pptx_bytes.getvalue(), "Total Sales = 100,000"),
    ):
        blocks = csv_blocks if data is None else extract_document(name, data)
        sources = [_src(b.text, f"{name} — {b.location}") for b in blocks]
        assert expected in verified_document_figures(sources), name


def test_pdf_text_tables_are_detected_from_label_and_number_lines():
    page = ("Income statement for FY2025\nRevenue by product\n"
            "Software 1,199,000 588,000\nHardware 553,000 280,000\nServices 512,000 241,000\n"
            "Prepared by finance.")
    block = verified_document_figures([_src(page, "report.pdf — Page 1")])
    assert "Total Column 1 = 2,264,000" in block and "Total Column 2 = 1,109,000" in block
    assert "Column 1 by Item: Software = 1,199,000 (52.96%)" in block


def test_prose_or_documents_without_numeric_tables_add_nothing():
    assert verified_document_figures([_src("This memo explains revenue recognition under IFRS 15.", "memo.docx — Document text")]) == ""
    assert verified_document_figures([]) == ""


def test_unrelated_columns_are_not_compared():
    block = verified_document_figures([_src("Customer\tRevenue\tUnits\nA\t100,000\t5\nB\t50,000\t3\nC\t80,000\t2")])
    assert "Units as a share of Revenue" not in block and "Total Units = 10" in block


async def test_the_hook_reads_the_complete_documents_for_a_targeted_question(monkeypatch):
    full = [_src("\n".join([HEADER, *ROWS]))]
    partial = [_src("\n".join([HEADER, ROWS[0]]))]
    calls = []

    async def fake_retrieve(db, **kwargs):
        calls.append(kwargs)
        return full

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(service, "retrieve_document_sources", fake_retrieve)
    db = SimpleNamespace(begin_nested=lambda: _Nested())
    targeted = SimpleNamespace(retrieval_mode="targeted")
    block = await service._verified_document_figures_context(db, "total revenue?", ["doc-1"], partial, targeted, "t1", "u1")
    assert "Total Revenue_USD = 888,000" in block and calls[0]["full_document"] is True
    assert await service._verified_document_figures_context(db, "q", [], partial, targeted, "t1", "u1") == ""


async def test_the_hook_fails_soft(monkeypatch):
    async def broken(db, **kwargs):
        raise TimeoutError("statement timeout")

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(service, "retrieve_document_sources", broken)
    db = SimpleNamespace(begin_nested=lambda: _Nested())
    assert await service._verified_document_figures_context(
        db, "q", ["doc-1"], [], SimpleNamespace(retrieval_mode="targeted"), "t1", "u1") == ""
