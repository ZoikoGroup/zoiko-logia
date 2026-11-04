"""OCR readings that could mislead an answer are named or withheld (4 Nov 2026,
from probing the real engine with known images):

  - a chart's values listed by bar height, apart from labels that are not
    periods (Software / Hardware), were paired left to right: wrong values;
  - "5,000" read as "5.000" (0.94 confidence), a blurred "$3,618.47" as
    "S3.618.47" (0.96): confidence does not catch them;
  - a Devanagari line read as "可 TqIf 5,000" (0.77): the reader knows Latin
    and Chinese scripts only;
  - a blurred image was not marked at all, only a small one.

The rules are tested on OCR boxes directly; the image cases also run the real
engine where it is installed.
"""
import io

import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.domains.kriton_workspace import ocr
from app.domains.kriton_workspace.documents import extract_document
from tests.test_answer_status_pipeline import pipeline  # noqa: F401  (fixture)


def box(text, x, y, score=0.98, w=None, h=30):
    w = w or 18 * len(text)
    return ([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], text, score)


# ── Figures whose comma or dot is unclear ──────────────────────────────────

@pytest.mark.parametrize("text, named", [
    ("Total 5.000 yuan", ['"5.000" may be 5,000']),
    ("Amount due: 3.618.47", ['"3.618.47" is not a valid number']),
    ("Amount due:S3.618.47", ['"S3.618.47" may begin with a $', '"3.618.47" is not a valid number']),
    ("Paid 1.250.000 in total", ['"1.250.000" is not a valid number']),
])
def test_an_unclear_separator_is_named_for_confirmation(text, named):
    notes = ocr.reading_notes([box(text, 10, 10)], text)
    assert notes.startswith("[Check these figures before using them:")
    assert all(n in notes for n in named), notes


@pytest.mark.parametrize("text", [
    "Total $1,250.00 and 480.50", "Due 15.03.2026", "Code: B8O0-l1S5", "Version 1.2.3", "Rate 3.5%", "Item 12",
])
def test_ordinary_figures_raise_no_note(text):
    assert ocr.reading_notes([box(text, 10, 10)], text) == ""


# ── Low confidence and scripts the reader does not know ────────────────────

def test_low_confidence_and_mixed_script_text_is_named():
    boxes = [box("可 TqIf 5,000", 10, 10, score=0.77), box("Invoice total", 10, 60, score=0.99),
             box("Rogue 可 word", 10, 110, score=0.95)]
    notes = ocr.reading_notes(boxes, "")
    assert notes.startswith("[Low-confidence reading:")
    assert '"可 TqIf 5,000"' in notes and '"Rogue 可 word"' in notes and "Invoice total" not in notes


def test_short_boxes_and_chinese_with_digits_are_not_doubted():
    boxes = [box("1", 10, 10, score=0.6), box("Qty", 60, 10, score=0.99), box("总计5,000元", 10, 60, score=0.94)]
    assert ocr.reading_notes(boxes, "1 Qty\n总计5,000元") == ""


# ── Charts whose labels are not periods ────────────────────────────────────

def test_values_are_paired_with_word_labels_by_position():
    # Listed top to bottom (by bar height) the values were 4,200 / 3,100 / 1,800.
    boxes = [box("4,200", 190, 60), box("3,100", 850, 150), box("1,800", 520, 340),
             box("Software", 160, 540), box("Hardware", 490, 540), box("Services", 820, 540)]
    note = ocr.chart_note(boxes)
    assert "Software 4,200; Hardware 1,800; Services 3,100" in note
    assert "add up to 9,100" in note


def test_word_labels_without_a_value_each_are_not_read_as_a_chart():
    # A footer of words with one number somewhere above is not a chart.
    boxes = [box("Invoice 4471", 100, 60), box("1,800", 520, 340), box("Thank you", 160, 540),
             box("Visit again", 490, 540), box("Goodbye", 820, 540)]
    assert ocr.chart_note(boxes) == ""


def test_period_labels_keep_the_no_value_warning():
    boxes = [box("Revenue", 100, 40), box("Q1", 200, 540), box("Q2", 400, 540), box("Q3", 600, 540)]
    assert ocr.chart_note(boxes).startswith("[Chart: categories Q1, Q2, Q3 are shown, but no value is printed")


# ── Blur ────────────────────────────────────────────────────────────────────

def _text_image(text="Amount due: $3,618.47", blur=0.0, size=(1200, 600)):
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((80, 220), text, fill="black", font=ImageFont.load_default(size=60))
    return image.filter(ImageFilter.GaussianBlur(blur)) if blur else image


def test_sharpness_separates_crisp_from_blurred_text():
    assert ocr.image_sharpness(_text_image()) > 0.6
    assert ocr.image_sharpness(_text_image(blur=4)) < ocr.MIN_SHARPNESS
    assert ocr.image_sharpness(Image.new("RGB", (400, 300), "white")) is None


def test_a_blurred_reading_hides_its_digits_and_says_why():
    text = '[Check these figures before using them: "3.618.47" is not a valid number]\nAmount due: S3.618.47'
    marked = ocr._mark_low_resolution(text, (1200, 600), sharpness=0.09)
    assert marked.startswith("[Blurred image: the text below was read unreliably (sharpness 0.09)")
    body = marked.split("]", 1)[1]
    assert "Check these figures" not in body and not any(ch.isdigit() for ch in body)
    assert ocr._mark_low_resolution("Amount 5", (1200, 600), sharpness=0.9) == "Amount 5"


# ── The real engine ────────────────────────────────────────────────────────

def _png(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def engine(monkeypatch):
    pytest.importorskip("rapidocr_onnxruntime")
    monkeypatch.setattr(ocr, "_engine", None)


def test_a_blurred_amount_is_not_passed_on_as_a_figure(engine):
    [block] = extract_document("blurred.png", _png(_text_image(blur=4)))
    assert block.text.startswith("[Blurred image:")
    assert not any(ch.isdigit() for ch in block.text.split("]", 1)[1])


def test_a_sharp_amount_is_read_exactly(engine):
    [block] = extract_document("sharp.png", _png(_text_image()))
    assert "$3,618.47" in block.text and not block.text.startswith("[")


def test_a_blurred_scan_in_a_pdf_is_marked_like_an_image(engine):
    pytest.importorskip("pypdfium2")
    scan = io.BytesIO()
    _text_image(blur=4).save(scan, "PDF", resolution=150)                 # image only, like QA H03
    [page] = extract_document("scan.pdf", scan.getvalue())
    assert page.metadata == {"page": 1, "ocr": True} and page.text.startswith("[Blurred image:")


def test_a_bar_chart_with_word_labels_is_paired_by_position(engine):
    image = Image.new("RGB", (1200, 600), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=36)
    for i, (label, value) in enumerate([("Software", 4200), ("Hardware", 1800), ("Services", 3100)]):
        x = 150 + i * 330
        draw.rectangle((x, 520 - value // 10, x + 200, 520), fill="#2f6db5")
        draw.text((x + 40, 520 - value // 10 - 50), f"{value:,}", fill="black", font=font)
        draw.text((x + 10, 535), label, fill="black", font=font)
    [block] = extract_document("chart.png", _png(image))
    assert "Software 4,200; Hardware 1,800; Services 3,100" in block.text


# ── Reading notes guide the answer; they are not quoted to the user ────────

def test_every_note_the_reader_writes_is_known_to_the_answer_instructions():
    from app.orchestration.service import _OCR_READING_NOTES
    written = [
        ocr.BLURRED_NOTE.format(sharpness=0.09), ocr.LOW_RESOLUTION_NOTE.format(width=180, height=104),
        ocr.reading_notes([box("5.000", 10, 10)], "5.000"),
        ocr.reading_notes([box("可 TqIf 5,000", 10, 10, score=0.77)], ""),
        ocr.chart_note([box("2,100", 200, 300), box("Q1", 200, 540), box("Q2", 400, 540)]),
        ocr.chart_note([box("Revenue", 100, 40), box("Q1", 200, 540), box("Q2", 400, 540), box("Q3", 600, 540)]),
    ]
    for note in written:
        assert note and any(marker in note for marker in _OCR_READING_NOTES), note


@pytest.mark.parametrize("snippet, instructed", [
    ("[Blurred image: the text below was read unreliably (sharpness 0.09) …]\nAmount due: S?.???.??", True),
    ("Invoice total: $6,420.75", False),
])
async def test_an_image_reading_note_brings_the_plain_words_instruction(pipeline, monkeypatch, snippet, instructed):
    from unittest.mock import AsyncMock, MagicMock

    from app.domains.model_gateway.agent import AgentOutcome
    from app.orchestration import service
    from app.orchestration.schemas import AskKritonRequest
    from app.orchestration.websearch import WebSource

    monkeypatch.setattr(service, "retrieve_document_sources", AsyncMock(return_value=[
        WebSource(title="invoice.png — Image", url="", snippet=snippet, provider="uploaded_document",
                  freshness="uploaded", source_id="doc-1")]))
    prompts = []

    async def model(prompt, *args, **kwargs):
        prompts.append(str(prompt))
        return AgentOutcome(text="Recorded.")
    pipeline.agent.side_effect = model
    await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                             request=AskKritonRequest(query="What exact amount is due on this invoice?",
                                                      document_ids=["doc-1"]))
    sent = "\n".join(prompts)
    assert prompts
    assert ("do not quote them, their measurements" in sent) is instructed
    if instructed:
        assert "not as the answer, an example, a template or a guess" in sent
