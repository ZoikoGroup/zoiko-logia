"""Bounded PDF text extraction in an isolated native-reader process.

PDFium is not thread safe. Separate processes prevent concurrent public PDF
reads from sharing native state with each other or the upload/OCR pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def read_pdf_pages(content: bytes, *, seconds: float = 2.5) -> list[tuple[int, str]]:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())], input=content,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=seconds, check=True,
    )
    return [(int(index), str(text)) for index, text in json.loads(result.stdout)]


def _worker() -> None:
    import pypdfium2
    body = sys.stdin.buffer.read(8_000_001)
    if len(body) > 8_000_000:
        raise ValueError("PDF exceeds extraction limit")
    pages = []
    used = 0
    with pypdfium2.PdfDocument(body) as document:
        for index in range(min(len(document), 1000)):
            page = document[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded()
                finally:
                    textpage.close()
            finally:
                page.close()
            if text:
                remaining = 2_000_000 - used
                pages.append((index + 1, text[:remaining]))
                used += len(text)
            if used >= 2_000_000:
                break
    sys.stdout.write(json.dumps(pages))


if __name__ == "__main__":
    _worker()
