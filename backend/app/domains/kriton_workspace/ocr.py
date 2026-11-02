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


# A chart is read top to bottom like any page, which mixes the axis scale
# with the values printed on the bars: "3500 / 3,100 / 3000 / 2,500 …" was
# answered as Q1 3,500 … Q4 2,100, with Q1 highest (QA case H01). A value
# printed on a bar sits straight above its category label, so values are
# matched to labels by position; the axis scale is a column of its own.
_CHART_NUMBER = re.compile(r"^[$£€₹]?-?\d[\d,]*(?:\.\d+)?%?$")
_PERIOD_LABEL = re.compile(r"^(?:Q[1-4]|H[12]|FY\s?\d{2,4}|(?:19|20)\d{2}|"
                           r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*$", re.IGNORECASE)


def _number(text: str):
    from decimal import Decimal, InvalidOperation

    try:
        return Decimal(re.sub(r"[^\d.-]", "", text))
    except InvalidOperation:
        return None


def chart_note(boxes: list[tuple[list, str, float]]) -> str:
    """A note naming each chart category's printed value, or saying that the
    chart prints no values, when the page's lowest line is a row of category
    labels (Q1 Q2 Q3 Q4); "" for any other page."""
    items = []
    for points, text, score in boxes:
        if (text or "").strip() and float(score) >= MIN_CONFIDENCE:
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            items.append({"text": text.strip(), "x": (min(xs) + max(xs)) / 2, "y": (min(ys) + max(ys)) / 2,
                          "h": max(ys) - min(ys)})
    if len(items) < 3:
        return ""
    height = statistics.median(item["h"] for item in items) or 1.0
    bottom = max(item["y"] for item in items)
    labels = sorted((item for item in items if bottom - item["y"] <= height * 0.5), key=lambda item: item["x"])
    if (len(labels) < 2 or any(_CHART_NUMBER.match(label["text"]) or len(label["text"]) > 15 for label in labels)
            or not all(_PERIOD_LABEL.match(label["text"]) for label in labels)):
        return ""
    spacing = min(b["x"] - a["x"] for a, b in zip(labels, labels[1:]))
    numbers = [item for item in items if item["y"] < bottom - height * 0.5 and _CHART_NUMBER.match(item["text"])]
    values, used = {}, []
    for label in labels:
        above = [item for item in numbers if abs(item["x"] - label["x"]) <= spacing * 0.3]
        if len(above) > 1:
            return ""      # more than one number over a label: not a simple chart
        if above:
            values[label["text"]] = above[0]["text"]
            used.append(above[0])
    scale = [item["text"] for item in numbers if not any(item is chosen for chosen in used)]
    names = ", ".join(label["text"] for label in labels)
    if not values:
        return (f"[Chart: categories {names} are shown, but no value is printed for any of them"
                + (" and the axis scale is not shown" if not scale else
                   "; reading one off the axis scale would only be an estimate")
                + ". Do not state values, growth rates or percentages from this chart as exact; say they cannot be "
                  "read from the image and ask for the underlying figures.]")
    listed = "; ".join(f"{label['text']} {values[label['text']]}" for label in labels if label["text"] in values)
    note = f"[Chart read by position: the value printed above each category label is {listed}"
    amounts = [_number(values[label["text"]]) for label in labels if label["text"] in values]
    if len(values) == len(labels) and all(amount is not None for amount in amounts):
        total = sum(amounts)
        note += f"; the printed values add up to {total:,}" if "," in "".join(values.values()) else \
            f"; the printed values add up to {total}"
    missing = [label["text"] for label in labels if label["text"] not in values]
    if missing:
        note += f"; no value is printed for {', '.join(missing)}"
    if scale:
        note += f". The other numbers ({', '.join(scale[:8])}) are the axis scale, not values"
    return note + ".]"


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
    return page_text(result or [])


def page_text(boxes: list[tuple[list, str, float]]) -> str:
    """The page's OCR text; a chart's starts with its chart note."""
    text = lines_from_boxes(boxes)
    note = chart_note(boxes)
    if not (note and text):
        return text
    # The note holds every number of the chart. Left in the page text, they
    # were paired with the line above ("Revenue-$11,000 3,500", QA H02) and
    # summed as the quarters.
    words = lines_from_boxes([box for box in boxes if not _CHART_NUMBER.match((box[1] or "").strip())])
    return f"{note}\n{words}"


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


def _mark_low_resolution(text: str, size: tuple[int, int] | None) -> str:
    if size and max(size) < MIN_SCAN_PIXELS:
        # The digits are hidden, not only qualified: "cannot be confirmed:
        # 83,777.77" still put a wrong figure in front of the user.
        return LOW_RESOLUTION_NOTE.format(width=size[0], height=size[1]) + "\n" + re.sub(r"\d", "?", text)
    return text


# OCR reads small text badly; a small image is enlarged to about this width.
MIN_OCR_WIDTH = 1400


def ocr_image_bytes(content: bytes) -> str:
    """The OCR text of an uploaded PNG or JPEG image (QA group H asks for
    screenshots, charts and receipts), or "" when OCR is unavailable."""
    import io

    from PIL import Image, ImageOps

    try:
        _get_engine()
    except Exception:
        logger.warning("OCR is unavailable; the image stays without text", exc_info=True)
        return ""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
    size = image.size
    if size[0] < MIN_OCR_WIDTH:
        scale = MIN_OCR_WIDTH / size[0]
        image = image.resize((MIN_OCR_WIDTH, round(size[1] * scale)), Image.LANCZOS)
    text = ocr_image(image)
    return _mark_low_resolution(text, size) if text else text


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
            texts[index] = _mark_low_resolution(text, _page_image_size(content, index))
    return texts
