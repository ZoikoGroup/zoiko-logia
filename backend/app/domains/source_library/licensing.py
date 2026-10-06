"""Central, fail-closed source-rights decision point.

Every caller asks about one exact source version and one operation. Missing,
unknown, expired, revoked, superseded, cross-tenant, or context-inapplicable
rights are denials with stable reason codes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domains.source_library.models import Source, SourceRight, SourceVersion

SOURCE_OPERATIONS = frozenset({
    "ingestion", "indexing", "retrieval", "model_transmission", "display",
    "summary", "export", "retention", "training",
})
USABLE_VERSION_STATUSES = frozenset({"APPROVED", "ACTIVE"})


@dataclass(frozen=True)
class SourceUseContext:
    tenant_id: str
    jurisdiction: str = ""
    framework: str = ""
    effective_date: date | None = None


@dataclass(frozen=True)
class SourceUseDecision:
    allowed: bool
    reason_code: str
    rights_version: int | None = None


def _normalise_scope(value: str) -> str:
    return value.strip().casefold()


def _scope_matches(configured: str, requested: str) -> bool:
    if not requested:
        return True
    values = {_normalise_scope(item) for item in configured.split(",") if item.strip()}
    return not values or "global" in values or _normalise_scope(requested) in values


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _decide(
    version: SourceVersion | None,
    source: Source | None,
    right: SourceRight | None,
    context: SourceUseContext,
    operation: str,
    now: datetime,
    superseding_from: date | None = None,
) -> SourceUseDecision:
    """The rights decision for one version, given its rows. Shared by
    can_use and can_use_many so the two can never disagree."""
    if operation not in SOURCE_OPERATIONS:
        return SourceUseDecision(False, "UNKNOWN_OPERATION")
    if version is None or source is None:
        return SourceUseDecision(False, "SOURCE_VERSION_NOT_FOUND")
    if source.is_tenant_private and source.tenant_id != context.tenant_id:
        return SourceUseDecision(False, "TENANT_PRIVATE_BOUNDARY")
    if version.revoked_at is not None:
        return SourceUseDecision(False, "SOURCE_REVOKED")
    if version.superseded_by_version_id is not None:
        if not (context.effective_date and superseding_from and context.effective_date < superseding_from):
            return SourceUseDecision(False, "SOURCE_SUPERSEDED")
    if version.status not in USABLE_VERSION_STATUSES:
        return SourceUseDecision(False, "VERSION_NOT_APPROVED")
    if not _scope_matches(source.jurisdiction_scope, context.jurisdiction):
        return SourceUseDecision(False, "JURISDICTION_MISMATCH")
    if not _scope_matches(source.framework_scope, context.framework):
        return SourceUseDecision(False, "FRAMEWORK_MISMATCH")
    if context.effective_date is not None:
        if version.effective_from and context.effective_date < version.effective_from:
            return SourceUseDecision(False, "NOT_YET_EFFECTIVE")
        if version.effective_to and context.effective_date > version.effective_to:
            return SourceUseDecision(False, "SOURCE_EXPIRED")
    if right is None:
        return SourceUseDecision(False, "RIGHT_UNKNOWN")
    if right.valid_from and _aware(now) < _aware(right.valid_from):
        return SourceUseDecision(False, "RIGHT_NOT_YET_VALID", right.rights_version)
    if right.valid_to and _aware(now) > _aware(right.valid_to):
        return SourceUseDecision(False, "RIGHT_EXPIRED", right.rights_version)
    if right.decision != "allow":
        return SourceUseDecision(False, right.reason_code or "RIGHT_DENIED", right.rights_version)
    return SourceUseDecision(True, "ALLOWED", right.rights_version)


def _latest_right(rights: list[SourceRight]) -> SourceRight | None:
    return max(
        rights,
        key=lambda right: (right.rights_version, _aware(right.created_at) if right.created_at else datetime.min.replace(tzinfo=timezone.utc)),
        default=None,
    )


async def can_use(
    db: AsyncSession,
    source_version_id: str,
    context: SourceUseContext,
    operation: str,
    *,
    now: datetime | None = None,
) -> SourceUseDecision:
    return (await can_use_many(db, [source_version_id], context, operation, now=now))[source_version_id]


async def can_use_many(
    db: AsyncSession,
    source_version_ids: list[str],
    context: SourceUseContext,
    operation: str,
    *,
    now: datetime | None = None,
) -> dict[str, SourceUseDecision]:
    """can_use for many versions in two queries. Checked one at a time,
    retrieval made several sequential round trips per candidate version —
    38-48s per question against a remote database once the UK VAT library
    was loaded."""
    current = now or datetime.now(timezone.utc)
    ids = list(dict.fromkeys(source_version_ids))
    if operation not in SOURCE_OPERATIONS or not ids:
        return {vid: _decide(None, None, None, context, operation, current) for vid in ids}
    superseding = aliased(SourceVersion)
    rows = await db.execute(
        select(SourceVersion, Source, superseding.effective_from)
        .join(Source, Source.id == SourceVersion.source_id)
        .outerjoin(superseding, superseding.id == SourceVersion.superseded_by_version_id)
        .where(SourceVersion.id.in_(ids))
    )
    fetched = rows.all()
    versions = {version.id: (version, source) for version, source, _ in fetched}
    superseding_dates = {version.id: start for version, _, start in fetched}
    rights_by_version: dict[str, list[SourceRight]] = {}
    rights = await db.execute(
        select(SourceRight).where(SourceRight.source_version_id.in_(ids), SourceRight.operation == operation)
    )
    for right in rights.scalars():
        rights_by_version.setdefault(right.source_version_id, []).append(right)
    return {
        vid: _decide(
            *versions.get(vid, (None, None)),
            _latest_right(rights_by_version.get(vid, [])),
            context, operation, current, superseding_dates.get(vid),
        )
        for vid in ids
    }
