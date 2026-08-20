"""
Uploaded-document ingestion and retrieval (app/domains/documents).

Every case here builds a REAL file of the format under test and runs it through
the live extractor — no mocked parsers. A mocked PDF proves nothing about
whether pypdf can read a PDF, and the failure mode this feature has to get
right (a scan that yields no text) only shows up against a real file.

Runs on SQLite as well as Postgres. On SQLite the retrieval path exercised is
_search_fallback rather than ts_rank_cd, which is the point: the fallback is
what the rest of the suite runs against, so it has to stay correct.
"""
import asyncio
import io
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.documents import service as documents_service
from app.domains.documents.chunker import CHUNK_CHARS, chunk_segments
from app.domains.documents.extract import ExtractionError, extract
from app.domains.identity.models import Tenant, User

# Object storage is not the subject of these tests and must never be written to
# by them, so the credentials are cleared for the duration of the module. The
# ingest path treats unconfigured storage as a normal, supported condition.
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""


# ── Real fixture files ───────────────────────────────────────────────────────

def _docx_bytes() -> bytes:
    import docx

    document = docx.Document()
    document.add_paragraph(
        "Corporation tax has been provided at 25 per cent, giving a charge of "
        "1,050,000 for the quarter. Deferred tax on accelerated capital "
        "allowances is 182,000."
    )
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _xlsx_bytes(rows: int = 400) -> bytes:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Summary"
    sheet.append(["Period", "Revenue", "Corporation tax", "Net margin"])
    for i in range(1, rows + 1):
        sheet.append([f"M{i}", 100000 + i * 137, 25000 + i * 34, round(11.5 + i * 0.01, 2)])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _csv_bytes() -> bytes:
    lines = ["invoice_no,client,net,vat,gross"]
    lines += [f"INV-{1000 + i},Client {i},{i * 250},{i * 50},{i * 300}" for i in range(1, 80)]
    return "\n".join(lines).encode("utf-8")


def _assemble_pdf(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _pdf_bytes() -> bytes:
    """A single-page PDF with a genuine text stream. Built by hand because no
    PDF writer is a project dependency and this suite must not add one."""
    lines = [
        "HMRC VAT Return Summary",
        "Box 1 VAT due on sales: 840000.00",
        "Box 5 Net VAT to pay: 328000.00",
    ]
    content = "BT /F1 12 Tf 50 750 Td 16 TL\n"
    for line in lines:
        content += f"({line}) Tj T*\n"
    content += "ET"
    stream = content.encode("latin-1")
    return _assemble_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ])


def _scanned_pdf_bytes() -> bytes:
    """A structurally valid PDF that draws a grey rectangle and contains no text
    operators — what a scan or a photograph of a document looks like to a text
    extractor."""
    stream = b"0.8 0.8 0.8 rg 50 50 500 700 re f"
    return _assemble_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ])


# ── Extraction and chunking (no database) ────────────────────────────────────

def test_every_supported_format_yields_text():
    for extension, data in [
        (".docx", _docx_bytes()),
        (".xlsx", _xlsx_bytes()),
        (".csv", _csv_bytes()),
        (".pdf", _pdf_bytes()),
        (".txt", b"An engagement letter. Our fee is 18,500 plus VAT."),
    ]:
        segments = extract(data, extension)
        assert segments, f"{extension} produced no segments"
        assert any(s.text.strip() for s in segments), f"{extension} produced only empty text"


def test_scanned_pdf_is_rejected_with_a_usable_message():
    """The failure that matters most: a scan must be reported, not silently
    indexed as an empty document the user then asks questions about."""
    try:
        extract(_scanned_pdf_bytes(), ".pdf")
        raise AssertionError("a text-free PDF was accepted")
    except ExtractionError as exc:
        message = str(exc).lower()
        # The message reaches the uploader, so it has to name the cause and a
        # way forward rather than just failing.
        assert "scan" in message or "ocr" in message, message


def test_corrupt_and_empty_files_are_rejected():
    for data, extension in [
        (b"%PDF-1.4 this is not a pdf", ".pdf"),
        (b"", ".txt"),
        (b"   \n  \n ", ".txt"),
    ]:
        try:
            extract(data, extension)
            raise AssertionError(f"{extension} accepted unusable content")
        except ExtractionError:
            pass


def test_unknown_extension_is_rejected():
    try:
        extract(b"anything", ".exe")
        raise AssertionError(".exe was accepted")
    except ExtractionError:
        pass


def test_tabular_chunks_repeat_the_header_row():
    """The detail that decides whether a spreadsheet is usable at all. Without
    the header on every chunk, a chunk reads "Q3 | 4,200 | 1,180" and nothing
    in it says which column is revenue and which is tax."""
    chunks = chunk_segments(extract(_xlsx_bytes(), ".xlsx"))
    header = "Period | Revenue | Corporation tax | Net margin"
    summary_chunks = [c for c in chunks if "Summary" in c.locator]
    assert len(summary_chunks) > 1, "fixture too small to produce multiple chunks"
    for chunk in summary_chunks:
        assert chunk.content.startswith(header), f"{chunk.locator} lost its header"


def test_chunks_stay_near_the_size_budget():
    for extension, data in [(".xlsx", _xlsx_bytes()), (".csv", _csv_bytes()), (".docx", _docx_bytes())]:
        for chunk in chunk_segments(extract(data, extension)):
            # Not an exact cap: a chunk is cut on a row or paragraph boundary,
            # so the last unit can push slightly past the budget by design.
            assert len(chunk.content) <= CHUNK_CHARS * 1.6, (
                f"{extension} produced a {len(chunk.content)}-char chunk"
            )


def test_chunk_locators_identify_where_text_came_from():
    """A citation has to point INTO the file, not merely at it."""
    assert all("page" in c.locator for c in chunk_segments(extract(_pdf_bytes(), ".pdf")))
    assert all("sheet" in c.locator for c in chunk_segments(extract(_xlsx_bytes(), ".xlsx")))


# ── Ingestion and retrieval (against a real database) ────────────────────────

class _Fixture:
    """A throwaway SQLite database with a tenant and two users in it.

    Deliberately its own engine rather than the app's: these tests create and
    drop tables, which must never touch a configured Postgres instance.
    """

    def __init__(self):
        self.tenant = f"t-{uuid.uuid4().hex[:8]}"
        self.owner = f"u-{uuid.uuid4().hex[:8]}"
        self.other = f"u-{uuid.uuid4().hex[:8]}"

    async def __aenter__(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.db.add(Tenant(id=self.tenant, name="Documents Test Tenant"))
        self.db.add(User(id=self.owner, tenant_id=self.tenant, email=f"{self.owner}@example.com",
                         full_name="Owner", role="Advisor"))
        self.db.add(User(id=self.other, tenant_id=self.tenant, email=f"{self.other}@example.com",
                         full_name="Colleague", role="Advisor"))
        await self.db.commit()
        return self

    async def __aexit__(self, *_):
        await self.db.close()
        await self.engine.dispose()

    async def ingest(self, filename, extension, data, user=None):
        return await documents_service.ingest_document(
            self.db, tenant_id=self.tenant, user_id=user or self.owner,
            filename=filename, extension=extension, data=data,
        )

    async def retrieve(self, query, document_ids, tenant=None, user=None):
        return await documents_service.retrieve_passages(
            self.db, query=query, document_ids=document_ids,
            tenant_id=tenant or self.tenant, user_id=user or self.owner,
        )


async def test_ingest_indexes_a_real_document_and_reports_real_counts():
    async with _Fixture() as fx:
        result = await fx.ingest("vat-return.pdf", ".pdf", _pdf_bytes())
        assert result.status == "ready", result.failure_reason
        # chunk_count must be the number of chunks actually stored, not a
        # function of the byte size as the placeholder endpoint used to return.
        assert result.chunk_count >= 1
        assert result.char_count > 0
        assert result.failure_reason is None


async def test_failed_extraction_is_recorded_not_discarded():
    async with _Fixture() as fx:
        result = await fx.ingest("scan.pdf", ".pdf", _scanned_pdf_bytes())
        assert result.status == "failed"
        assert result.failure_reason, "a failed document must carry a reason for the uploader"
        assert result.chunk_count == 0
        # And it must never contribute evidence to an answer.
        assert await fx.retrieve("VAT return", [result.document_id]) == []


async def test_retrieval_finds_the_document_that_holds_the_answer():
    async with _Fixture() as fx:
        pdf = await fx.ingest("vat-return.pdf", ".pdf", _pdf_bytes())
        docx = await fx.ingest("accounts.docx", ".docx", _docx_bytes())
        ids = [pdf.document_id, docx.document_id]

        vat = await fx.retrieve("what is the net VAT to pay", ids)
        assert any(p.filename == "vat-return.pdf" for p in vat)

        tax = await fx.retrieve("how much corporation tax was provided", ids)
        assert any(p.filename == "accounts.docx" for p in tax)

        # Every passage must carry the locator that makes it citable.
        assert all(p.locator for p in vat + tax)


async def test_retrieval_is_capped_at_the_answer_budget():
    """More evidence is not better past a point: eight 2,000-character chunks
    already fill the context the model has to reason in."""
    async with _Fixture() as fx:
        ids = [
            (await fx.ingest("a.xlsx", ".xlsx", _xlsx_bytes())).document_id,
            (await fx.ingest("b.csv", ".csv", _csv_bytes())).document_id,
        ]
        passages = await fx.retrieve("revenue tax invoice client period margin net gross", ids)
        assert len(passages) <= documents_service.MAX_CHUNKS_PER_ANSWER


async def test_another_user_cannot_retrieve_someone_elses_document():
    """Uploaded documents are private to the uploader, not merely to the tenant
    — a colleague's client files are not this user's to read."""
    async with _Fixture() as fx:
        owned = await fx.ingest("vat-return.pdf", ".pdf", _pdf_bytes())
        assert await fx.retrieve("net VAT to pay", [owned.document_id], user=fx.other) == []


async def test_another_tenant_cannot_retrieve_the_document():
    async with _Fixture() as fx:
        owned = await fx.ingest("vat-return.pdf", ".pdf", _pdf_bytes())
        assert await fx.retrieve("net VAT to pay", [owned.document_id], tenant="tenant-elsewhere") == []


async def test_absent_or_unmatched_input_returns_nothing_rather_than_failing():
    """Attaching a document that does not answer the question must leave the
    pipeline behaving exactly as it does with no attachment at all."""
    async with _Fixture() as fx:
        doc = await fx.ingest("vat-return.pdf", ".pdf", _pdf_bytes())
        assert await fx.retrieve("net VAT", []) == []
        assert await fx.retrieve("   ", [doc.document_id]) == []
        assert await fx.retrieve("net VAT", ["doc-that-does-not-exist"]) == []
        assert await fx.retrieve("zzqqxx unrelated gibberish", [doc.document_id]) == []


async def test_delete_removes_the_chunks_as_well_as_the_row():
    async with _Fixture() as fx:
        doc = await fx.ingest("vat-return.pdf", ".pdf", _pdf_bytes())
        assert await fx.retrieve("net VAT to pay", [doc.document_id])

        deleted = await documents_service.delete_document(
            fx.db, document_id=doc.document_id, tenant_id=fx.tenant, user_id=fx.owner
        )
        assert deleted
        assert await fx.retrieve("net VAT to pay", [doc.document_id]) == []
        assert await documents_service.count_documents(
            fx.db, tenant_id=fx.tenant, user_id=fx.owner
        ) == 0


async def test_delete_refuses_a_document_the_caller_does_not_own():
    async with _Fixture() as fx:
        doc = await fx.ingest("vat-return.pdf", ".pdf", _pdf_bytes())
        assert not await documents_service.delete_document(
            fx.db, document_id=doc.document_id, tenant_id=fx.tenant, user_id=fx.other
        )
        # And it is still there for its owner.
        assert await fx.retrieve("net VAT to pay", [doc.document_id])


async def test_documents_are_listed_only_for_their_owner():
    async with _Fixture() as fx:
        await fx.ingest("vat-return.pdf", ".pdf", _pdf_bytes())
        await fx.ingest("accounts.docx", ".docx", _docx_bytes())
        mine = await documents_service.list_documents(
            fx.db, tenant_id=fx.tenant, user_id=fx.owner
        )
        theirs = await documents_service.list_documents(
            fx.db, tenant_id=fx.tenant, user_id=fx.other
        )
        assert len(mine) == 2
        assert theirs == []


def _run_async_tests():
    """Standalone runner, matching the convention in tests/test_tenant_isolation.py."""
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and asyncio.iscoroutinefunction(fn):
            asyncio.run(fn())
            print(f"  {name}: PASS")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and not asyncio.iscoroutinefunction(fn):
            fn()
            print(f"  {name}: PASS")
    _run_async_tests()
    print("test_documents_ingest: all tests passed")
