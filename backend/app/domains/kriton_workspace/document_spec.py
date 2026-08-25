"""Validated, format-neutral document layout produced from grounded content."""
from __future__ import annotations

import base64
import io
import re
import unicodedata
from typing import Literal

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field, model_validator


class DocumentBlock(BaseModel):
    type: Literal["heading", "paragraph", "bullets", "table", "chart", "flow_diagram"]
    text: str = ""
    title: str = ""
    level: int = 1
    items: list[str] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    image_png: bytes | None = None
    alt_text: str = ""

    @model_validator(mode="after")
    def validate_content(self):
        if self.type == "table":
            if not self.headers:
                raise ValueError("A table requires headers")
            width = len(self.headers)
            if any(len(row) != width for row in self.rows):
                raise ValueError("Every table row must match the header width")
        if self.type in {"chart", "flow_diagram"} and not self.image_png:
            raise ValueError("Visual blocks require a rendered PNG asset")
        return self


class DocumentSpec(BaseModel):
    title: str
    blocks: list[DocumentBlock]
    source_locations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_document(self):
        if not self.title.strip() or not self.blocks:
            raise ValueError("A generated document requires a title and content")
        searchable = " ".join(
            [self.title]
            + [block.text for block in self.blocks]
            + [item for block in self.blocks for item in block.items]
            + [cell for block in self.blocks for row in block.rows for cell in row]
        )
        if re.search(r"\b(?:TBD|TODO|NaN)\b|(?:USD|GBP|EUR|\$|£|€)\s*\?", searchable, re.IGNORECASE):
            raise ValueError("Generated document contains an unresolved placeholder")
        return self


_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_HORIZONTAL_RULE = re.compile(r"^\s*(?:-{3,}|_{3,}|\*{3,})\s*$")
_REFERENCE_MARKER = re.compile(r"\[\s*REF(?:ERENCE)?\s*[-:#]?\s*\d+\s*\]", re.IGNORECASE)


def normalize_document_text(text: str) -> str:
    """Remove internal markers and normalize typography for every export format."""
    normalized = unicodedata.normalize("NFC", str(text or ""))
    normalized = normalized.translate(str.maketrans({
        "\u00a0": " ",  # no-break space
        "\u2007": " ",  # figure space
        "\u202f": " ",  # narrow no-break space
        "\u200b": "",   # zero-width space
        "\ufeff": "",   # byte-order/zero-width no-break mark
        "\u2010": "-",  # hyphen
        "\u2011": "-",  # non-breaking hyphen
        "\u2012": "-",  # figure dash
        "\u2212": "-",  # minus sign
    }))
    normalized = _REFERENCE_MARKER.sub("", normalized)
    normalized = re.sub(r"\(\s*\)", "", normalized)
    normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized.strip()


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _chart_png(title: str, values: dict[str, float]) -> bytes:
    width, height = 1200, 675
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=17)
    draw.text((55, 35), title, fill="#153b4a", font=font)
    items = list(values.items())[:10]
    maximum = max((abs(value) for _, value in items), default=1) or 1
    chart_left, chart_top, chart_right, chart_bottom = 245, 100, 1125, 610
    draw.line((chart_left, chart_top, chart_left, chart_bottom), fill="#78909c", width=2)
    row_height = max(38, (chart_bottom - chart_top) // max(len(items), 1))
    for index, (label, value) in enumerate(items):
        y = chart_top + index * row_height + 8
        bar_width = int((chart_right - chart_left - 130) * abs(value) / maximum)
        draw.text((55, y), str(label)[:22], fill="#263238", font=small)
        draw.rounded_rectangle(
            (chart_left, y, chart_left + bar_width, y + 25), radius=5,
            fill="#16799A",
        )
        draw.text((chart_left + bar_width + 12, y + 2), f"{value:,.2f}", fill="#263238", font=small)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _flow_png(title: str, labels: list[str]) -> bytes:
    width, height = 1200, 360
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    heading = ImageFont.load_default(size=22)
    font = ImageFont.load_default(size=18)
    draw.text((55, 30), title, fill="#153b4a", font=heading)
    count = max(len(labels), 1)
    box_width = min(230, (width - 110 - (count - 1) * 50) // count)
    x = 55
    y = 135
    for index, label in enumerate(labels):
        draw.rounded_rectangle((x, y, x + box_width, y + 90), radius=12, fill="#e8f4f7", outline="#16799A", width=3)
        draw.multiline_text((x + 15, y + 28), label[:32], fill="#153b4a", font=font, align="center")
        if index < count - 1:
            start = x + box_width
            end = start + 50
            draw.line((start + 5, y + 45, end - 7, y + 45), fill="#F3A712", width=5)
            draw.polygon([(end - 7, y + 36), (end + 5, y + 45), (end - 7, y + 54)], fill="#F3A712")
        x += box_width + 50
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_document_spec(
    title: str, narrative: str, analysis: dict, request_text: str = ""
) -> DocumentSpec:
    """Parse grounded Markdown once, then enrich it with verified visuals."""
    lines = narrative.splitlines()
    blocks: list[DocumentBlock] = []
    paragraph: list[str] = []
    bullets: list[str] = []

    def flush_text() -> None:
        nonlocal paragraph, bullets
        if paragraph:
            blocks.append(DocumentBlock(type="paragraph", text=" ".join(paragraph)))
            paragraph = []
        if bullets:
            blocks.append(DocumentBlock(type="bullets", items=bullets))
            bullets = []

    index = 0
    while index < len(lines):
        raw = lines[index].rstrip()
        stripped = raw.strip()
        if not stripped:
            flush_text()
            index += 1
            continue
        if _HORIZONTAL_RULE.fullmatch(stripped):
            flush_text()
            index += 1
            continue
        if stripped.startswith("#"):
            flush_text()
            hashes = len(stripped) - len(stripped.lstrip("#"))
            blocks.append(DocumentBlock(
                type="heading", level=min(max(hashes, 1), 3),
                text=normalize_document_text(stripped.lstrip("# ")),
            ))
            index += 1
            continue
        if index + 1 < len(lines) and "|" in stripped and _TABLE_SEPARATOR.match(lines[index + 1]):
            flush_text()
            headers = [normalize_document_text(cell) for cell in _cells(stripped)]
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                row = [normalize_document_text(cell) for cell in _cells(lines[index])]
                if len(row) == len(headers):
                    rows.append(row)
                index += 1
            blocks.append(DocumentBlock(type="table", headers=headers, rows=rows))
            continue
        if stripped.startswith(("- ", "* ")):
            if paragraph:
                flush_text()
            bullets.append(normalize_document_text(stripped[2:].strip()))
        else:
            if bullets:
                flush_text()
            paragraph.append(normalize_document_text(stripped))
        index += 1
    flush_text()

    product_values = analysis.get("product_revenue") or {}
    customer_values = analysis.get("customer_revenue") or {}
    if product_values:
        blocks.append(DocumentBlock(
            type="chart", title="Revenue by Product", alt_text="Bar chart of verified product revenue",
            image_png=_chart_png("Revenue by Product", product_values),
        ))
    elif customer_values:
        blocks.append(DocumentBlock(
            type="chart", title="Revenue by Customer", alt_text="Bar chart of verified customer revenue",
            image_png=_chart_png("Revenue by Customer", customer_values),
        ))

    lowered = request_text.lower()
    if any(term in lowered for term in ("flow diagram", "flowchart", "process diagram", "workflow diagram")):
        labels = ["Uploaded evidence", "Verified analysis", "Management findings", "Recommendations"]
        blocks.append(DocumentBlock(
            type="flow_diagram", title="Report Evidence Flow", alt_text="Flow from evidence to recommendations",
            image_png=_flow_png("Report Evidence Flow", labels),
        ))
    return DocumentSpec(
        title=normalize_document_text(title),
        blocks=blocks,
        source_locations=[
            normalize_document_text(location)
            for location in analysis.get("evidence_locations", [])
            if normalize_document_text(location)
        ],
    )


def visual_as_data_uri(block: DocumentBlock) -> str:
    encoded = base64.b64encode(block.image_png or b"").decode("ascii")
    return f"data:image/png;base64,{encoded}"
