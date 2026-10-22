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


def test_a_messy_sheet_with_titles_sections_formulas_dashes_codes_and_rates():
    sheet = "\n".join([
        "Quarterly sales report",
        "Prepared by\tFinance team",
        "Region\tRevenue\tCost\tProfit\tVAT rate",
        "North",                                              # a section row inside the table
        "Leeds\tUSD 1,000\t400\t=B4-C4 => 600\t20%",
        "York\t2,000\t-\t=B5-C5 => 2000\t20%",
        "South",
        "Bath\t3,000 USD\t(500)\t=B7-C7 => 3500\t5%",
        "Total\t6,000\t-100\t6,100\t",
    ])
    block = verified_document_figures([_src(sheet)])
    assert "Table 'sales.xlsx' (Region, Revenue, Cost, Profit, VAT rate): 3 data rows" in block   # title, "Prepared by" and Total rows left out
    assert "Total Revenue = 6,000" in block and "Total Cost = -100" in block and "Total Profit = 6,100" in block
    assert "VAT rate: average 15" in block and "Total VAT rate" not in block


def test_a_long_workbook_split_into_ranges_and_overlapping_chunks_is_counted_once():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Customer", "Notes", "Revenue"])
    for n in range(1, 131):
        sheet.append([f"Customer {n:03d}", "long note " * 12, n * 100])
    data = io.BytesIO()
    workbook.save(data)
    blocks = extract_document("big.xlsx", data.getvalue())
    assert len({b.location for b in blocks}) >= 4 and len(blocks) > len({b.location for b in blocks})   # ranges, and split chunks
    sources = [WebSource(title=f"big.xlsx — {b.location}", url="", snippet=b.text, source_id="doc-1") for b in blocks]
    block = verified_document_figures(sources)
    assert f"Total Revenue = {sum(n * 100 for n in range(1, 131)):,}" in block
    assert "130 data rows" in block


def test_two_uploads_with_the_same_file_name_stay_separate():
    a = WebSource(title="sales.xlsx — 'S'!1:3", url="", snippet="Item\tAmount\nA\t10\nB\t20", source_id="doc-a")
    b = WebSource(title="sales.xlsx — 'S'!1:3", url="", snippet="Item\tAmount\nA\t1\nB\t2", source_id="doc-b")
    block = verified_document_figures([a, b])
    assert "Total Amount = 30" in block and "Total Amount = 3" in block


def test_pdf_column_names_come_from_a_header_line_or_a_year_row():
    named = verified_document_figures([_src("Product Revenue Cost\nSoftware 100 40\nHardware 50 20\nServices 30 10", "r.pdf — Page 1")])
    assert "Total Revenue = 180" in named and "Total Cost = 70" in named
    years = verified_document_figures([_src("Revenue 2024 2025\nSoftware 100 140\nHardware 50 60\nServices 30 35", "r.pdf — Page 2")])
    assert "Total 2025 = 235" in years


def test_ocr_boxes_become_tab_rows_with_empty_cells_kept_in_their_column():
    from app.domains.kriton_workspace.ocr import lines_from_boxes

    def box(x0, x1, y, text):
        return [[x0, y - 10], [x1, y - 10], [x1, y + 10], [x0, y + 10]], text, 0.95

    text = lines_from_boxes([
        box(50, 300, 20, "Sales summary FY2025"),
        box(50, 150, 80, "Product"), box(400, 520, 80, "Revenue"), box(700, 780, 80, "Cost"),
        box(50, 160, 120, "Software"), box(405, 530, 121, "1,199,000"), box(690, 800, 119, "588,000"),
        box(50, 160, 160, "Hardware"), box(690, 800, 160, "280,000"),            # Revenue cell blank
        box(50, 100, 200, "Data"), box(105, 160, 200, "Centre"), box(405, 530, 200, "512,000"), box(690, 800, 200, "241,000"),
    ])
    assert text.splitlines() == [
        "Sales summary FY2025", "Product\tRevenue\tCost", "Software\t1,199,000\t588,000",
        "Hardware\t\t280,000", "Data Centre\t512,000\t241,000",
    ]


def test_a_scanned_pdf_is_read_with_ocr():
    pytest.importorskip("rapidocr_onnxruntime")
    pytest.importorskip("pypdfium2")
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=30)
    image = Image.new("RGB", (1240, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 60), "Sales summary FY2025", fill="black", font=font)
    for r, row in enumerate([("Product", "Revenue", "Cost"), ("Software", "1,199,000", "588,000"),
                             ("Hardware", "553,000", "280,000"), ("Services", "512,000", "241,000")]):
        for c, cell in enumerate(row):
            draw.text((80 + c * 380, 160 + r * 70), cell, fill="black", font=font)
    scan = io.BytesIO()
    image.save(scan, "PDF", resolution=150)              # an image only: no text layer
    [page] = extract_document("scan.pdf", scan.getvalue())
    assert page.metadata == {"page": 1, "ocr": True}
    block = verified_document_figures([_src(page.text, "scan.pdf — Page 1")])
    assert "Total Revenue = 2,264,000" in block and "Revenue by Product: Software = 1,199,000 (52.96%)" in block


def test_ocr_unavailable_leaves_scanned_pages_empty_without_failing(monkeypatch):
    from PIL import Image

    from app.domains.kriton_workspace import ocr

    def unavailable():
        raise ImportError("libGL.so.1: cannot open shared object file")

    monkeypatch.setattr(ocr, "_get_engine", unavailable)
    scan = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(scan, "PDF")
    assert extract_document("scan.pdf", scan.getvalue()) == []


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


def test_a_fixed_asset_register_gets_its_straight_line_depreciation():
    register = "\n".join([
        "asset_id\tdescription\tcategory\tcost\tacquired\tuseful_life_years\taccumulated_depreciation\tnet_book_value",
        "FA201\tAsset 01\tPlant and machinery\t9450\t2023-02-15\t4\t4725\t4725",
        "FA202\tAsset 02\tMotor vehicles\t10900\t2023-03-15\t5\t6540\t4360",
        "FA203\tAsset 03\tIT equipment\t12350\t2023-04-15\t3\t4116.67\t8233.33",
        "FA204\tAsset 04\tPlant and machinery\t5520\t2023-05-15\t4\t2760\t2760",
    ])
    block = verified_document_figures([_src(register, "kriton-test-fixed-assets.xlsx — 'Register'!1:5")])
    # 9450/4 + 10900/5 + 12350/3 + 5520/4 = 2362.50 + 2180 + 4116.67 + 1380
    assert "Annual straight-line depreciation (cost ÷ useful_life_years" in block
    assert "total = 10,039.17 for 4 assets" in block
    assert "Plant and machinery = 3,742.50" in block and "IT equipment = 4,116.67" in block
    assert "FA201 = 2,362.50" in block
    assert "Total useful_life_years" not in block and "useful_life_years: average 4" in block


def test_no_depreciation_line_without_both_cost_and_useful_life():
    block = verified_document_figures([_src("Customer\tRevenue\tCost\nA\t100\t40\nB\t50\t20")])
    assert "straight-line" not in block


def test_a_dated_ledger_gets_totals_per_month_in_date_order():
    # "Show monthly totals as a bar chart" of a 600-row ledger was refused:
    # the figures had no month totals.
    rows = ["txn_id\tdate\tnominal_code\tamount",
            "T1\t2026-02-03\tNominal 4000\t100.50", "T2\t2026-01-15\tNominal 4010\t200",
            "T3\t2026-02-20\tNominal 4000\t50", "T4\t31/03/2026\tNominal 4010\t25"]
    figures = verified_document_figures([WebSource(title="ledger.csv — Sheet1", url="", snippet="\n".join(rows), source_id="d1")])
    assert "amount by month (from date): Jan 2026 = 200; Feb 2026 = 150.50; Mar 2026 = 25" in figures
    assert "Rows by month (from date): Jan 2026 = 1; Feb 2026 = 2; Mar 2026 = 1" in figures
    assert not unreconciled_figures("February 2026 total: 150.50", figures)
