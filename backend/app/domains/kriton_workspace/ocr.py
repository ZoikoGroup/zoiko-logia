"""OCR for scanned PDF pages (photos or scans with no text layer).

pypdf returns nothing for such a page, so the document had no evidence and
no figures. Each page is rendered (pypdfium2) and read with RapidOCR, both
pip-only with bundled models, so nothing is sent to an external service.

Text boxes are rebuilt into lines by their vertical position, and boxes on
one line that are clearly apart are joined with a tab. A scanned table thus
comes out as tab-separated rows, the same shape the Word / Excel extractors
write, so retrieval and verified figures (orchestration/document_figures.py)
read it like any other table.

An OCR outcome is never silent. OCRError carries a machine-readable code:
OCR_MISSING_DEPENDENCY (rapidocr-onnxruntime is not installed) and
OCR_INITIALIZATION_FAILED (installed, but the engine does not start) are
server faults; IMAGE_UNREADABLE (the bytes are not a decodable image) and
OCR_NO_TEXT_FOUND (OCR ran and read nothing legible) are about the file. A
missing package used to look exactly like an unreadable image ("No readable
text or cells were found"), so a server without OCR rejected every image.
One page that fails inside an otherwise readable scan is still skipped.
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


OCR_MISSING_DEPENDENCY = "OCR_MISSING_DEPENDENCY"
OCR_INITIALIZATION_FAILED = "OCR_INITIALIZATION_FAILED"
IMAGE_UNREADABLE = "IMAGE_UNREADABLE"
OCR_NO_TEXT_FOUND = "OCR_NO_TEXT_FOUND"
SERVER_FAULTS = frozenset({OCR_MISSING_DEPENDENCY, OCR_INITIALIZATION_FAILED})


class OCRError(RuntimeError):
    """An OCR outcome that is not text; code says which (see the module docstring)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

    @property
    def server_fault(self) -> bool:
        return self.code in SERVER_FAULTS


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                logger.error("OCR unavailable: rapidocr-onnxruntime is not installed")
                raise OCRError(OCR_MISSING_DEPENDENCY,
                               "OCR is not installed on this server (the rapidocr-onnxruntime package is missing), "
                               "so images and scanned pages cannot be read.") from exc
            try:
                _engine = RapidOCR()
            except Exception as exc:  # noqa: BLE001 — a model file or system library the engine needs
                logger.error("OCR unavailable: the engine failed to start", exc_info=True)
                raise OCRError(OCR_INITIALIZATION_FAILED,
                               f"OCR is installed on this server but could not start ({type(exc).__name__}), "
                               "so images and scanned pages cannot be read.") from exc
        return _engine


def ocr_status() -> dict:
    """{"state": "READY"} or the failure's code and message: for /health/ocr."""
    try:
        _get_engine()
    except OCRError as exc:
        return {"state": exc.code, "message": str(exc)}
    return {"state": "READY"}


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
    labels (Q1 Q2 Q3 Q4, or words with a value over each); "" otherwise."""
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
    if len(labels) < 2 or any(_CHART_NUMBER.match(label["text"]) or len(label["text"]) > 20 for label in labels):
        return ""
    # Period labels (Q1, Jan, 2024) are a chart's axis whatever is above them.
    # Other words (Software, Hardware) count only when every one has exactly
    # one number straight above it: their values were listed by bar height,
    # apart from the labels, and paired left to right by the reader.
    periods = all(_PERIOD_LABEL.match(label["text"]) for label in labels)
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
    if not periods and len(values) < len(labels):
        return ""
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
    """The image's text, led by any notes on what may be misread."""
    import numpy

    result, _ = _get_engine()(numpy.asarray(image))
    text = page_text(result or [])
    notes = reading_notes(result or [], text) if text else ""
    return f"{notes}\n{text}" if notes else text


# OCR reads a comma as a dot with high confidence: "5,000" came back as
# "5.000" at 0.94, and a blurred "$3,618.47" as "S3.618.47" at 0.96 (probed
# 4 Nov 2026). Such figures are named so they are confirmed, not used.
_DOTTED_THOUSANDS = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+\.\d{1,2}(?![\d.,])|(?<![\d.,])\d{1,3}(?:\.\d{3}){2,}(?![\d.,])")
_DOT_OR_COMMA = re.compile(r"(?<![\d.,$£€₹])\d{1,3}\.\d{3}(?![\d.,])")
# An amount whose $ was read as S ("S3.618.47"), not a code like "l1S5".
_S_FOR_DOLLAR = re.compile(r"(?<![A-Za-z0-9])S(?=\d[\d,]*[.,]\d)")
# A box read with less confidence than this is named as unreliable. Sharp
# printed text reads at 0.89 or more; a Hindi line came back as "可 TqIf 5,000"
# at 0.77 (this reader knows Latin and Chinese scripts only).
LOW_CONFIDENCE = 0.85
_CJK = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")


def reading_notes(boxes: list[tuple[list, str, float]], text: str) -> str:
    """Notes naming what in this reading may be wrong: figures whose comma or
    dot is unclear, and text read with low confidence or in mixed scripts.
    "" when there is nothing to say."""
    notes = []
    invalid = sorted(set(_DOTTED_THOUSANDS.findall(text)))
    unclear = sorted(set(_DOT_OR_COMMA.findall(text)) - set(invalid))
    dollar = sorted({match.group(0) + text[match.end():match.end() + 8].split()[0] for match in _S_FOR_DOLLAR.finditer(text)})
    if invalid or unclear or dollar:
        parts = [f'"{n}" is not a valid number as read (a comma may have been read as a dot)' for n in invalid]
        parts += [f'"{n}" may be {n.replace(".", ",")} (a comma read as a dot) or {n}' for n in unclear]
        parts += [f'"{n}" may begin with a $ read as S' for n in dollar]
        notes.append("[Check these figures before using them: " + "; ".join(parts) + ". Ask the user to confirm them; "
                     "do not state them as exact.]")
    # A one- or two-character box ("1" in a Qty column) reads with lower
    # confidence whatever its quality; only longer text is judged.
    doubtful = [t.strip() for _, t, score in boxes
                if len((t or "").strip()) >= 3 and MIN_CONFIDENCE <= float(score) < LOW_CONFIDENCE]
    doubtful += [t.strip() for _, t, score in boxes if (t or "").strip() and float(score) >= LOW_CONFIDENCE
                 and _CJK.search(t) and _LATIN_WORD.search(t)]
    if doubtful:
        quoted = "; ".join(f'"{t}"' for t in doubtful[:6])
        notes.append(f"[Low-confidence reading: {quoted} may be misread (handwriting, decoration, or a script this "
                     "reader does not support, such as Devanagari). Do not rely on these parts; ask the user for "
                     "the text or a clearer copy.]")
    return "\n".join(notes)


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


# A blurred image is as unreliable as a small one, whatever its pixel size:
# OCR misread "$3,618.47" as "S3.618.47" with 0.96 confidence. Sharpness is
# the typical edge step relative to the image's contrast: sharp, faint, tiny,
# rotated and JPEG-compressed text measured 0.71 or more; digits were
# misread from about 0.10; the H03 scanned invoice measured 0.09.
MIN_SHARPNESS = 0.15
BLURRED_NOTE = ("[Blurred image: the text below was read unreliably (sharpness {sharpness:.2f}) and its digits are "
                "shown as ?. Do not state or guess any amount, date or reference from it; say it cannot be read "
                "reliably and ask for a clearer copy or the original file.]")


def image_sharpness(image) -> float | None:
    """How sharp the image's edges are (about 0.9 for crisp text, under 0.15
    when blurred), or None for an image with too few edges to measure."""
    import numpy

    grey = numpy.asarray(image.convert("L"), dtype=float)
    contrast = float(grey.max() - grey.min())
    if contrast < 1:
        return None
    steps = numpy.concatenate([numpy.abs(numpy.diff(grey, axis=1)).ravel(), numpy.abs(numpy.diff(grey, axis=0)).ravel()])
    edges = steps[steps > contrast * 0.05]
    if edges.size < 50:
        return None
    return float(numpy.percentile(edges, 90) / contrast)


def _page_image_sharpness(content: bytes, page_index: int) -> float | None:
    """The sharpness of the largest image on a PDF page, measured on the
    embedded image itself (rendering the page would soften it)."""
    try:
        import io

        from pypdf import PdfReader

        images = PdfReader(io.BytesIO(content)).pages[page_index].images
        largest = max(images, key=lambda image: image.image.size[0] * image.image.size[1]) if images else None
        return image_sharpness(largest.image) if largest is not None else None
    except Exception:
        return None


def _mark_low_resolution(text: str, size: tuple[int, int] | None, sharpness: float | None = None) -> str:
    if size and max(size) < MIN_SCAN_PIXELS:
        # The digits are hidden, not only qualified: "cannot be confirmed:
        # 83,777.77" still put a wrong figure in front of the user.
        return LOW_RESOLUTION_NOTE.format(width=size[0], height=size[1]) + "\n" + re.sub(r"\d", "?", text)
    if sharpness is not None and sharpness < MIN_SHARPNESS:
        # With every digit hidden, a note about which figures to check says nothing.
        kept = "\n".join(line for line in text.splitlines() if not line.startswith("[Check these figures"))
        return BLURRED_NOTE.format(sharpness=sharpness) + "\n" + re.sub(r"\d", "?", kept)
    return text


# OCR reads small text badly; a small image is enlarged to about this width.
MIN_OCR_WIDTH = 1400


def ocr_image_bytes(content: bytes) -> str:
    """The OCR text of an uploaded PNG or JPEG image (QA group H asks for
    screenshots, charts and receipts). Raises OCRError, never returns "":
    OCR unavailable, an undecodable file, or nothing legible are each said."""
    import io

    from PIL import Image, ImageOps, UnidentifiedImageError

    _get_engine()
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise OCRError(IMAGE_UNREADABLE, "The file could not be opened as a PNG or JPEG image; "
                                         "it may be damaged or in another format.") from exc
    size, sharpness = image.size, image_sharpness(image)       # measured before any enlarging
    if size[0] < MIN_OCR_WIDTH:
        scale = MIN_OCR_WIDTH / size[0]
        image = image.resize((MIN_OCR_WIDTH, round(size[1] * scale)), Image.LANCZOS)
    text = ocr_image(image)
    if not text.strip():
        raise OCRError(OCR_NO_TEXT_FOUND, "OCR read the image but found no legible text. "
                                          "Upload a clearer image or the original document.")
    return _mark_low_resolution(text, size, sharpness)


def ocr_pdf_pages(content: bytes, page_indexes: list[int]) -> dict[int, str]:
    """{page index: OCR text} for the given (0-based) pages; a page that
    fails on its own is left out. A page whose scan is too small to read
    reliably starts with a note saying so. Raises OCRError when OCR itself
    is unavailable."""
    texts: dict[int, str] = {}
    _get_engine()           # OCRError when OCR is missing or does not start: the caller decides
    for index in page_indexes[:MAX_OCR_PAGES]:
        try:
            text = ocr_image(_render_page(content, index))
        except Exception:
            logger.warning("OCR failed on PDF page %s", index + 1, exc_info=True)
            continue
        if text:
            texts[index] = _mark_low_resolution(text, _page_image_size(content, index),
                                                _page_image_sharpness(content, index))
    return texts
