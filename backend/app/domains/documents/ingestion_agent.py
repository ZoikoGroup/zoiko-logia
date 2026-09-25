"""Bounded F6 document-ingestion planning and execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import os
from typing import Callable

import httpx

from app.domains.documents.extract import ExtractionError, Segment, extract

PARSER_VERSION = "f6.1"


@dataclass(frozen=True)
class AgentStep:
    capability: str
    reason: str
    targets: list[str]


@dataclass
class ExtractionOutcome:
    segments: list[Segment]
    status: str
    method: str
    coverage_ratio: float
    confidence: float
    review_reason: str | None
    steps: list[AgentStep]

    def plan_json(self) -> dict:
        return {"version": PARSER_VERSION, "steps": [asdict(step) for step in self.steps]}


OcrAdapter = Callable[[bytes, str, list[str]], list[Segment]]
_ocr_adapter: OcrAdapter | None = None


def register_ocr_adapter(adapter: OcrAdapter | None) -> None:
    """Register an approved provider adapter at application composition time."""
    global _ocr_adapter
    _ocr_adapter = adapter


def _http_ocr_adapter(data: bytes, extension: str, targets: list[str]) -> list[Segment]:
    """Provider-neutral HTTPS contract; secrets never enter the task payload."""
    url = os.getenv("DOCUMENT_OCR_URL", "").strip()
    if not url:
        return []
    key = os.getenv("DOCUMENT_OCR_API_KEY", "").strip()
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {key}"} if key else {},
        json={
            "content_base64": base64.b64encode(data).decode("ascii"),
            "extension": extension,
            "targets": targets,
        },
        timeout=float(os.getenv("DOCUMENT_OCR_TIMEOUT_SECONDS", "90")),
    )
    response.raise_for_status()
    payload = response.json()
    return [
        Segment(locator=str(item["locator"]), text=str(item["text"]),
                tabular=bool(item.get("tabular", False)))
        for item in payload.get("segments", [])
        if item.get("locator") and item.get("text")
    ]


def execute_plan(data: bytes, extension: str) -> ExtractionOutcome:
    steps = [AgentStep("document.inspect", "FORMAT_AND_NATIVE_TEXT_CHECK", ["document"])]
    try:
        segments = extract(data, extension)
        steps.append(AgentStep("document.extract_native", "NATIVE_TEXT_AVAILABLE", ["document"]))
        return ExtractionOutcome(segments, "ready", "native", 1.0, 1.0, None, steps)
    except ExtractionError as exc:
        message = str(exc)
        scan_like = extension.lower() in {".pdf", ".pptx"} and any(
            marker in message.lower() for marker in ("scan", "ocr", "images")
        )
        if not scan_like:
            raise

        steps.append(AgentStep("document.ocr_regions", "NATIVE_TEXT_UNAVAILABLE", ["document"]))
        adapter = _ocr_adapter or (_http_ocr_adapter if os.getenv("DOCUMENT_OCR_URL", "").strip() else None)
        if adapter is None:
            return ExtractionOutcome([], "needs_review", "ocr_required", 0.0, 0.0,
                                     "OCR is required but no approved OCR adapter is configured.", steps)
        segments = adapter(data, extension, ["document"])
        if not segments:
            return ExtractionOutcome([], "needs_review", "ocr", 0.0, 0.0,
                                     "OCR produced no reviewable text.", steps)
        return ExtractionOutcome(segments, "needs_review", "ocr", 1.0, 0.70,
                                 "OCR output requires reviewer approval before retrieval.", steps)
