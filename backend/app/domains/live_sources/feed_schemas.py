"""Normalized contracts for authoritative scheduled snapshot feeds."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class SanctionsEntry(BaseModel):
    provider_key: str
    record_id: str
    entity_type: str
    primary_name: str
    aliases: tuple[str, ...] = ()
    programs: tuple[str, ...] = ()
    listed_on: str | None = None
    # The catalogue requires screening to record the identifiers a match was
    # made against, not just a name. A name alone cannot distinguish two
    # people who share one, which is exactly the case where an unreviewed
    # "match" does real harm to the wrong person.
    identifiers: tuple[str, ...] = ()
    nationalities: tuple[str, ...] = ()
    dates_of_birth: tuple[str, ...] = ()
    source_url: HttpUrl

    @property
    def searchable_names(self) -> tuple[str, ...]:
        return (self.primary_name, *self.aliases)


# How a candidate was produced. Recorded on every result — including a
# no-match — because "we found nothing" is only meaningful alongside the
# method that found nothing, and the catalogue requires the matching method
# to be part of the screening record.
MatchMethod = Literal[
    # An identifier match is listed first because it is the strongest thing
    # this screening can produce: a passport or registration number
    # identifies a party, where a name merely describes one. Name matching
    # alone cannot tell two people who share a name apart, which is exactly
    # the case where acting on an unreviewed match harms the wrong person.
    "exact_identifier",
    "exact_primary_name",
    "exact_alias",
    "fuzzy_name",
    "no_match",
]


class SanctionsMatch(BaseModel):
    entry: SanctionsEntry
    method: MatchMethod
    # 1.0 for an exact normalised-name hit; the similarity ratio otherwise.
    score: float = Field(ge=0.0, le=1.0)
    # Which stored value actually matched — for an alias, fuzzy or
    # identifier hit this is not the primary name, and a reviewer needs to
    # see the string that triggered the candidate.
    matched_name: str
    # Set only for method="exact_identifier": the identifier as published on
    # the listing, so the record states what was compared rather than
    # implying a name match.
    matched_identifier: str | None = None


class SanctionsSnapshot(BaseModel):
    provider_key: str
    entries: list[SanctionsEntry]
    fetched_at: str
    source_url: HttpUrl
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def list_version(self) -> str:
        """Short, stable identifier for the exact list contents screened
        against — the audit record needs to name a version, and the content
        hash is the only thing the authorities publish that actually changes
        when and only when the list does."""
        return self.content_sha256[:12]
