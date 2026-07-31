"""Normalized contracts for authoritative scheduled snapshot feeds."""
from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class SanctionsEntry(BaseModel):
    provider_key: str
    record_id: str
    entity_type: str
    primary_name: str
    aliases: tuple[str, ...] = ()
    programs: tuple[str, ...] = ()
    listed_on: str | None = None
    source_url: HttpUrl

    @property
    def searchable_names(self) -> tuple[str, ...]:
        return (self.primary_name, *self.aliases)


class SanctionsSnapshot(BaseModel):
    provider_key: str
    entries: list[SanctionsEntry]
    fetched_at: str
    source_url: HttpUrl
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
