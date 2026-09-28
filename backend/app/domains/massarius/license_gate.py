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

Retrieval rights, tenant scope and applicability are enforced before passage
content is loaded in orchestration/retrieve.py. This module is the independent
second boundary: it rechecks model-transmission rights and resolves what may be
displayed or summarised before model context and response construction.

Must NOT: perform retrieval itself, do risk classification, or construct the
final SourceBundle (bundle_builder.py's job) — only decide what's eligible
and how each source may be displayed.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.massarius.errors import LicenceDenied
from app.domains.source_library.licensing import SourceUseContext, can_use
from app.domains.source_library.models import Source
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


async def check_eligibility(
    db: AsyncSession,
    sources: list[SourceSummary],
    *,
    tenant_id: str,
    allow_tenant_private: bool = True,
    jurisdiction: str = "",
    framework: str = "",
    effective_date=None,
) -> LicenceCheckResult:
    """
    Checkpoint A + B combined: filters ineligible sources and resolves
    display states for the rest. Raises nothing itself — callers that want
    a hard stop on any denial should inspect `excluded` and raise
    LicenceDenied themselves (see orchestration/service.py's wiring), since
    "some sources excluded" is often a normal, non-fatal outcome (it can
    just lower confidence_state) while "the caller wants zero tolerance for
    a specific denial class" is a policy decision made at the call site.
    """
    fields_by_id = await _fetch_licence_fields(db, [s.id for s in sources])

    eligible: list[SourceSummary] = []
    excluded: list[SourceSummary] = []
    exclusion_reasons: dict[str, str] = {}
    display_states: dict[str, SourceDisplayState] = {}

    for source in sources:
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

        if not source.version_id:
            # Transitional compatibility for callers that still construct a
            # legacy summary directly. Governed retrieval always supplies a
            # version_id and therefore always uses the operation-level matrix.
            # A legacy "permitted" value is explicit; unknown remains denied.
            if record.licence_state != "permitted":
                excluded.append(source)
                exclusion_reasons[source.id] = "source_version_not_identified"
                continue
            eligible.append(source)
            display_states[source.id] = _resolve_display_state(record)
            continue

        context = SourceUseContext(
            tenant_id=tenant_id,
            jurisdiction=jurisdiction,
            framework=framework,
            effective_date=effective_date,
        )
        transmission = await can_use(db, source.version_id, context, "model_transmission")
        if not transmission.allowed:
            excluded.append(source)
            exclusion_reasons[source.id] = transmission.reason_code.lower()
            continue

        eligible.append(source)
        display = await can_use(db, source.version_id, context, "display")
        if display.allowed:
            display_states[source.id] = _resolve_display_state(record)
        else:
            summary = await can_use(db, source.version_id, context, "summary")
            display_states[source.id] = "summarise" if summary.allowed else "internal_reasoning_only"

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
