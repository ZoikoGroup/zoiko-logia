"""Contracts for authoritative APIs that return records rather than metrics."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class EvidenceSearchIntent(BaseModel):
    provider_key: str
    query: str = Field(min_length=2, max_length=500)
    jurisdiction: str = ""
    record_types: tuple[str, ...] = ()
    page_size: int = Field(default=10, ge=1, le=25)


class EvidenceRecord(BaseModel):
    provider_key: str
    record_id: str
    record_type: str
    title: str
    summary: str = ""
    jurisdiction: str
    published_at: str | None = None
    effective_at: str | None = None
    source_url: HttpUrl
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceSearchResponse(BaseModel):
    provider_key: str
    query: str
    records: list[EvidenceRecord]
    fetched_at: str
