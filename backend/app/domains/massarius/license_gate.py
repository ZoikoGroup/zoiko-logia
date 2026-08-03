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

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.live_sources.authority import rank_for_document
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
    # Bundle-level rollup of the real per-source licence/authority data this
    # module just read from the DB — the only trustworthy source for these
    # two fields. Found during the enterprise-grade consistency audit:
    # orchestration/retrieve.py independently guesses a bundle-wide
    # authority_level from query category ("primary" if category in
    # ("audit", "tax") else "secondary") and hardcodes licence_state to
    # "permitted", and bundle_builder.py was copying that guess straight
    # into the final SourceBundle — meaning answer_validator.py's Authority
    # ceiling check (source_bundle.authority_level != "primary") was gated
    # on a category heuristic, not on what Checkpoint A/B actually found
    # for the sources that survived. A source truly tagged "internal" in
    # the DB could still produce a bundle claiming "primary", silently
    # disabling the ceiling check for absolute-certainty language.
    authority_level: str = "primary"
    licence_state: str = "permitted"
    # source_id -> the catalogue's 1-6 authority rank, for eligible document
    # sources. Derived from the Source rows this module already reads for
    # eligibility, so it costs no extra query — and without it the authority
    # hierarchy (live_sources/authority.py) has nothing to rank a
    # document-only bundle by, and silently falls back to retrieval order.
    authority_ranks: dict[str, int] = field(default_factory=dict)


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
    authority_ranks: dict[str, int] = {}
    eligible_authority_levels: list[str] = []
    eligible_licence_states: list[str] = []

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
        authority_ranks[source.id] = rank_for_document(record.authority_level, record.source_class)
        eligible_authority_levels.append(record.authority_level)
        eligible_licence_states.append(record.licence_state)

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
        # The registry already holds the catalogue's rank for a live source,
        # so it is read rather than derived.
        authority_ranks[source.id] = record.authority_rank
        eligible_authority_levels.append(record.authority_level)
        eligible_licence_states.append(record.licence_state)

    return LicenceCheckResult(
        eligible=eligible,
        excluded=excluded,
        exclusion_reasons=exclusion_reasons,
        display_states=display_states,
        authority_level=_weakest_authority_level(eligible_authority_levels),
        licence_state=_weakest_licence_state(eligible_licence_states),
        authority_ranks=authority_ranks,
    )


# Most-restrictive-governs, matching this codebase's existing convention
# (routing_matrix's confidence downgrades, _DOWNGRADE_ON_EXCLUSION below) —
# a bundle can only claim the authority/licence standing of its WEAKEST
# eligible source, never its strongest.
_AUTHORITY_RANK = {"primary": 0, "secondary": 1, "internal": 2}
_LICENCE_RANK = {"permitted": 0, "unknown": 1}  # "restricted" never reaches here — excluded at Checkpoint A


def _weakest_authority_level(levels: list[str]) -> str:
    if not levels:
        return "primary"
    return max(levels, key=lambda lvl: _AUTHORITY_RANK.get(lvl, 2))


def _weakest_licence_state(states: list[str]) -> str:
    if not states:
        return "permitted"
    return max(states, key=lambda st: _LICENCE_RANK.get(st, 1))


def _resolve_display_state(record: Source) -> SourceDisplayState:
    """Checkpoint B — per-source exposure resolution."""
    if record.licence_state == "unknown":
        return "internal_reasoning_only"
    if record.authority_level == "internal":
        return "summarise"
    return "show"


# The catalogue records display_permission per provider using the same
# vocabulary Checkpoint B resolves to. Anything outside it is ignored rather
# than trusted: a typo in a registry row must not silently widen exposure.
_VALID_DISPLAY_PERMISSIONS: frozenset[str] = frozenset(
    {"show", "summarise", "internal_reasoning_only"}
)


def _resolve_live_display_state(record: LiveSourceProvider) -> SourceDisplayState:
    """Checkpoint B for live sources — same vocabulary as _resolve_display_state.

    An explicit display_permission on the registry row wins over the derived
    state. That column existed but nothing read it, so a provider recorded as
    restricted-display was still shown in full — governance that is recorded
    but unenforced reads as a control while behaving as none.

    It can only ever tighten, never widen: a row asking for "show" on a
    source whose licence is unknown is still held at
    internal_reasoning_only, because a licence state is a legal fact and a
    display preference is not permission to override it.
    """
    derived = _derive_live_display_state(record)
    override = (record.display_permission or "").strip().lower()
    if override not in _VALID_DISPLAY_PERMISSIONS:
        return derived
    return _stricter_display_state(derived, override)  # type: ignore[arg-type]


def _derive_live_display_state(record: LiveSourceProvider) -> SourceDisplayState:
    if record.licence_state == "unknown":
        return "internal_reasoning_only"
    if record.authority_level == "internal":
        return "summarise"
    return "show"


# Most-restrictive-governs, the same convention _weakest_authority_level
# above already follows.
_DISPLAY_RESTRICTION_RANK = {"show": 0, "summarise": 1, "internal_reasoning_only": 2}


def _stricter_display_state(left: SourceDisplayState, right: SourceDisplayState) -> SourceDisplayState:
    return max(left, right, key=lambda state: _DISPLAY_RESTRICTION_RANK.get(state, 2))


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
