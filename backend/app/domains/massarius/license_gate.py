"""
Massarius™ retrieval and evidence subsystem — licence eligibility gate
(ZL-ENG-03 §5.3, Checkpoints A and B).

Checkpoint A (prefilter): screens retrieved candidates for eligibility —
licence state, authority level, tenant-private boundary — before they're
allowed into bundle construction. Ineligible sources are filtered, not just
flagged.

Checkpoint B (display resolution): for sources that pass Checkpoint A,
resolves each one's SourceDisplayState ("show" | "summarise" |
"internal_reasoning_only") based on the same licence/authority data.

Flagged deviation from the spec's literal ordering (ZL-ENG-03 §4, §6): the
spec wants Checkpoint A to run *before* retrieval, filtering what
`retrieval.py` is even allowed to look at. The live keyword_mvp retrieval
(app/orchestration/retrieve.py) is out of scope to modify, and it already
does its own DB query and status filtering internally before this module
ever sees anything. So Checkpoint A here runs immediately *after* retrieval
returns, screening its output — genuinely eligibility-filtering, but not
literally pre-query. True pre-retrieval filtering would require retrieve.py
itself to call into this module before running its query.

Also flagged: retrieve.py's returned SourceBundle.sources is a SourceSummary
list (id/title/category/jurisdiction_scope/version_label/status only) — it
does not carry licence_state/authority_level/is_tenant_private, so those
fields can't be read off the bundle retrieve.py already built. This module
re-queries app.domains.source_library.models.Source directly by id to get
them — a small extra read, but it means zero changes to retrieve.py or
source_library's existing service functions.

Must NOT: perform retrieval itself, do risk classification, or construct the
final SourceBundle (bundle_builder.py's job) — only decide what's eligible
and how each source may be displayed.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.massarius.errors import LicenceDenied
from app.domains.source_library.models import Source
from app.domains.live_sources.models import LiveSourceProvider
from app.orchestration.schemas import SourceDisplayState, SourceSummary


@dataclass
class LicenceCheckResult:
    eligible: list[SourceSummary]
    excluded: list[SourceSummary]
    exclusion_reasons: dict[str, str]           # source_id -> reason_code
    display_states: dict[str, SourceDisplayState]  # source_id -> state, eligible sources only


async def _fetch_licence_fields(db: AsyncSession, source_ids: list[str]) -> dict[str, Source]:
    if not source_ids:
        return {}
    result = await db.execute(select(Source).where(Source.id.in_(source_ids)))
    return {row.id: row for row in result.scalars().all()}


def _live_provider_key_of(source_id: str) -> str | None:
    """live_sources.service.make_live_source_id() builds ids as
    "live-{provider_key}-{indicator_code}-{country_code}" — provider_key
    itself uses underscores (e.g. "world_bank"), never dashes, so it's always
    the second dash-separated segment."""
    parts = source_id.split("-")
    if len(parts) < 2 or parts[0] != "live":
        return None
    return parts[1]


async def _fetch_live_provider_fields(db: AsyncSession, provider_keys: set[str]) -> dict[str, LiveSourceProvider]:
    """One-to-one analogue of _fetch_licence_fields(), against
    LiveSourceProvider instead of Source — a LiveSourceProvider row marked
    DISABLED (or licence_state='restricted') must exclude a live source even
    if a stale LiveFetchCache row still exists for it."""
    if not provider_keys:
        return {}
    result = await db.execute(
        select(LiveSourceProvider).where(LiveSourceProvider.provider_key.in_(provider_keys))
    )
    return {row.provider_key: row for row in result.scalars().all()}


async def check_eligibility(
    db: AsyncSession,
    sources: list[SourceSummary],
    *,
    tenant_id: str,
    allow_tenant_private: bool = True,
) -> LicenceCheckResult:
    """
    Checkpoint A + B combined: filters ineligible sources and resolves
    display states for the rest. Raises nothing itself — callers that want
    a hard stop on any denial should inspect `excluded` and raise
    LicenceDenied themselves (see orchestration/service.py's wiring), since
    "some sources excluded" is often a normal, non-fatal outcome (it can
    just lower confidence_state) while "the caller wants zero tolerance for
    a specific denial class" is a policy decision made at the call site.

    Live external-data sources (SourceSummary.source_type == "live_api",
    from app.domains.live_sources) are checked against LiveSourceProvider
    registry rows instead of source_library.Source — same eligibility
    vocabulary (licence_state/is_tenant_private), different table.
    """
    doc_sources = [s for s in sources if s.source_type != "live_api"]
    live_sources = [s for s in sources if s.source_type == "live_api"]

    fields_by_id = await _fetch_licence_fields(db, [s.id for s in doc_sources])
    live_provider_keys = {pk for pk in (_live_provider_key_of(s.id) for s in live_sources) if pk}
    live_fields_by_provider = await _fetch_live_provider_fields(db, live_provider_keys)

    eligible: list[SourceSummary] = []
    excluded: list[SourceSummary] = []
    exclusion_reasons: dict[str, str] = {}
    display_states: dict[str, SourceDisplayState] = {}

    for source in doc_sources:
        record = fields_by_id.get(source.id)
        if record is None:
            excluded.append(source)
            exclusion_reasons[source.id] = "source_record_not_found"
            continue

        if record.licence_state == "restricted":
            excluded.append(source)
            exclusion_reasons[source.id] = "licence_restricted"
            continue

        if record.is_tenant_private and record.tenant_id != tenant_id:
            excluded.append(source)
            exclusion_reasons[source.id] = "tenant_private_boundary"
            continue

        if record.is_tenant_private and not allow_tenant_private:
            excluded.append(source)
            exclusion_reasons[source.id] = "tenant_private_not_permitted_for_mode"
            continue

        eligible.append(source)
        display_states[source.id] = _resolve_display_state(record)

    for source in live_sources:
        provider_key = _live_provider_key_of(source.id)
        record = live_fields_by_provider.get(provider_key) if provider_key else None
        if record is None:
            excluded.append(source)
            exclusion_reasons[source.id] = "live_provider_not_found"
            continue

        if record.status != "ACTIVE":
            excluded.append(source)
            exclusion_reasons[source.id] = "live_provider_disabled"
            continue

        if record.licence_state == "restricted":
            excluded.append(source)
            exclusion_reasons[source.id] = "licence_restricted"
            continue

        if record.is_tenant_private and record.tenant_id != tenant_id:
            excluded.append(source)
            exclusion_reasons[source.id] = "tenant_private_boundary"
            continue

        eligible.append(source)
        display_states[source.id] = _resolve_live_display_state(record)

    return LicenceCheckResult(
        eligible=eligible,
        excluded=excluded,
        exclusion_reasons=exclusion_reasons,
        display_states=display_states,
    )


def _resolve_display_state(record: Source) -> SourceDisplayState:
    """Checkpoint B — per-source exposure resolution."""
    if record.licence_state == "unknown":
        return "internal_reasoning_only"
    if record.authority_level == "internal":
        return "summarise"
    return "show"


def _resolve_live_display_state(record: LiveSourceProvider) -> SourceDisplayState:
    """Checkpoint B for live sources — same vocabulary as _resolve_display_state."""
    if record.licence_state == "unknown":
        return "internal_reasoning_only"
    if record.authority_level == "internal":
        return "summarise"
    return "show"


def raise_if_denied(result: LicenceCheckResult, *, checkpoint: str = "A") -> None:
    """Convenience for a caller that wants Checkpoint A/B denial to be a hard
    stop (e.g. every eligible source got excluded) rather than a soft
    confidence-state signal."""
    if result.excluded and not result.eligible:
        raise LicenceDenied(
            checkpoint=checkpoint,  # type: ignore[arg-type]
            source_ids=[s.id for s in result.excluded],
            reason_code="all_candidates_denied",
        )
