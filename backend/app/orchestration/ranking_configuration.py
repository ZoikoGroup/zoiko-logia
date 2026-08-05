"""Dynamic Visualization Selection v6 — governed ranking-weight configuration
proposals.

A RankingConfiguration row is a versioned PROPOSAL for
presentation_dataprofile._WEIGHTS, nothing more. Two states only: "draft"
(created, not yet reviewed) and "approved" (reviewed and recorded). Neither
state changes what _score_candidate actually does — _WEIGHTS is still a
plain module-level constant, edited and code-reviewed like any other
production value, and RANKING_VERSION is still bumped by hand alongside it.
This module deliberately has NO "activate" operation and no code path that
reads an approved row back into the live scorer: turning a reviewed proposal
into the running configuration is intentionally left as a separate, manual,
ordinary code change, so "approved" can never silently become "live" through
this API. That is the whole point of requirement v6.12 ("may propose weight
deltas, but never activates them automatically").

Maker-checker, mirroring CompensatingEvent (audit_ledger/models.py): the
actor who drafts a configuration cannot also approve it.

Approval is recorded on the formal compliance audit ledger (AuditEvent, via
record_event_async) rather than the product-telemetry table — see
visualization_analytics.py's own docstring for why that table stays
telemetry-only. A ranking-configuration change is an administrative/
governance action, not a per-query product event, exactly the kind of thing
the audit ledger already exists for.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.orchestration.models import RankingConfiguration
from app.orchestration.visualization_analytics_schemas import validate_weights


class RankingConfigurationError(Exception):
    """Base class — callers (the router) catch this and translate to an
    appropriate HTTP status rather than leaking internals."""


class DuplicateRankingVersionError(RankingConfigurationError):
    pass


class RankingConfigurationNotFoundError(RankingConfigurationError):
    pass


class AlreadyReviewedError(RankingConfigurationError):
    pass


class SelfApprovalError(RankingConfigurationError):
    """Maker-checker: the actor who drafted a configuration cannot also
    approve it — same rule CompensatingEvent already enforces elsewhere."""


async def create_draft(
    db: AsyncSession, *, ranking_version: str, effective_from: datetime, weights: dict[str, float], created_by: str,
) -> RankingConfiguration:
    validate_weights(weights)  # defense in depth — the request schema already validated this.
    existing = await db.execute(
        select(RankingConfiguration).where(RankingConfiguration.ranking_version == ranking_version)
    )
    if existing.scalar_one_or_none() is not None:
        raise DuplicateRankingVersionError(f"ranking_version {ranking_version!r} already exists")
    row = RankingConfiguration(
        ranking_version=ranking_version, effective_from=effective_from, weights=weights,
        status="draft", created_by=created_by,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_configurations(db: AsyncSession, *, status: str | None = None) -> list[RankingConfiguration]:
    stmt = select(RankingConfiguration).order_by(RankingConfiguration.created_at.desc())
    if status is not None:
        stmt = stmt.where(RankingConfiguration.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_configuration(db: AsyncSession, configuration_id: str) -> RankingConfiguration | None:
    return await db.get(RankingConfiguration, configuration_id)


async def get_configuration_by_version(db: AsyncSession, ranking_version: str) -> RankingConfiguration | None:
    """v7 — ranking_experiments.py looks configurations up by their
    ranking_version (what a RankingExperiment's control/variant fields
    reference), not by row id."""
    result = await db.execute(select(RankingConfiguration).where(RankingConfiguration.ranking_version == ranking_version))
    return result.scalar_one_or_none()


async def approve_configuration(
    db: AsyncSession, *, configuration_id: str, approver_id: str,
) -> RankingConfiguration:
    row = await get_configuration(db, configuration_id)
    if row is None:
        raise RankingConfigurationNotFoundError(configuration_id)
    if row.status != "draft":
        raise AlreadyReviewedError(f"ranking configuration {configuration_id} is already {row.status}")
    if row.created_by == approver_id:
        raise SelfApprovalError("the actor who drafted a configuration cannot also approve it")

    row.status = "approved"
    row.approved_by = approver_id
    row.approved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)

    # Administrative change log, deliberately the compliance AuditEvent
    # ledger rather than VisualizationTelemetryEvent — see module docstring.
    await record_event_async(
        db,
        event_name="ranking_configuration_approved",
        emitting_service="orchestration",
        subject_type="ranking_configuration",
        subject_id=row.ranking_version,
        actor_id=approver_id,
        tenant_id="GLOBAL_CONTROL",
        classification="INTERNAL",
        replay_relevance="SUPPORTING",
        payload={
            "ranking_configuration_id": row.id,
            "ranking_version": row.ranking_version,
            "created_by": row.created_by,
            "weights": row.weights,
        },
    )
    return row
