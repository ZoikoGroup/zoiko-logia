"""F1 engagement-scoped operation authorization."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.identity.models import Engagement, EngagementGrant, EngagementMembership

ASK = "ask"
DOCUMENT_READ = "document.read"
DOCUMENT_WRITE = "document.write"
MODEL_TRANSMIT = "model.transmit"
AUDIT_REPLAY = "audit.replay"
EXPORT = "export"
ALL_OPERATIONS = (ASK, DOCUMENT_READ, DOCUMENT_WRITE, MODEL_TRANSMIT, AUDIT_REPLAY, EXPORT)


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason_code: str
    engagement_id: str | None = None
    membership_id: str | None = None
    grant_version: str | None = None


async def authorize(
    db: AsyncSession, *, actor_id: str, tenant_id: str,
    engagement_id: str, operation: str,
) -> AuthorizationDecision:
    """Deny by default. Explicit deny beats wildcard or operation allow."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Engagement, EngagementMembership, EngagementGrant)
        .join(EngagementMembership, and_(
            EngagementMembership.engagement_id == Engagement.id,
            EngagementMembership.user_id == actor_id,
            EngagementMembership.tenant_id == tenant_id,
        ))
        .outerjoin(EngagementGrant, EngagementGrant.membership_id == EngagementMembership.id)
        .where(
            Engagement.id == engagement_id,
            Engagement.tenant_id == tenant_id,
            Engagement.status == "active",
            EngagementMembership.status == "active",
            EngagementMembership.revoked_at.is_(None),
        )
    )
    rows = result.all()
    if not rows:
        return AuthorizationDecision(False, "ENGAGEMENT_ACCESS_DENIED", engagement_id)
    membership = rows[0][1]
    grants = [row[2] for row in rows if row[2] is not None]
    applicable = [
        grant for grant in grants
        if grant.operation in {operation, "*"}
        and (grant.expires_at is None or grant.expires_at > now)
    ]
    if any(grant.effect == "deny" for grant in applicable):
        return AuthorizationDecision(False, "OPERATION_EXPLICITLY_DENIED", engagement_id, membership.id)
    allowed = next((grant for grant in applicable if grant.effect == "allow"), None)
    if allowed is None:
        return AuthorizationDecision(False, "OPERATION_NOT_GRANTED", engagement_id, membership.id)
    return AuthorizationDecision(True, "AUTHORIZED", engagement_id, membership.id, allowed.version)


async def list_authorized_engagements(
    db: AsyncSession, *, actor_id: str, tenant_id: str, operation: str = ASK,
) -> list[Engagement]:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Engagement).distinct()
        .join(EngagementMembership, EngagementMembership.engagement_id == Engagement.id)
        .join(EngagementGrant, EngagementGrant.membership_id == EngagementMembership.id)
        .where(
            Engagement.tenant_id == tenant_id,
            Engagement.status == "active",
            EngagementMembership.tenant_id == tenant_id,
            EngagementMembership.user_id == actor_id,
            EngagementMembership.status == "active",
            EngagementMembership.revoked_at.is_(None),
            EngagementGrant.effect == "allow",
            EngagementGrant.operation.in_([operation, "*"]),
            or_(EngagementGrant.expires_at.is_(None), EngagementGrant.expires_at > now),
        )
        .order_by(Engagement.name)
    )
    return list(result.scalars().all())
