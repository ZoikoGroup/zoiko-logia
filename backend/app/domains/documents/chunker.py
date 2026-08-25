"""
Turn extracted Segments into retrievable chunks.

Two strategies, chosen per segment rather than per file, because one file can
contain both kinds of content (a .docx with an embedded table):

  Prose     — pack whole paragraphs up to the size budget, then carry a short
              overlap into the next chunk so a sentence split across the seam
              is still findable from either side.

  Tabular   — cut on row boundaries and repeat the header row at the top of
              every chunk. This is the detail that decides whether a
              spreadsheet is usable: without the header, a chunk reads
              "Q3 | 4,200 | 1,180" and nothing in it says which column is
              revenue and which is tax.

Sizes are in characters, not tokens. Characters are what the extractors
produce, and the ratio is stable enough (~4 chars/token for English prose)
that a token-accurate count would buy nothing here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.domains.documents.extract import Segment

# 2,000 characters is roughly 500 tokens: large enough to hold a whole clause
# of a contract or a full paragraph of guidance with its context, small enough
# that eight of them plus the answering instructions still leave the model room
# to think.
CHUNK_CHARS = 2_000

# Carried from the end of one prose chunk into the start of the next.
OVERLAP_CHARS = 200

# Below this, a trailing fragment is appended to the previous chunk instead of
# becoming a chunk of its own — a 30-character chunk can outrank a real one on
# keyword density while carrying no usable context.
_MIN_CHUNK_CHARS = 120

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


@dataclass
class Chunk:
    ordinal: int
    content: str
    locator: str


def _split_prose(text: str) -> list[str]:
    """Pack paragraphs into chunk-sized pieces, keeping paragraph boundaries
    wherever possible and falling back to sentence boundaries for a paragraph
    that is itself larger than the budget."""
    pieces: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= CHUNK_CHARS:
            pieces.append(paragraph)
            continue
        # An oversized paragraph (common in PDFs, where the whole page arrives
        # as one block) is broken on sentence ends rather than mid-word.
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        buffer = ""
        for sentence in sentences:
            if len(buffer) + len(sentence) + 1 > CHUNK_CHARS and buffer:
                pieces.append(buffer.strip())
                buffer = sentence
            elif len(sentence) > CHUNK_CHARS:
                # A single sentence longer than the budget — a minified line, a
                # base64 blob. Hard-cut it; there is no better boundary.
                for start in range(0, len(sentence), CHUNK_CHARS):
                    pieces.append(sentence[start:start + CHUNK_CHARS])
                buffer = ""
            else:
                buffer = f"{buffer} {sentence}".strip()
        if buffer.strip():
            pieces.append(buffer.strip())

    # Pack the pieces up to the budget, then apply the overlap.
    packed: list[str] = []
    buffer = ""
    for piece in pieces:
        if buffer and len(buffer) + len(piece) + 2 > CHUNK_CHARS:
            packed.append(buffer)
            tail = buffer[-OVERLAP_CHARS:] if len(buffer) > OVERLAP_CHARS else buffer
            buffer = f"{tail}\n\n{piece}" if tail else piece
        else:
            buffer = f"{buffer}\n\n{piece}" if buffer else piece
    if buffer:
        packed.append(buffer)
    return packed


def _split_tabular(text: str) -> list[str]:
    """Cut on row boundaries, repeating the header row on every chunk."""
    rows = [r for r in text.splitlines() if r.strip()]
    if not rows:
        return []
    header = rows[0]
    body = rows[1:]
    if not body:
        return [header]

    # The header is prepended to every chunk, so it must be paid for out of the
    # budget. A pathological header wider than the whole budget would leave no
    # room for data, so it is capped.
    header_cost = min(len(header) + 1, CHUNK_CHARS // 2)

    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for row in body:
        if current and size + len(row) + 1 + header_cost > CHUNK_CHARS:
            chunks.append("\n".join([header, *current]))
            current, size = [], 0
        current.append(row)
        size += len(row) + 1
    if current:
        chunks.append("\n".join([header, *current]))
    return chunks


def chunk_segments(segments: list[Segment]) -> list[Chunk]:
    """Flatten extracted segments into ordered, retrievable chunks."""
    chunks: list[Chunk] = []
    for segment in segments:
        pieces = _split_tabular(segment.text) if segment.tabular else _split_prose(segment.text)
        pieces = [p.strip() for p in pieces if p.strip()]

        # Fold a too-short tail into its predecessor rather than emitting it.
        if len(pieces) > 1 and len(pieces[-1]) < _MIN_CHUNK_CHARS:
            pieces[-2] = f"{pieces[-2]}\n{pieces[-1]}"
            pieces.pop()

        for index, piece in enumerate(pieces, start=1):
            # Only number the locator when the segment produced more than one
            # chunk — "page 4" is clearer than "page 4 (part 1 of 1)".
            locator = segment.locator
            if len(pieces) > 1:
                locator = f"{segment.locator} (part {index} of {len(pieces)})"
            chunks.append(Chunk(ordinal=len(chunks), content=piece, locator=locator))
    return chunks
