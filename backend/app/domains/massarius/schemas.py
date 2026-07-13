"""
Massarius™ retrieval and evidence subsystem — canonical schemas (ZL-ENG-03 §5, Gate 1).

Every Massarius™ module imports its shared shapes from here. The types
themselves are defined in app/orchestration/schemas.py, not redefined here:
that file already anchors the live AskKritonResponse contract (ZL-ENG-02 §12)
and is the one place SourceBundle can safely change shape without a second,
competing definition drifting out of sync. This module exists so the file
`app/domains/massarius/schemas.py` the spec names is a real, importable path —
it must NOT define local variants of these types (that would itself violate
Gate 1).
"""
from __future__ import annotations

from app.orchestration.schemas import (
    RetrievalMethod,
    RetrievalPlan,
    SourceCandidate,
    SourceSummary,
    SourceDisplayState,
    SourceBundle,
    CitationBinding,
    CitationMap,
    ValidationResult,
    RedactionReport,
)

__all__ = [
    "RetrievalMethod",
    "RetrievalPlan",
    "SourceCandidate",
    "SourceSummary",
    "SourceDisplayState",
    "SourceBundle",
    "CitationBinding",
    "CitationMap",
    "ValidationResult",
    "RedactionReport",
]
