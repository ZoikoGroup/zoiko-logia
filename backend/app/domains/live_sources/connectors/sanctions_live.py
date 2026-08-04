"""Ask-Kriton adapter for name-candidate lookup in cached sanctions snapshots."""
from __future__ import annotations

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.feed_schemas import SanctionsMatch, SanctionsSnapshot
from app.domains.live_sources.sanctions_service import find_candidates
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse

# The catalogue requires every screening record to carry the list version,
# the update timestamp, the matching method, the identifiers, and the source
# URL. Version, timestamp and URL travel in NormalizedResponse's own fields;
# method and identifiers have no field of their own, so they are stated in
# the value text that reaches both the model and the citation.
_REVIEW_NOTICE = (
    "This is a screening candidate for human review, not a sanctions finding "
    "and not clearance."
)


def _describe(match: SanctionsMatch) -> str:
    entry = match.entry
    matched_on = (
        f'matched on identifier: "{match.matched_identifier}"'
        if match.method == "exact_identifier" and match.matched_identifier
        else f'matched on name: "{match.matched_name}"'
    )
    parts = [
        f"Candidate: {entry.primary_name}",
        matched_on,
        f"matching method: {match.method} (score {match.score:g})",
        f"type: {entry.entity_type}",
        f"programs: {', '.join(entry.programs) or 'not stated'}",
    ]
    # Identifiers are the difference between "someone with this name is
    # listed" and "this party is listed". Their absence is stated rather
    # than omitted, so a reviewer is never left to assume an identifier
    # check happened when none was possible.
    parts.append(
        f"identifiers on record: {'; '.join(entry.identifiers)}" if entry.identifiers
        else "identifiers on record: none published for this entry"
    )
    if entry.dates_of_birth:
        parts.append(f"date(s) of birth: {', '.join(entry.dates_of_birth)}")
    if entry.nationalities:
        parts.append(f"nationality: {', '.join(entry.nationalities)}")
    if entry.listed_on:
        parts.append(f"listed on: {entry.listed_on}")
    return "; ".join(parts)


def _value_text(
    name: str, snapshot: SanctionsSnapshot, matches: list[SanctionsMatch],
    identifiers: tuple[str, ...] = (),
) -> str:
    provenance = f"List version {snapshot.list_version}, synchronised {snapshot.fetched_at}."
    # The record must state what was compared, not just what was found. A
    # name-only screen and a name-plus-passport screen carry very different
    # weight, and an unqualified "no match" implies the stronger one.
    scope = (
        f"Screened on name and {len(identifiers)} supplied identifier"
        f"{'s' if len(identifiers) != 1 else ''}."
        if identifiers else "Screened on name only; no identifiers were supplied."
    )
    if not matches:
        return (
            f'No candidate was found for "{name}". {scope} {provenance} '
            "This is not sanctions clearance: transliterations and non-Latin scripts are "
            "not covered by name matching, and any identifier not supplied was not checked."
        )
    described = " | ".join(_describe(match) for match in matches)
    plural = "candidate" if len(matches) == 1 else "candidates"
    return f"{len(matches)} screening {plural}. {scope} {provenance} {described}. {_REVIEW_NOTICE}"


class SanctionsLiveConnector(LiveSourceConnector):
    def __init__(self, provider_key: str, display_name: str, landing_url: str) -> None:
        self.provider_key, self.display_name, self.landing_url = provider_key, display_name, landing_url

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        name = intent.company_query or ""
        # Bounded on purpose: a screening answer a person is meant to read
        # and act on degrades past a handful of candidates. The unbounded
        # result set belongs to a review tool, not to an answer.
        snapshot, matches = await find_candidates(
            self.provider_key, name, identifiers=intent.screening_identifiers, limit=5,
        )
        record_id = matches[0].entry.record_id if matches else f"no-match-{snapshot.list_version}"
        return NormalizedResponse(
            provider_key=self.provider_key, indicator_code=record_id,
            indicator_label=f"{self.display_name} screening",
            country_code=intent.country_code, country_label=intent.country_label,
            value=_value_text(name, snapshot, matches, intent.screening_identifiers), unit="",
            observation_period=snapshot.fetched_at, as_of=snapshot.fetched_at,
            source_url=self.landing_url,
            citation_title=f"{self.display_name} — official snapshot, list version {snapshot.list_version}",
            company_query=name,
        )
