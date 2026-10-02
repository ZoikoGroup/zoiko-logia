"""
CSV attachments — documents.py's _extract_csv and the upload endpoint's
allowed types.

A CSV is read as a one-sheet workbook: tab-joined rows in 40-row blocks with
the location and metadata the XLSX extractor emits. Everything downstream
(retrieval, figure extraction for charts, spreadsheet KPIs) only sees those
blocks, so the pinned promise is that the same data behaves the same whichever
of the two formats it arrived in.
"""
import io

from openpyxl import Workbook

from app.domains.kriton_workspace import router as workspace_router
from app.domains.kriton_workspace.documents import extract_document
from app.orchestration.document_evidence import build_document_evidence
from app.orchestration.websearch import WebSource

HEADER = ["employee_id", "employee_name", "department", "gross_pay", "net_pay"]
ROWS = [
    ["EMP101", "Employee 01", "Finance", "2585.00", "1731.95"],
    ["EMP102", "Employee 02", "Operations", "2770.00", "1855.90"],
    ["EMP103", "Employee 03", "Sales", "2955.00", "1979.85"],
]


def _csv(rows, delimiter=",", encoding="utf-8") -> bytes:
    return "\n".join(delimiter.join(row) for row in rows).encode(encoding)


def _xlsx(rows) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "payroll"
    for row in rows:
        sheet.append([float(cell) if cell.replace(".", "", 1).isdigit() else cell for cell in row])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _sources(name: str, data: bytes) -> list[WebSource]:
    return [
        WebSource(title=name, url=f"document://{name}#{b.location}", snippet=b.text, provider="uploaded_document")
        for b in extract_document(name, data)
    ]


def test_csv_reads_like_a_one_sheet_workbook():
    [block] = extract_document("payroll.csv", _csv([HEADER, *ROWS]))
    assert block.location == "'payroll'!1:4"
    assert block.metadata == {"sheet": "payroll", "start_row": 1, "end_row": 4}
    assert block.text.splitlines()[0] == "\t".join(HEADER)
    assert block.text.splitlines()[1] == "EMP101\tEmployee 01\tFinance\t2585.00\t1731.95"


def test_csv_and_xlsx_of_the_same_data_give_the_same_blocks_and_chart_figures():
    csv_blocks = extract_document("payroll.csv", _csv([HEADER, *ROWS]))
    xlsx_blocks = extract_document("payroll.xlsx", _xlsx([HEADER, *ROWS]))
    assert [b.location for b in csv_blocks] == [b.location for b in xlsx_blocks]
    assert [b.metadata for b in csv_blocks] == [b.metadata for b in xlsx_blocks]

    question = "show gross pay by employee as a bar chart"
    from_csv = build_document_evidence(question, _sources("payroll.csv", _csv([HEADER, *ROWS])))
    from_xlsx = build_document_evidence(question, _sources("payroll.xlsx", _xlsx([HEADER, *ROWS])))
    assert [(o.dimension, o.value) for o in from_csv.observations] == \
        [(o.dimension, o.value) for o in from_xlsx.observations]
    assert len(from_csv.observations) == 3


def test_every_block_of_a_long_csv_carries_the_header():
    rows = [HEADER] + [[f"EMP{n}", f"Employee {n}", "Finance", f"{1000 + n}.00", "900.00"] for n in range(90)]
    blocks = extract_document("payroll.csv", _csv(rows))
    assert [b.location for b in blocks] == ["'payroll'!1:41", "'payroll'!42:81", "'payroll'!82:91"]
    assert all(b.text.splitlines()[0] == "\t".join(HEADER) for b in blocks)
    # 90 data rows in total, none lost or duplicated across blocks.
    assert sum(len(b.text.splitlines()) - 1 for b in blocks) == 90


def test_semicolon_quoted_commas_bom_and_windows_text_are_read():
    semicolon = extract_document("ledger.csv", _csv([["account", "amount"], ["Rent", "1200"]], delimiter=";"))
    assert semicolon[0].text.splitlines() == ["account\tamount", "Rent\t1200"]

    quoted = extract_document("ledger.csv", b'account,note\nRent,"Office, London"\n')
    assert quoted[0].text.splitlines()[1] == "Rent\tOffice, London"

    bom = extract_document("ledger.csv", "﻿account,amount\nRent,1200".encode("utf-8"))
    assert bom[0].text.splitlines()[0] == "account\tamount"

    windows = extract_document("ledger.csv", "account,amount\nCafé,£12".encode("cp1252"))
    assert windows[0].text.splitlines()[1] == "Café\t£12"


def test_header_only_and_empty_csvs_do_not_fail():
    [header_only] = extract_document("empty.csv", _csv([HEADER]))
    assert header_only.location == "'empty'!1:1"
    assert extract_document("blank.csv", b"\n\n") == []


def test_the_upload_endpoint_accepts_csv():
    assert ".csv" in workspace_router._ALLOWED_ATTACHMENT_EXTENSIONS
    assert workspace_router._ATTACHMENT_MIME_TYPES[".csv"] == "text/csv"
    # Every allowed type has a MIME type, or the upload would fail on lookup.
    assert workspace_router._ALLOWED_ATTACHMENT_EXTENSIONS <= set(workspace_router._ATTACHMENT_MIME_TYPES)
