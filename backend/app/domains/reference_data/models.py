"""
Immutable wrapper for external reference-data payloads.

Note: orchestration/schemas.py already defines a SourceBundle, but that one
is shaped for Kriton's internal retrieval/classification pipeline
(source_bundle_id, confidence_state, sources: list[SourceSummary], ...) and
doesn't fit a raw third-party API payload. Rather than overload that name
with a second, unrelated meaning, this is a distinct, smaller model —
ReferenceSourceBundle — reserved for wrapping external reference sources
like Treasury Fiscal Data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReferenceSourceBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_name: str
    source_url: str
    retrieved_at: datetime = Field(default_factory=_utc_now)
    data: list[dict[str, Any]]
    licence_status: str = "public_no_auth"
