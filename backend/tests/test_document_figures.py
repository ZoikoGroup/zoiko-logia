"""Verified figures from attached documents' tables (orchestration/document_figures.py):
every file type, the real rejected financial-statements case, and the
service hook that always uses the complete documents."""
import io
import re
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


def _box(x, y, text):
    return [[x - 30, y - 12], [x + 30, y - 12], [x + 30, y + 12], [x - 30, y + 12]], text, 0.95


# The QA bar chart as OCR reads it (H01): axis scale at x=84, a value printed
# above each quarter, the quarters along the bottom.
BAR_CHART = [_box(700, 38, "Northbridge FY2025 Quarterly Revenue"),
             *(_box(84, y, tick) for y, tick in ((123, "3500"), (196, "3000"), (270, "2500"), (344, "2000"))),
             _box(1140, 165, "3,100"), _box(847, 253, "2,500"), _box(555, 282, "2,300"), _box(261, 311, "2,100"),
             _box(261, 663, "Q1"), _box(555, 663, "Q2"), _box(847, 663, "Q3"), _box(1140, 663, "Q4")]


def test_h01_a_chart_value_is_matched_to_the_label_below_it_not_read_top_to_bottom():
    # Read top to bottom, the scale's 3500 became Q1 and Q1 "the highest".
    from app.domains.kriton_workspace.ocr import chart_note

    note = chart_note(BAR_CHART)
    assert "Q1 2,100; Q2 2,300; Q3 2,500; Q4 3,100; the printed values add up to 10,000" in note
    assert "(3500, 3000, 2500, 2000) are the axis scale, not values" in note


def test_h02_a_chart_page_keeps_its_title_but_not_the_loose_numbers():
    # Left in the text, the scale was paired with the title ("Revenue-$11,000
    # 3,500") and 3,500 + 3,100 + 3,000 + 2,500 summed as the quarters.
    from app.domains.kriton_workspace.ocr import page_text

    boxes = [_box(700, 38, "Northbridge FY2025 Revenue - $11,000 (USD 000s)"), *BAR_CHART[1:]]
    text = page_text(boxes)
    assert text.splitlines()[0].startswith("[Chart read by position") and "add up to 10,000" in text
    assert "$11,000" in text and "\n3500" not in text and "\n3,100" not in text
    figures = verified_document_figures([_src(text, "chart.pdf — Page 1")], "What is inconsistent?")
    assert "3,500" not in figures


def test_h06_a_chart_with_no_values_or_scale_says_none_can_be_read():
    from app.domains.kriton_workspace.ocr import chart_note

    note = chart_note([_box(650, 38, "Revenue Trend (scale suppressed)"),
                       *(_box(x, 663, q) for x, q in ((80, "Q1"), (460, "Q2"), (839, "Q3"), (1219, "Q4")))])
    assert "no value is printed for any of them and the axis scale is not shown" in note
    assert "Do not state values, growth rates or percentages" in note


def test_a_page_that_is_not_a_chart_gets_no_chart_note():
    from app.domains.kriton_workspace.ocr import chart_note

    receipt = [_box(200, 50, "NORTHBRIDGE TEST RECEIPT"), _box(150, 200, "Goods / services"), _box(400, 200, "$80.00"),
               _box(150, 350, "TOTAL"), _box(400, 350, "$88.00"), _box(150, 420, "PAID | 2025-06-12")]
    table_footer = [_box(100, 80, "Customer"), _box(400, 80, "Revenue"), _box(100, 140, "Acme"),
                    _box(400, 140, "1,000"), _box(100, 600, "Signed"), _box(400, 600, "Date")]
    assert chart_note(receipt) == "" and chart_note(table_footer) == ""


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


def test_an_uploaded_image_is_read_with_ocr_and_accepted_by_the_upload_endpoint():
    # QA group H uploads screenshots, charts and receipts as images; only
    # PDF, Office and CSV files could be attached.
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image, ImageDraw, ImageFont

    from app.domains.kriton_workspace import router as workspace_router

    font = ImageFont.load_default(size=30)
    image = Image.new("RGB", (900, 420), "white")
    draw = ImageDraw.Draw(image)
    for r, (label, amount) in enumerate([("Goods / services", "$80.00"), ("Sales tax (10%)", "$8.00"), ("TOTAL", "$88.00")]):
        draw.text((60, 60 + r * 110), label, fill="black", font=font)
        draw.text((560, 60 + r * 110), amount, fill="black", font=font)
    for suffix, kind in ((".png", "PNG"), (".jpg", "JPEG")):
        upload = io.BytesIO()
        image.save(upload, kind)
        [block] = extract_document(f"receipt{suffix}", upload.getvalue())
        assert block.location == "Image" and block.metadata == {"image": True, "ocr": True}
        assert "TOTAL\t$88.00" in block.text and "Sales tax (10%)\t$8.00" in block.text
        assert suffix in workspace_router._ALLOWED_ATTACHMENT_EXTENSIONS
        assert workspace_router._ATTACHMENT_MIME_TYPES[suffix].startswith("image/")


def test_a_small_uploaded_image_is_marked_unreliable_like_a_small_scan():
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (180, 104), "white")
    ImageDraw.Draw(image).text((10, 40), "Amount due: $1,777.77", fill="black")
    upload = io.BytesIO()
    image.save(upload, "PNG")
    blocks = extract_document("invoice.png", upload.getvalue())
    assert blocks == [] or (blocks[0].text.startswith("[Low-resolution scan: the page image is only 180 x 104 pixels")
                            and not re.search(r"\d", blocks[0].text.split("]", 1)[1]))


def test_h03_a_low_resolution_scan_is_marked_unreliable():
    # A 180 x 104 pixel invoice ("$1,7??.??") was read as "83,777.77" with 0.9
    # OCR confidence and stated as the exact amount owed.
    pytest.importorskip("rapidocr_onnxruntime")
    pytest.importorskip("pypdfium2")
    from PIL import Image, ImageDraw

    small = Image.new("RGB", (180, 104), "white")
    ImageDraw.Draw(small).text((8, 40), "Amount due: $1,777.77", fill="black")
    scan = io.BytesIO()
    small.save(scan, "PDF", resolution=21)
    [page] = extract_document("scan.pdf", scan.getvalue())
    assert page.text.startswith("[Low-resolution scan: the page image is only 180 x 104 pixels")
    assert "Do not state or guess any amount, date or reference from this page" in page.text
    # Not one digit of the unreliable reading reaches the answer: the 180 and
    # 104 are only in the note.
    assert not re.search(r"\d", page.text.split("]", 1)[1])


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


def test_depreciation_that_does_not_fit_the_register_date_is_flagged():
    register = "\n".join([
        "asset_id\tdescription\tcategory\tcost\tacquired\tuseful_life_years\taccumulated_depreciation\tnet_book_value",
        "FA201\tAsset 01\tPlant and machinery\t9450\t2023-02-15\t4\t4725\t4725",
        "FA203\tAsset 03\tIT equipment\t12350\t2023-04-15\t3\t4116.67\t8233.33",
        "FA205\tAsset 05\tPlant and machinery\t15250\t2023-06-15\t4\t7625\t7625",
        "FA208\tAsset 08\tFixtures\t19600\t2023-09-15\t10\t17640\t1960",
        "FA209\tAsset 09\tPlant and machinery\t21050\t2023-01-15\t4\t10525\t10525",
        "FA214\tAsset 14\tMotor vehicles\t28300\t2023-06-15\t5\t28300\t0",
    ])
    block = verified_document_figures([_src(register, "kriton-test-fixed-assets.xlsx — 'Register'!1:7")])
    # Two years of a four-year life from Jan/Feb/Jun 2023 put the register at about 2025.
    assert "the assets put it at about Feb 2025 (middle value), ranging from Apr 2024 to Sep 2032" in block
    assert ("FA208 (Fixtures, 10-year life, acquired Sep 2023) is 90% depreciated = 9 years of charge, "
            "depreciated to about Sep 2032") in block
    assert "FA214 (Motor vehicles, 5-year life, acquired Jun 2023) is fully depreciated, which takes until Jun 2028" in block
    assert "FA201 (" not in block and "FA203 (" not in block
    assert "the register is not ready for reporting until they are explained" in block


PAYROLL = "\n".join([
    "employee_id,employee_name,department,gross_pay,paye,employee_ni,employer_ni,pension,net_pay".replace(",", "\t"),
    "EMP101\tEmployee 01\tFinance\t2585.00\t517.00\t206.80\t356.73\t129.25\t1731.95",
    "EMP102\tEmployee 02\tOperations\t2770.00\t554.00\t221.60\t382.26\t138.50\t1855.90",
    "EMP103\tEmployee 03\tSales\t2955.00\t591.00\t236.40\t407.79\t147.75\t1979.85",
])


def test_a_payroll_register_gets_a_balanced_payroll_journal():
    block = verified_document_figures([_src(PAYROLL, "kriton-test-payroll-register.csv — rows 1:4")])
    # Gross 8,310 + employer NI 1,146.78 = 9,456.78; HMRC 1,662 + 664.80 + 1,146.78 = 3,473.58,
    # pension 415.50, net 5,567.70: 3,473.58 + 415.50 + 5,567.70 = 9,456.78.
    assert ("Dr Gross wages and salaries expense 8,310 (gross_pay); "
            "Dr Employer's National Insurance expense 1,146.78 (employer_ni); "
            "Cr PAYE and National Insurance payable to the tax authority 3,473.58 (paye + employee_ni + employer_ni); "
            "Cr Pension contributions payable 415.50 (pension); "
            "Cr Net wages payable to employees 5,567.70 (net_pay); "
            "total debits = 9,456.78; total credits = 9,456.78") in block
    assert "does not balance" not in block
    assert "Net pay check (gross_pay − paye − employee_ni − pension = net_pay): every row agrees" in block


def test_a_payroll_row_whose_net_pay_does_not_agree_is_named():
    wrong = PAYROLL.replace("1979.85", "1999.85")
    block = verified_document_figures([_src(wrong, "payroll.csv — rows 1:4")])
    assert "rows that do not agree: EMP103" in block
    assert "The payroll journal does not balance: credits exceed debits by 20" in block


def test_an_invoice_list_with_gross_and_net_is_not_a_payroll():
    invoices = "\n".join(["invoice\tnet\tvat\tgross", "INV1\t100\t20\t120", "INV2\t200\t40\t240"])
    assert "Payroll journal" not in verified_document_figures([_src(invoices, "inv.csv — rows 1:3")])


def test_the_internal_block_name_never_reaches_the_answer():
    from app.orchestration.document_figures import strip_internal_labels
    assert strip_internal_labels("Source: asset-level figures summed – see “Verified figures”") == \
        "Source: asset-level figures summed"
    assert strip_internal_labels("Jan 2023 = 2 assets [verified figures].") == "Jan 2023 = 2 assets."
    assert strip_internal_labels("They match the totals (see verified totals).") == "They match the totals."
    assert strip_internal_labels("Source: “Verified figures” list of per-asset depreciation") == \
        "Source: the document's figures of per-asset depreciation"
    assert strip_internal_labels("Plain 627,000 stays.") == "Plain 627,000 stays."


def test_a_register_without_accumulated_depreciation_gets_no_fit_check():
    register = "\n".join([
        "Asset ID\tCost\tAcquired\tUseful life (years)",
        "A1\t1000\t2023-01-01\t5", "A2\t2000\t2023-02-01\t5", "A3\t3000\t2023-03-01\t5"])
    assert "Depreciation fit" not in verified_document_figures([_src(register, "fa.xlsx — 'FA'!1:4")])


def test_a_residual_value_is_not_depreciated():
    register = "\n".join([
        "Asset ID\tDescription\tCost (GBP)\tUseful life (years)\tResidual value (GBP)",
        "FA-002\tForklift truck A\t38000\t8\t4000", "FA-008\tOffice laptops\t18000\t3\t0"])
    block = verified_document_figures([_src(register, "fa.xlsx — 'Fixed Assets'!1:3")])
    # (38,000 - 4,000) / 8 = 4,250 and 18,000 / 3 = 6,000
    assert "(Cost (GBP) − Residual value (GBP)) ÷ Useful life (years)" in block
    assert "FA-002 = 4,250" in block and "FA-008 = 6,000" in block and "total = 10,250 for 2 assets" in block


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


_GENERAL_LEDGER = ["Date\tVoucher No\tAccount\tDescription\tDebit\tCredit",
                   "2025-04-03\tJV-1\tTrade receivables\tSale\t1000\t", "2025-04-03\tJV-1\tRevenue\tSale\t\t1000",
                   "2025-04-28\tJV-2\tSalaries and wages\tPayroll\t300\t", "2025-04-28\tJV-2\tCash at bank\tPayroll\t\t300",
                   "2025-05-05\tJV-3\tCost of sales\tStock\t400\t", "2025-05-05\tJV-3\tTrade payables\tStock\t\t400",
                   "2025-05-10\tJV-4\tTrade receivables\tSale\t2500\t", "2025-05-10\tJV-4\tRevenue\tSale\t\t2500",
                   "2025-05-20\tJV-5\tCash at bank\tReceipt\t900\t", "2025-05-20\tJV-5\tTrade receivables\tReceipt\t\t900"]


def test_a_general_ledger_gets_income_and_expenses_per_month_not_trial_balance_statements():
    # "Show total revenue and expenses per month ... chart of monthly revenue"
    # was refused: Credit by month mixed every account, and the ledger's
    # lines were classified as a trial balance ("Cash at bank" on the credit
    # side stopped every total).
    figures = verified_document_figures(
        [WebSource(title="gl.csv — Sheet1", url="", snippet="\n".join(_GENERAL_LEDGER), source_id="d1")],
        "Show total revenue and expenses per month and draw a chart of monthly revenue")
    assert "Accounts not classified" not in figures and "Trial balance" not in figures
    assert "Revenue by month (Revenue): Apr 2025 = 1,000; May 2025 = 2,500" in figures
    assert "Total expenses by month: Apr 2025 = 300; May 2025 = 400" in figures
    assert "Profit (total income minus total expenses) by month: Apr 2025 = 700; May 2025 = 2,100" in figures
    assert "total income = 3,500; total expenses = 700; profit = 2,800" in figures
    assert "by month for Account" not in figures          # covered by the ledger lines; kept the request small
    assert not unreconciled_figures("Revenue was 2,500 in May 2025, against 1,000 in April 2025.", figures)


def test_a_dated_table_that_is_not_a_ledger_gets_months_per_customer():
    rows = ["Date\tCustomer\tAmount", "2026-01-05\tAlder\t100", "2026-01-09\tBirch\t40",
            "2026-02-03\tAlder\t70", "2026-02-11\tBirch\t10"]
    figures = verified_document_figures(
        [WebSource(title="sales.csv — Sheet1", url="", snippet="\n".join(rows), source_id="d1")], "Sales per month by customer")
    assert "Amount by month for Customer = Alder (from Date): Jan 2026 = 100; Feb 2026 = 70" in figures


def test_ledger_per_account_months_are_left_out_of_other_questions():
    figures = verified_document_figures(
        [WebSource(title="gl.csv — Sheet1", url="", snippet="\n".join(_GENERAL_LEDGER), source_id="d1")],
        "Which account has the largest debit total?")
    assert "by month for Account" not in figures and "Ledger 'gl.csv'" not in figures
    assert "Accounts not classified" not in figures      # still not read as a trial balance
    assert "Debit by month (from Date)" in figures        # the existing monthly totals stay


def _sheet(name: str, rows: list[str]) -> WebSource:
    return WebSource(title=f"pack.xlsx — '{name}'!1:{len(rows)}", url="", snippet="\n".join(rows), source_id="d1")


# Same column names on both sheets, with opposite meanings: a bank statement's
# Debit is money out, a cash book's Debit is money in.
_BANK = ["Date\tDetails\tDebit\tCredit\tBalance", "2026-09-01\tOpening balance\t\t\t1000",
         "2026-09-03\tReceipt - Alder Retail\t\t500\t1500", "2026-09-05\tCheque 101 - Fenwick\t200\t\t1300",
         "2026-09-12\tReceipt - Harbour Kitchens\t\t754\t2054", "2026-09-20\tDirect debit - Insurance\t100\t\t1954",
         "2026-09-30\tBank charges\t8\t\t1946", "2026-09-30\tInterest received\t\t4\t1950"]
_BOOK = ["Date\tDetails\tDebit\tCredit\tBalance", "2026-09-01\tOpening balance\t\t\t1000",
         "2026-09-03\tReceipt - Alder Retail\t500\t\t1500", "2026-09-05\tCheque 101 - Fenwick\t\t200\t1300",
         "2026-09-12\tReceipt - Harbour Kitchens\t745\t\t2045", "2026-09-29\tCheque 102 - Swift\t\t60\t1985",
         "2026-09-30\tReceipt - Elmfield (deposited)\t300\t\t2285"]


def test_a_bank_statement_and_cash_book_get_a_reconciliation():
    # A model-made reconciliation used the wrong closing balance, missed a
    # direct debit and called a cash-book error a bank error.
    figures = verified_document_figures([_sheet("Bank Statement", _BANK), _sheet("Cash Book", _BOOK)],
                                        "Prepare the bank reconciliation")
    assert "bank statement closing balance = 1,950; cash book closing balance = 2,285; difference = 335" in figures
    assert "receipts not yet credited (add to the bank balance): 2026-09-30, Receipt - Elmfield (deposited) 300" in figures
    assert "payments not yet presented (deduct from the bank balance): 2026-09-29, Cheque 102 - Swift 60" in figures
    assert "credits (add to the cash book): 2026-09-30, Interest received 4" in figures
    assert "debits (deduct from the cash book): 2026-09-20, Direct debit - Insurance 100; 2026-09-30, Bank charges 8" in figures
    assert "Receipt - Harbour Kitchens: cash book 745, bank 754, cash book understated by 9" in figures
    # 2,285 + 4 - 100 - 8 + 9 = 2,190 and 1,950 + 300 - 60 = 2,190
    assert "Adjusted cash book balance = 2,190; adjusted bank balance = 2,190; unexplained difference = 0" in figures
    assert not unreconciled_figures("The adjusted balance is 2,190 on both sides.", figures)


def test_a_running_balance_is_never_added_up():
    figures = verified_document_figures([_sheet("Bank Statement", _BANK)])
    assert "Total Balance" not in figures
    assert ("Balance is a running balance (never add it up): opening = 1,000 (2026-09-01, Opening balance); "
            "closing = 1,950 (2026-09-30, Interest received)") in figures
    assert "Bank reconciliation" not in figures          # a statement alone has nothing to reconcile


def test_an_undated_balance_column_is_still_totalled():
    figures = verified_document_figures([_src("Account\tBalance\nCash\t100\nBank\t250")])
    assert "Total Balance = 350" in figures


_VAT_ROWS = ["Date\tReference\tType\tCustomer/Supplier\tVAT treatment\tNet amount\tVAT amount",
             "2026-07-01\tS-1\tSale\tAlder\tStandard 20%\t1000\t200", "2026-07-02\tS-2\tSale\tBirch\tZero-rated\t500\t0",
             "2026-07-03\tS-3\tSale\tAlder\tStandard 20%\t300\t60", "2026-07-04\tP-1\tPurchase\tFenwick\tStandard 20%\t400\t80",
             "2026-07-05\tP-2\tPurchase\tOakline\tReduced 5%\t200\t10"]


def test_sales_by_vat_treatment_leave_out_the_purchases():
    # "Summarise sales by VAT treatment": the treatment totals mixed sales
    # and purchases, so the answer said the sources did not state it.
    figures = verified_document_figures([_src("\n".join(_VAT_ROWS), "vat.csv — Sheet1")],
                                        "Summarise sales by VAT treatment.")
    assert ("Net amount by VAT treatment for Type = Sale (total 1,800): Standard 20% = 1,300 (72.22%); "
            "Zero-rated = 500 (27.78%)") in figures
    assert "for Type = Purchase" not in figures          # not asked about
    assert "by Reference for Type" not in figures        # one row each says nothing
    assert "for Type = Sale" not in verified_document_figures([_src("\n".join(_VAT_ROWS), "vat.csv — Sheet1")],
                                                              "Total VAT by customer")


def test_a_trial_balance_gets_its_statements_and_the_suspense_account_is_flagged():
    # "Prepare the financial statements" put revenue and interest in the
    # balance sheet and stated no profit: the model classified the accounts.
    rows = ["account_code\taccount_name\tdebit\tcredit",
            "1000\tProperty, plant and equipment\t1265000\t", "1200\tInventory\t418000\t",
            "1300\tTrade receivables\t703000\t", "1400\tCash at bank\t512000\t",
            "2000\tTrade payables\t\t389000", "2200\tDeferred tax liability\t\t87000",
            "3000\tShare capital\t\t100000", "3100\tRetained earnings\t\t1000000",
            "4000\tRevenue\t\t4182000", "5000\tCost of sales\t2431000\t", "6000\tAdministrative expenses\t300000\t",
            "6100\tInterest payable\t62000\t", "8000\tSuspense\t67000\t"]
    figures = verified_document_figures([WebSource(title="tb.csv — Sheet1", url="", snippet="\n".join(rows), source_id="d1")])
    assert "total debits = 5,758,000; total credits = 5,758,000; difference = 0" in figures
    assert "Gross profit = 1,751,000" in figures and "Finance costs = 62,000 (Interest payable 62,000)" in figures
    assert "Profit for the year = 1,389,000" in figures
    assert "Total assets = 2,898,000" in figures and "Total liabilities = 476,000" in figures
    assert "Suspense account balance = 67,000" in figures
    assert "Total account_code" not in figures   # a code is not an amount


def test_contra_balances_and_common_accounts_still_give_the_statements():
    # Six ordinary accounts were "not classified", so no statement totals were
    # given and the income statement stopped after Revenue.
    rows = ["Account code\tAccount name\tDebit\tCredit",
            "1000\tLand and buildings\t400\t", "1090\tAccumulated depreciation\t\t100", "1200\tTrade receivables\t200\t",
            "1210\tAllowance for doubtful debts\t\t20", "3000\tShare capital\t\t300", "3200\tDividends paid\t50\t",
            "4000\tRevenue\t\t1000", "5000\tCost of sales\t600\t", "6010\tEmployer NI and pension\t40\t",
            "6600\tProfessional fees\t30\t", "2500\tBank loan (repayable 2030)\t\t100",
            # Balances the sheet (1,320 + 200 = 1,520): an unbalanced trial
            # balance gives no statements (Document 01 FS-009).
            "9999\tSuspense\t200\t", "\tTotal\t1520\t1520"]
    figures = verified_document_figures([WebSource(title="tb.csv — Sheet1", url="", snippet="\n".join(rows), source_id="d1")])
    assert "Accounts not classified" not in figures
    assert "Operating expenses = 70 (Employer NI and pension 40, Professional fees 30)" in figures
    assert "Profit for the year = 330" in figures
    assert "Non-current assets = 300 (Land and buildings 400, Accumulated depreciation -100)" in figures
    assert "Current assets = 180" in figures and "Non-current liabilities = 100" in figures
    assert "Dividends paid -50" in figures
    assert "Total = " not in figures                   # the sheet's own Total row is not an account


def test_an_account_the_rules_cannot_place_stops_the_statement_totals():
    rows = ["account_name\tdebit\tcredit", "Revenue\t\t500", "Mystery account\t500\t"]
    figures = verified_document_figures([WebSource(title="tb.csv — Sheet1", url="", snippet="\n".join(rows), source_id="d1")])
    assert "Accounts not classified" in figures and "Mystery account" in figures
    assert "Profit for the year" not in figures


def test_a_general_ledger_gets_each_account_balance_and_its_trial_balance():
    # "Generate ledger account statements": the model subtracted the wrong
    # debit and credit totals itself and the explanation was withheld.
    rows = ["Date\tVoucher No\tAccount\tDescription\tDebit\tCredit",
            "2025-04-03\tJV-1\tTrade receivables\tSale\t1000\t", "2025-04-03\tJV-1\tRevenue\tSale\t\t1000",
            "2025-04-20\tJV-2\tCash at bank\tReceipt\t600\t", "2025-04-20\tJV-2\tTrade receivables\tReceipt\t\t600",
            "2025-04-25\tJV-3\tRent\tRent\t250\t", "2025-04-25\tJV-3\tCash at bank\tRent\t\t250"]
    figures = verified_document_figures([WebSource(title="gl.csv — Sheet1", url="", snippet="\n".join(rows), source_id="d1")])
    assert "- Trade receivables: 2 entries; total debits = 1,000; total credits = 600; closing balance = 400 Dr" in figures
    assert "- Cash at bank: 2 entries; total debits = 600; total credits = 250; closing balance = 350 Dr" in figures
    assert "- Revenue: 1 entries; total debits = 0; total credits = 1,000; closing balance = 1,000 Cr" in figures
    assert "total debit balances = 1,000; total credit balances = 1,000; difference = 0" in figures


# Document 01 (QA question bank) cases G02, G03, G04, G06 and J04, on small
# copies of the Northbridge fixtures.
_SALES = ["transaction_id\tposted_date\tquarter\trow_type\tamount_usd",
          "NB-1\t2025-01-31\tQ1\tTRANSACTION\t650000", "NB-2\t2025-04-30\tQ2\tTRANSACTION\t720000",
          "NB-3\t2025-07-31\tQ3\tTRANSACTION\t800000", "NB-4\t2025-10-31\tQ4\tTRANSACTION\t950000"]


def test_g04_an_exact_duplicate_transaction_is_named_and_left_out_of_the_totals():
    rows = _SALES + ["NB-4\t2025-10-31\tQ4\tTRANSACTION\t950000"]
    figures = verified_document_figures([_src("\n".join(rows), "dup.csv — Sheet1")])
    assert "NB-4 appears 2 times with identical values" in figures
    assert "the total including the repeats would be 4,070,000" in figures
    assert "Total amount_usd = 3,120,000" in figures


def test_an_id_repeated_with_different_values_is_named_not_removed():
    rows = _SALES + ["NB-4\t2025-11-30\tQ4\tTRANSACTION\t10"]
    figures = verified_document_figures([_src("\n".join(rows), "dup.csv — Sheet1")])
    assert "repeated with different values (not excluded; check them): NB-4" in figures
    assert "Total amount_usd = 3,120,010" in figures


def test_g06_a_row_with_no_quarter_is_named_not_assigned():
    rows = [r.replace("\tQ3\t", "\t\t") for r in _SALES]
    figures = verified_document_figures([_src("\n".join(rows), "blank.csv — Sheet1")])
    assert "1 row(s) have no quarter (NB-3 800,000)" in figures and "Do not assign them to a quarter" in figures
    assert "Total amount_usd = 3,120,000" in figures and "Q3 =" not in figures


def test_g02_a_summary_row_that_sums_the_rows_above_is_not_added_again():
    summary = ["Quarter\tCalculated (USD 000s)", "Q1\t=SUM(Transactions!E2:E4) => 2100", "Q2\t2300",
               "FY2025\t=SUM(B2:B3) => 4400"]
    figures = verified_document_figures([_src("\n".join(summary), "book.xlsx — 'Summary'!1:4")])
    assert "Total Calculated (USD 000s) = 4,400" in figures and "8,800" not in figures


def test_g03_a_stale_displayed_value_is_flagged_against_the_recalculation():
    sheet = ["Metric\tLegacy displayed\tRecalculated\tDifference",
             "Q4 FY2025 (USD 000s)\t3200\t3100\t=B2-C2 => 100", "Release state\tINTENTIONALLY STALE\tDO NOT USE\tFAIL"]
    figures = verified_document_figures([_src("\n".join(sheet), "stale.xlsx — 'Stale'!1:3")])
    assert ("Q4 FY2025 (USD 000s): Legacy displayed 3,200, Recalculated 3,100, difference 100. "
            "The Legacy displayed value is stale or wrong") in figures


BOOK = [
    _src("Id\tAmount\nA\t650000\nB\t700000\nC\t750000", "book.xlsx — 'Transactions'!1:4"),
    _src("Rate\n1000", "book.xlsx — 'Controls'!1:2"),
    _src("Quarter\tCalculated\tExpected\tDifference\n"
         "Q1\t=SUM(Transactions!B2:B4)/Controls!A2 => 2100\t2100\t=B2-C2 => 0\n"
         "Q2\t=B2*2 => 4300\t4200\t=B3-C3 => 100\n"
         "Q3\t=VLOOKUP(A4,Transactions!A2:B4,2) => 7\t7\t=B4-C4 => 0", "book.xlsx — 'Summary'!1:4"),
]


def test_g03_each_formula_is_recalculated_and_named_by_its_cell():
    # "Show whether summary-sheet formulas and displayed values agree" named no
    # formula and no cell: "the standard aggregations shown in the sheet".
    figures = verified_document_figures(BOOK, "Show whether summary-sheet formulas and displayed values agree.")
    assert ("Summary!B2 =SUM(Transactions!B2:B4)/Controls!A2: displayed 2,100; recalculated 2,100 "
            "(Controls!A2 = 1,000). Agrees.") in figures
    assert "Summary!B3 =B2*2: displayed 4,300; recalculated 4,200" in figures
    assert "Does NOT agree (difference 100)" in figures and "flag Summary!B3 for review" in figures
    # D3 uses B3 recalculated, not B3 as displayed: the stale 4,300 carried through.
    assert "Summary!D3 =B3-C3: displayed 100; recalculated 0" in figures
    assert "Summary!B4 =VLOOKUP(A4,Transactions!A2:B4,2): displayed 7; not recalculated (VLOOKUP is not supported)" in figures
    assert "2 agree, 2 do not agree, 2 not recalculated" in figures


def test_g03_a_stale_sheet_names_its_cells_and_quotes_a_sheet_name_with_spaces():
    sheet = _src("Metric\tLegacy displayed\tRecalculated\tDifference\nQ4\t3200\t3100\t=B2-C2 => 100",
                 "stale.xlsx — 'Stale Legacy Summary'!1:2")
    figures = verified_document_figures([sheet], "Do the displayed values agree?")
    assert "'Stale Legacy Summary'!B2 = 3,200; 'Stale Legacy Summary'!C2 = 3,100" in figures
    assert "Legacy displayed value is stale or wrong" in figures


def test_the_formula_check_is_only_for_formula_questions_and_needs_reliable_cell_addresses():
    assert "Formula check" not in verified_document_figures(BOOK, "What is total revenue?")
    # Blank rows were left out of this block: its cells cannot be addressed.
    gappy = _src("Quarter\tTotal\nQ1\t=SUM(B5:B6) => 5", "gap.xlsx — 'Summary'!1:4")
    assert "Formula check" not in verified_document_figures([gappy], "Check the formulas")


F8 = _src("source_id\tsection_id\tauthority_tier\teffective_from\teffective_to\trights\trule\n"
          "NB-POLICY-2025\t§A1\t1\t2025-01-01\t2025-12-31\tLICENSED_TEST_USE\tthreshold = 10\n"
          "NB-POLICY-2026\t§A1\t1\t2026-01-01\t\tLICENSED_TEST_USE\tthreshold = 20\n"
          "NB-RESTRICTED-001\t§R\t1\t2025-02-12\t\tPROHIBITED_FULL_TEXT\t<DO_NOT_RETRIEVE_OR_QUOTE>\n"
          "NB-CONFLICT-1\t§C\t2\t2025-04-15\t\tLICENSED_TEST_USE\tcutoff = 30\n"
          "NB-CONFLICT-2\t§C\t2\t2025-04-15\t\tLICENSED_TEST_USE\tcutoff = 35", "F8_SOURCE_REGISTRY.csv — Sheet1")


def test_i01_the_card_in_effect_on_the_date_controls_and_a_later_one_is_not_applied():
    # The answer mixed in the §C cards and decided nothing.
    figures = verified_document_figures(
        [F8], "Under the rules in F8, what is the controlling recognition guidance effective December 31, 2025?")
    assert "- As of 2025-12-31:" in figures
    assert 'NB-POLICY-2025 §A1, tier 1, effective 2025-01-01 to 2025-12-31: "threshold = 10" — NB-POLICY-2025 controls' in figures
    assert "Not yet in effect on this date (do not apply): NB-POLICY-2026 §A1 from 2026-01-01" in figures
    assert "Total authority_tier" not in figures                 # a tier is not an amount


def test_i02_a_date_names_what_ends_and_what_takes_effect():
    figures = verified_document_figures([F8], "Under F8, what changes on January 1, 2026?")
    assert ("Changes on 2026-01-01: NB-POLICY-2025 §A1 ends on 2025-12-31; NB-POLICY-2026 §A1 takes effect; "
            "NB-POLICY-2026 replaces NB-POLICY-2025 in section §A1") in figures


def test_i05_an_equal_tier_conflict_is_escalated_and_i04_a_denied_card_is_never_quoted():
    figures = verified_document_figures([F8], "Two authorized documents in F8 disagree; which one controls as of June 30, 2025?")
    assert "NB-CONFLICT-2 §C, tier 2" in figures and "CONFLICT: these cards have equal authority" in figures
    assert "escalate it for review" in figures
    assert "<DO_NOT_RETRIEVE_OR_QUOTE>" not in figures
    assert "Rights denied: NB-RESTRICTED-001 must not be quoted" in figures


def test_a_two_period_statement_gets_changes_and_averages_not_column_totals():
    # QA fixture F0: the closing column was totalled (revenue + equity = 34,100),
    # the opening column ignored, and B04/C03 had no changes or averages.
    statement = _src("Measure\tFY2024 / Opening\tFY2025 / Closing\nRevenue\t8000\t10000\n"
                     "Depreciation\tNot prescribed\t400\nAccounts receivable\t950\t1250\nInventory\t800\t1100\n"
                     "Accounts payable\t700\t1000\nEquity\t2700\t3600", "f0.xlsx — 'Statements'!1:7")
    flows = _src("Item\tFY2025 (USD thousands)\nOperating cash flow\t1200\nInvesting cash flow\t-800\n"
                 "Capital expenditures\t800\nOpening equity\t2700\nNet income\t900", "f0.xlsx — 'Cash'!1:6")
    figures = verified_document_figures([statement, flows])
    assert "- Accounts receivable: 950, 1,250, change 300, average 1,100" in figures
    assert "- Accounts payable: 700, 1,000, change 300, average 850" in figures
    assert "- Depreciation: 400 (no FY2024 / Opening figure)" in figures
    assert "Total FY2025 / Closing" not in figures and "Total FY2025 (USD thousands)" not in figures
    assert "- Investing cash flow: -800" in figures
    expenses = _src("Item\tFY2025\nRent\t96000\nUtilities\t18400\nInsurance\t12300", "costs.xlsx — 'Costs'!1:4")
    assert "Total FY2025 = 126,700" in verified_document_figures([expenses])      # like items are still totalled


F0_STATEMENT = ("Measure\tFY2024 / Opening\tFY2025 / Closing\nRevenue\t8000\t10000\nCost of goods sold\t5000\t6200\n"
                "Cash\t700\t1200\nAccounts receivable\t950\t1250\nInventory\t800\t1100\nNet PP&E\t3300\t3700\n"
                "Other assets\t250\t250\nAccounts payable\t700\t1000\nTax payable\t200\t300\n"
                "Long-term borrowings\t2100\t2200\nDeferred revenue\t300\t400\nEquity\t2700\t3600")


def test_b03_the_balance_sheet_in_a_statement_is_totalled_per_period():
    # B03 checked cash and equity but never assets = liabilities + equity.
    figures = verified_document_figures([_src(F0_STATEMENT, "f0.xlsx — 'Statements'!1:13")])
    assert ("Balance sheet, FY2024 / Opening: total assets 6,000; total liabilities 3,300; equity 2,700; "
            "liabilities + equity 6,000; balances") in figures
    assert "Balance sheet, FY2025 / Closing: total assets 7,500; total liabilities 3,900; equity 3,600" in figures
    # "Deferred revenue" is a liability, not revenue; B05 raises payables to 1,100.
    corrupted = F0_STATEMENT.replace("Accounts payable\t700\t1000", "Accounts payable\t700\t1100")
    assert "does NOT balance: assets differ by -100" in verified_document_figures(
        [_src(corrupted, "f0.xlsx — 'Statements'!1:13")])


def test_j04_a_three_way_mismatch_is_held_not_paid():
    match = ["record_type\treference\titem\tquantity\tunit_price_usd\ttotal_usd",
             "PURCHASE_ORDER\tPO-1\tDock\t10\t100\t1000", "GOODS_RECEIPT\tGR-1\tDock\t9\t100\t900",
             "SUPPLIER_INVOICE\tINV-1\tDock\t10\t100\t1000"]
    figures = verified_document_figures([_src("\n".join(match), "3way.csv — Sheet1")])
    assert "ordered 10, received 9, invoiced 10" in figures and "invoiced but not received = 1 (100 unmatched)" in figures
    assert "Do not approve or pay it" in figures
    assert "Total quantity" not in figures              # totals across order, receipt and invoice mean nothing
    # The answer then credited accounts payable with the held invoice's 1,000.
    assert "record only the goods received (900) as owed" in figures
    assert "do not post the invoice or the unmatched amount to accounts payable" in figures
    # A retest then recommended paying the received 900 now.
    assert "not even the received part: recommend no partial payment" in figures
    assert "a decision for an authorised approver, not for Kriton" in figures


_RELEASED_PDF = ("NORTHBRIDGE / INCOME STATEMENT\nNB-STMT-RELEASE-v1 | §1 Income Statement / p.1\nFY2025 Revenue\n10,000\n"
                 "FY2025 Cost of goods sold\n(6,200)\nFY2025 NET INCOME\n900\nSTATUS: RELEASED FOR SYNTHETIC TESTING")
_DRAFT_PDF = ("NORTHBRIDGE / UNRELEASED DRAFT\nDraft FY2025 Revenue\n10,500\nReleased FY2025 Revenue (F2)\n10,000\n"
              "Difference\n500\nDraft authorization state\nUNRELEASED / REVIEW_REQUIRED")


def test_f03_each_stated_figure_keeps_its_own_document_page_and_status():
    # A draft's own line "Released FY2025 Revenue (F2) 10,000" was quoted as
    # the released statement's notes.
    figures = verified_document_figures(
        [WebSource(title="released.pdf — Page 1", url="", snippet=_RELEASED_PDF, source_id="d1"),
         WebSource(title="draft.pdf — Page 1", url="", snippet=_DRAFT_PDF, source_id="d2")],
        "Which document is the released FY2025 revenue? Explain conflict.")
    assert "Figures stated in 'released.pdf' (released), Page 1: FY2025 Revenue 10,000; " in figures
    assert "FY2025 NET INCOME 900" in figures
    assert "Figures stated in 'draft.pdf' (unreleased draft), Page 1: Draft FY2025 Revenue 10,500; " in figures
    assert "'released.pdf' (released), Page 1 says FY2025 Revenue = 10,000; 'draft.pdf' (unreleased draft)" in figures
    assert "a draft that repeats a released figure is still the draft speaking" in figures
    assert not unreconciled_figures("Net income was 900 (released.pdf, page 1).", figures)


def test_prose_with_a_few_numbers_is_not_read_as_stated_figures():
    memo = "Internal audit memo\nWe tested 40 purchase orders.\nFindings\n5\nManagement responses are due."
    assert "Figures stated in" not in verified_document_figures([WebSource(title="memo.docx — Section 1", url="",
                                                                           snippet=memo, source_id="d1")])
