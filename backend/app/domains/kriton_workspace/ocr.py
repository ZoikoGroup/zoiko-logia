"""OCR for scanned PDF pages (photos or scans with no text layer).

pypdf returns nothing for such a page, so the document had no evidence and
no figures. Each page is rendered (pypdfium2) and read with RapidOCR, both
pip-only with bundled models, so nothing is sent to an external service.

Text boxes are rebuilt into lines by their vertical position, and boxes on
one line that are clearly apart are joined with a tab. A scanned table thus
comes out as tab-separated rows, the same shape the Word / Excel extractors
write, so retrieval and verified figures (orchestration/document_figures.py)
read it like any other table.

Everything here fails soft: if the OCR packages are missing or a page cannot
be read, the page keeps the (empty) text it had before.
"""
from __future__ import annotations

import logging
import re
import statistics
import threading

logger = logging.getLogger(__name__)

# A page with fewer readable characters than this is treated as scanned.
MIN_TEXT_CHARS = 25
MAX_OCR_PAGES = 40
RENDER_SCALE = 2.0          # ~144 dpi: readable for OCR, bounded memory
MIN_CONFIDENCE = 0.5

_engine = None
_engine_lock = threading.Lock()


def needs_ocr(text: str | None) -> bool:
    return len("".join((text or "").split())) < MIN_TEXT_CHARS


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        return _engine


def lines_from_boxes(boxes: list[tuple[list, str, float]]) -> str:
    """OCR boxes [(4 corner points, text, confidence)] -> text lines, with a
    tab between boxes on one line that are separated by a clear gap."""
    items = []
    for points, text, score in boxes:
        if not (text or "").strip() or float(score) < MIN_CONFIDENCE:
            continue
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        items.append({"text": text.strip(), "x0": min(xs), "x1": max(xs),
                      "y": (min(ys) + max(ys)) / 2, "h": max(ys) - min(ys)})
    if not items:
        return ""
    height = statistics.median(item["h"] for item in items) or 1.0
    items.sort(key=lambda item: item["y"])
    rows: list[list[dict]] = []
    for item in items:
        if rows and abs(item["y"] - statistics.mean(i["y"] for i in rows[-1])) <= height * 0.5:
            rows[-1].append(item)
        else:
            rows.append([item])
    # Boxes close together are one cell ("Software Licences"); a clear gap
    # starts the next cell.
    lines: list[list[dict]] = []
    for row in rows:
        row.sort(key=lambda item: item["x0"])
        cells = [dict(row[0])]
        for item in row[1:]:
            if item["x0"] - cells[-1]["x1"] > height:
                cells.append(dict(item))
            else:
                cells[-1]["text"] += " " + item["text"]
                cells[-1]["x1"] = item["x1"]
        lines.append(cells)
    return "\n".join(_aligned(lines))


def _aligned(lines: list[list[dict]]) -> list[str]:
    """Lines as text. In a run of table rows, a row with an empty cell has
    fewer boxes, so its numbers would shift left into the wrong column; each
    cell is placed under the nearest column of the run's widest row instead,
    leaving the empty cell empty."""
    out: list[str] = []
    index = 0
    while index < len(lines):
        if len(lines[index]) < 2:
            out.append(lines[index][0]["text"])
            index += 1
            continue
        end = index
        while end < len(lines) and len(lines[end]) >= 2:
            end += 1
        run = lines[index:end]
        widest = max(run, key=len)
        anchors = [(cell["x0"] + cell["x1"]) / 2 for cell in widest]
        for cells in run:
            placed = [""] * len(anchors)
            if len(cells) >= len(anchors):
                placed = [cell["text"] for cell in cells]
            else:
                column = -1
                for position, cell in enumerate(cells):
                    centre = (cell["x0"] + cell["x1"]) / 2
                    # Nearest column to the right of the previous one, leaving
                    # room for the cells still to place.
                    last = len(anchors) - (len(cells) - position)
                    column = min(range(column + 1, last + 1), key=lambda c: abs(anchors[c] - centre))
                    placed[column] = cell["text"]
            out.append("\t".join(placed).rstrip("\t"))
        index = end
    return out


def _render_page(content: bytes, page_index: int):
    import pypdfium2

    pdf = pypdfium2.PdfDocument(content)
    try:
        return pdf[page_index].render(scale=RENDER_SCALE).to_pil().convert("RGB")
    finally:
        pdf.close()


def ocr_image(image) -> str:
    import numpy

    result, _ = _get_engine()(numpy.asarray(image))
    return lines_from_boxes(result or [])


# A scan whose image is this small cannot be read reliably, however sure the
# OCR is: a 180 x 104 pixel invoice stretched over a page ("Amount due:
# $1,7??.??") was read as "83,777.77" with 0.9 confidence, and the answer
# stated it as the exact amount owed (QA case H03).
MIN_SCAN_PIXELS = 600
LOW_RESOLUTION_NOTE = ("[Low-resolution scan: the page image is only {width} x {height} pixels, so the text below "
                       "was read unreliably and its digits are shown as ?. Do not state or guess any amount, date or "
                       "reference from this page; say it cannot be read reliably and ask for a clearer copy or the "
                       "original file.]")


def _page_image_size(content: bytes, page_index: int) -> tuple[int, int] | None:
    """The pixel size of the largest image on the page, or None if unknown."""
    try:
        import io

        from pypdf import PdfReader

        sizes = [image.image.size for image in PdfReader(io.BytesIO(content)).pages[page_index].images]
    except Exception:
        return None
    return max(sizes, key=lambda size: size[0] * size[1]) if sizes else None


def ocr_pdf_pages(content: bytes, page_indexes: list[int]) -> dict[int, str]:
    """{page index: OCR text} for the given (0-based) pages; pages that
    cannot be read are left out. A page whose scan is too small to read
    reliably starts with a note saying so."""
    texts: dict[int, str] = {}
    try:
        _get_engine()
    except Exception:  # packages not installed, or a missing system library
        logger.warning("OCR is unavailable; scanned PDF pages stay without text", exc_info=True)
        return texts
    for index in page_indexes[:MAX_OCR_PAGES]:
        try:
            text = ocr_image(_render_page(content, index))
        except Exception:
            logger.warning("OCR failed on PDF page %s", index + 1, exc_info=True)
            continue
        if text:
            size = _page_image_size(content, index)
            if size and max(size) < MIN_SCAN_PIXELS:
                # The digits are hidden, not only qualified: "cannot be confirmed:
                # 83,777.77" still put a wrong figure in front of the user.
                text = (LOW_RESOLUTION_NOTE.format(width=size[0], height=size[1]) + "\n"
                        + re.sub(r"\d", "?", text))
            texts[index] = text
    return texts
