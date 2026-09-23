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


async def can_use(
    db: AsyncSession,
    source_version_id: str,
    context: SourceUseContext,
    operation: str,
    *,
    now: datetime | None = None,
) -> SourceUseDecision:
    if operation not in SOURCE_OPERATIONS:
        return SourceUseDecision(False, "UNKNOWN_OPERATION")

    result = await db.execute(
        select(SourceVersion, Source)
        .join(Source, Source.id == SourceVersion.source_id)
        .where(SourceVersion.id == source_version_id)
    )
    row = result.first()
    if row is None:
        return SourceUseDecision(False, "SOURCE_VERSION_NOT_FOUND")
    version, source = row

    if source.is_tenant_private and source.tenant_id != context.tenant_id:
        return SourceUseDecision(False, "TENANT_PRIVATE_BOUNDARY")
    if version.revoked_at is not None:
        return SourceUseDecision(False, "SOURCE_REVOKED")
    if version.superseded_by_version_id is not None:
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

    current = now or datetime.now(timezone.utc)
    rights_result = await db.execute(
        select(SourceRight)
        .where(
            SourceRight.source_version_id == source_version_id,
            SourceRight.operation == operation,
        )
        .order_by(SourceRight.rights_version.desc(), SourceRight.created_at.desc())
    )
    right = rights_result.scalars().first()
    if right is None:
        return SourceUseDecision(False, "RIGHT_UNKNOWN")
    if right.valid_from and _aware(current) < _aware(right.valid_from):
        return SourceUseDecision(False, "RIGHT_NOT_YET_VALID", right.rights_version)
    if right.valid_to and _aware(current) > _aware(right.valid_to):
        return SourceUseDecision(False, "RIGHT_EXPIRED", right.rights_version)
    if right.decision != "allow":
        return SourceUseDecision(False, right.reason_code or "RIGHT_DENIED", right.rights_version)
    return SourceUseDecision(True, "ALLOWED", right.rights_version)
