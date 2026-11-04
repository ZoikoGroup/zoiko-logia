"""OCR outcomes are told apart (4 Nov 2026): a server without the OCR package
rejected every image as "No readable text or cells were found", the same words
as an unreadable image, and nothing said OCR was missing.

  OCR_MISSING_DEPENDENCY     rapidocr-onnxruntime not installed      server, 503
  OCR_INITIALIZATION_FAILED  installed, the engine does not start    server, 503
  IMAGE_UNREADABLE           the bytes are not a decodable image     file, 422
  OCR_NO_TEXT_FOUND          OCR ran and read nothing legible        file, 422

The dependency and start-up cases are simulated (no OCR needed); the
extraction cases run the real engine and are skipped where it is absent.
"""
import io
import sys
import types
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.domains.kriton_workspace import documents, ocr
from app.domains.kriton_workspace.documents import extract_document
from tests.test_answer_status_pipeline import pipeline  # noqa: F401  (fixture)


@pytest.fixture
def no_engine(monkeypatch):
    monkeypatch.setattr(ocr, "_engine", None)


@pytest.fixture
def missing(no_engine, monkeypatch):
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)       # ImportError on import


@pytest.fixture
def broken(no_engine, monkeypatch):
    class RapidOCR:
        def __init__(self):
            raise OSError("onnx model file not found")
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", types.SimpleNamespace(RapidOCR=RapidOCR))


@pytest.fixture
def blind(monkeypatch):
    """An engine that starts but reads nothing."""
    monkeypatch.setattr(ocr, "_engine", lambda array: ([], None))


def _png(draw=None, size=(900, 300)) -> bytes:
    image = Image.new("RGB", size, "white")
    if draw:
        draw(ImageDraw.Draw(image))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _code(call) -> str:
    with pytest.raises(ocr.OCRError) as exc:
        call()
    return exc.value.code


# ── The four outcomes ──────────────────────────────────────────────────────

def test_a_missing_package_is_named_and_is_a_server_fault(missing):
    assert ocr.ocr_status()["state"] == ocr.OCR_MISSING_DEPENDENCY
    assert "rapidocr-onnxruntime" in ocr.ocr_status()["message"]
    with pytest.raises(ocr.OCRError) as exc:
        ocr.ocr_image_bytes(_png())
    assert exc.value.code == ocr.OCR_MISSING_DEPENDENCY and exc.value.server_fault


def test_an_engine_that_does_not_start_is_named_and_is_a_server_fault(broken):
    status = ocr.ocr_status()
    assert status["state"] == ocr.OCR_INITIALIZATION_FAILED and "OSError" in status["message"]
    assert _code(lambda: extract_document("chart.png", _png())) == ocr.OCR_INITIALIZATION_FAILED


def test_bytes_that_are_not_an_image_are_unreadable_not_missing_ocr(blind):
    assert _code(lambda: ocr.ocr_image_bytes(b"\x89PNG\r\n\x1a\nnot really an image")) == ocr.IMAGE_UNREADABLE
    assert not ocr.OCRError(ocr.IMAGE_UNREADABLE, "").server_fault


def test_an_image_with_nothing_legible_says_so(blind):
    assert _code(lambda: extract_document("blank.png", _png())) == ocr.OCR_NO_TEXT_FOUND


def test_the_ready_state_is_reported(monkeypatch):
    monkeypatch.setattr(ocr, "_engine", object())
    assert ocr.ocr_status() == {"state": "READY"}


# ── PDFs: wholly scanned fails with the reason; mixed keeps its text ───────

def _pdf(pages: list[str | None]) -> bytes:
    """A PDF whose pages are text (a string) or a scan (None: an image only)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    for text in pages:
        if text is None:
            c.drawImage(ImageReader(io.BytesIO(_png())), 50, 400, width=400, height=150)
        else:
            c.drawString(50, 700, text)
        c.showPage()
    c.save()
    return buffer.getvalue()


def test_a_wholly_scanned_pdf_without_ocr_fails_with_the_reason(missing):
    assert _code(lambda: extract_document("scan.pdf", _pdf([None, None]))) == ocr.OCR_MISSING_DEPENDENCY


def test_a_mixed_pdf_without_ocr_keeps_its_text_and_marks_the_unread_scan(missing):
    blocks = extract_document("mixed.pdf", _pdf(["Revenue for FY2025 was 10,000 thousand dollars in total.", None]))
    text = "\n".join(b.text for b in blocks)
    assert "Revenue for FY2025 was 10,000" in text
    assert "[Page 2 is a scan that was not read: OCR is not installed on this server" in text


# ── Through ingestion and the upload route ─────────────────────────────────

async def test_ingestion_records_the_code_and_the_route_maps_it_to_503_or_422(missing, monkeypatch, tmp_path):
    from fastapi import FastAPI
    import httpx

    from app.core.database import get_db
    from app.domains.identity.rbac import get_current_user
    from app.domains.kriton_workspace import router as workspace_router

    def failed(message):
        return SimpleNamespace(id="d1", status="FAILED", processing_error=message)

    outcomes = {"chart.png": "[OCR_MISSING_DEPENDENCY] OCR is not installed on this server",
                "blank.png": "[OCR_NO_TEXT_FOUND] OCR read the image but found no legible text."}

    async def ingest(db, *, filename, **kwargs):
        return failed(outcomes[filename]), 0
    monkeypatch.setattr(workspace_router, "ingest_document", ingest)
    monkeypatch.setattr(workspace_router, "get_settings", lambda: SimpleNamespace(ASYNC_DOCUMENT_INGESTION=False))
    app = FastAPI()
    app.include_router(workspace_router.router)

    async def db():
        yield None
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u", tenant_id="t")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        missing_ocr = await client.post("/kriton-workspace/attachments", files={"file": ("chart.png", _png())})
        blank = await client.post("/kriton-workspace/attachments", files={"file": ("blank.png", _png())})
    # The user reads plain words; the code travels in a header for tools and logs.
    assert missing_ocr.status_code == 503 and missing_ocr.headers["X-Kriton-Error-Code"] == "OCR_MISSING_DEPENDENCY"
    assert missing_ocr.json()["detail"] == ocr.USER_MESSAGES[ocr.OCR_MISSING_DEPENDENCY]
    assert blank.status_code == 422 and blank.headers["X-Kriton-Error-Code"] == "OCR_NO_TEXT_FOUND"
    assert blank.json()["detail"] == "We couldn't find any readable text in this image. Please upload a clearer " \
                                     "image or the original document."
    assert "[" not in blank.json()["detail"]


async def test_process_document_stores_the_ocr_code_first(missing, monkeypatch, tmp_path):
    # process_document reads _STORAGE_ROOT.parents[1] / storage_path, kept inside _STORAGE_ROOT.
    root = tmp_path / "a" / "b"
    root.mkdir(parents=True)
    stored = root / "chart.png"
    stored.write_bytes(_png())
    monkeypatch.setattr(documents, "_STORAGE_ROOT", root)
    document = SimpleNamespace(id="d1", filename="chart.png", storage_provider="local",
                               storage_path=str(stored.relative_to(tmp_path)), status="UPLOADED",
                               processing_error=None, expires_at=None, tenant_id="t")

    class DB:
        async def execute(self, *a, **k): ...
        async def commit(self): ...
        async def refresh(self, *a): ...
        def add_all(self, *a): ...
    await documents.process_document(DB(), document)
    assert document.status == "FAILED"
    assert document.processing_error.startswith("[OCR_MISSING_DEPENDENCY] OCR is not installed on this server")


# ── The real engine ────────────────────────────────────────────────────────

def test_a_readable_receipt_is_extracted_by_the_real_engine(no_engine):
    pytest.importorskip("rapidocr_onnxruntime")
    font = ImageFont.load_default(size=32)

    def receipt(draw):
        for row, (label, amount) in enumerate([("Subtotal", "$80.00"), ("Tax", "$8.00"), ("Total", "$88.00")]):
            draw.text((60, 40 + row * 80), label, fill="black", font=font)
            draw.text((520, 40 + row * 80), amount, fill="black", font=font)
    assert ocr.ocr_status() == {"state": "READY"}
    [block] = extract_document("receipt.png", _png(receipt))
    assert "Total\t$88.00" in block.text and "Tax\t$8.00" in block.text


def test_a_blank_image_read_by_the_real_engine_is_no_text_not_missing_ocr(no_engine):
    pytest.importorskip("rapidocr_onnxruntime")
    assert _code(lambda: extract_document("blank.png", _png())) == ocr.OCR_NO_TEXT_FOUND


# ── Kriton reads the image, not only accepts the file ──────────────────────
# Real OCR -> the chunks retrieval returns -> the prompt the model receives.

def _chart(draw):
    font = ImageFont.load_default(size=34)
    for i, (quarter, value) in enumerate([("Q1", 2100), ("Q2", 2300), ("Q3", 2500), ("Q4", 3100)]):
        x = 140 + i * 180
        draw.rectangle((x, 520 - value // 10, x + 110, 520), fill="#2f6db5")
        draw.text((x + 10, 520 - value // 10 - 44), f"{value:,}", fill="black", font=font)
        draw.text((x + 30, 535), quarter, fill="black", font=font)


@pytest.mark.parametrize("name, draw, size, question, facts", [
    ("chart.png", _chart, (900, 600), "List all four quarter values and identify the highest quarter.",
     ["Q1 2,100", "Q2 2,300", "Q3 2,500", "Q4 3,100"]),
])
async def test_the_image_text_reaches_the_model(pipeline, monkeypatch, no_engine, name, draw, size, question, facts):
    pytest.importorskip("rapidocr_onnxruntime")
    from app.domains.model_gateway.agent import AgentOutcome
    from app.orchestration import service
    from app.orchestration.schemas import AskKritonRequest
    from app.orchestration.websearch import WebSource
    from unittest.mock import AsyncMock, MagicMock

    blocks = extract_document(name, _png(draw, size))                       # the real engine
    sources = [WebSource(title=f"{name} — {b.location}", url="", snippet=b.text, provider="uploaded_document",
                         freshness="uploaded", source_id="doc-1") for b in blocks]
    monkeypatch.setattr(service, "retrieve_document_sources", AsyncMock(return_value=sources))
    prompts = []

    async def model(prompt, *args, **kwargs):
        prompts.append(str(prompt))
        return AgentOutcome(text="Recorded.")
    pipeline.agent.side_effect = model
    await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                             request=AskKritonRequest(query=question, document_ids=["doc-1"]))
    sent = "\n".join(prompts)
    assert prompts, "the question never reached the model"
    assert all(fact in sent for fact in facts), [fact for fact in facts if fact not in sent]



@pytest.mark.parametrize("stored, code, shown", [
    ("[IMAGE_UNREADABLE] The file could not be opened as a PNG or JPEG image", "IMAGE_UNREADABLE",
     "This file couldn't be opened as an image. It may be damaged or in another format."),
    ("[OCR_INITIALIZATION_FAILED] OCR is installed on this server but could not start (OSError)",
     "OCR_INITIALIZATION_FAILED", ocr.USER_MESSAGES[ocr.OCR_INITIALIZATION_FAILED]),
    ("No readable text or cells were found in the document", None,
     "No readable text or cells were found in the document"),
    (None, None, None),
])
def test_a_stored_error_is_shown_in_plain_words_and_keeps_its_code(stored, code, shown):
    from datetime import datetime, timezone

    from app.domains.kriton_workspace.schemas import DocumentPublic
    assert ocr.public_error(stored) == (code, shown)
    public = DocumentPublic(id="d", filename="x.png", mime_type="image/png", status="FAILED",
                            processing_error=stored, created_at=datetime.now(timezone.utc))
    assert public.processing_error == shown
