"""WF-01 decision D1: which wireframe owns each of the 30 gaps.

adopt records registry/gap_ownership.json as ADOPTED_PENDING_RATIFICATION
(authority.propose); ratify records the same content, bound by its hash, as
RATIFIED by someone else (authority.ratify). Both append; neither edits.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin_governance.governance_access import canonical_sha256, governance_error
from app.domains.admin_governance.governance_models import GapOwnershipDecision

ALLOCATION = Path(__file__).resolve().parents[3] / "registry" / "gap_ownership.json"
OWNERS = {"WF-01", "WF-02", "WF-03"}


def proposed() -> dict:
    return json.loads(ALLOCATION.read_text())


async def _replay(db: AsyncSession, key: str) -> GapOwnershipDecision | None:
    return (await db.execute(select(GapOwnershipDecision).where(GapOwnershipDecision.idempotency_key == key))).scalar_one_or_none()


def _public(row: GapOwnershipDecision) -> dict:
    return {"id": row.id, "status": row.status, "content_sha256": row.content_sha256, "actor_id": row.actor_id,
            "allocation": row.allocation}


async def adopt(db: AsyncSession, actor, key: str) -> dict:
    replay = await _replay(db, key)
    if replay is not None:
        return _public(replay)
    source = proposed()
    allocation = source["allocation"]
    if len(allocation) != 30 or set(allocation.values()) - OWNERS:
        raise governance_error("INVALID_ALLOCATION", "The allocation must give each of G01-G30 one of WF-01/02/03.", 422)
    row = GapOwnershipDecision(status="ADOPTED_PENDING_RATIFICATION", allocation=allocation, basis=source.get("basis", ""),
                               actor_id=actor.id, content_sha256=canonical_sha256(allocation), idempotency_key=key)
    db.add(row)
    await db.commit()
    return _public(row)


async def ratify(db: AsyncSession, actor, *, adoption_id: str, content_sha256: str, key: str) -> dict:
    replay = await _replay(db, key)
    if replay is not None:
        return _public(replay)
    adoption = (await db.execute(select(GapOwnershipDecision).where(
        GapOwnershipDecision.id == adoption_id, GapOwnershipDecision.status == "ADOPTED_PENDING_RATIFICATION"))).scalar_one_or_none()
    if adoption is None:
        raise governance_error("UNKNOWN_ADOPTION", "No such adoption.", 404)
    if adoption.actor_id == actor.id:
        raise governance_error("INDEPENDENCE_REQUIRED", "The person who adopted the allocation cannot ratify it.", 403)
    if content_sha256 != adoption.content_sha256:
        raise governance_error("STALE_REVISION", "The allocation changed since you read it.")
    row = GapOwnershipDecision(status="RATIFIED", allocation=adoption.allocation, basis=f"ratifies {adoption.id}",
                               actor_id=actor.id, content_sha256=adoption.content_sha256, idempotency_key=key)
    db.add(row)
    await db.commit()
    return _public(row)


async def current(db: AsyncSession) -> dict:
    rows = list((await db.execute(select(GapOwnershipDecision).order_by(GapOwnershipDecision.created_at))).scalars())
    if not rows:
        return {"status": "NOT_ADOPTED", "proposed_sha256": canonical_sha256(proposed()["allocation"])}
    latest = rows[-1]
    return {"status": latest.status, "decision_id": latest.id, "content_sha256": latest.content_sha256,
            "proposed_sha256": canonical_sha256(proposed()["allocation"])}
