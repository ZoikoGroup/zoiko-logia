from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.authorization import ALL_OPERATIONS, ASK, list_authorized_engagements
from app.domains.identity.engagement_schemas import EngagementCreate, EngagementPublic, MembershipCreate, MembershipPublic
from app.domains.identity.models import Engagement, EngagementGrant, EngagementMembership, User
from app.domains.identity.rbac import get_current_user, require_admin

router = APIRouter(prefix="/engagements", tags=["engagements"])


@router.get("", response_model=list[EngagementPublic])
async def get_engagements(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await list_authorized_engagements(db, actor_id=current_user.id, tenant_id=current_user.tenant_id, operation=ASK)


@router.post("", response_model=EngagementPublic)
async def create_engagement(payload: EngagementCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    engagement = Engagement(tenant_id=admin.tenant_id, name=payload.name.strip())
    db.add(engagement)
    await db.commit()
    await db.refresh(engagement)
    return engagement


@router.post("/{engagement_id}/members", response_model=MembershipPublic)
async def add_member(engagement_id: str, payload: MembershipCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    engagement = (await db.execute(select(Engagement).where(Engagement.id == engagement_id, Engagement.tenant_id == admin.tenant_id))).scalar_one_or_none()
    user = (await db.execute(select(User).where(User.id == payload.user_id, User.tenant_id == admin.tenant_id))).scalar_one_or_none()
    if engagement is None or user is None:
        raise HTTPException(404, "Engagement or user not found")
    invalid = sorted(set(payload.operations) - set(ALL_OPERATIONS) - {"*"})
    if invalid:
        raise HTTPException(422, f"Unsupported operations: {', '.join(invalid)}")
    membership = EngagementMembership(tenant_id=admin.tenant_id, engagement_id=engagement_id, user_id=user.id, engagement_role=payload.engagement_role)
    db.add(membership)
    await db.flush()
    for operation in sorted(set(payload.operations)):
        db.add(EngagementGrant(tenant_id=admin.tenant_id, membership_id=membership.id, operation=operation, effect="allow", version=engagement.rights_version))
    await db.commit()
    await db.refresh(membership)
    return membership


@router.delete("/{engagement_id}/members/{user_id}", response_model=MembershipPublic)
async def revoke_member(engagement_id: str, user_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    membership = (await db.execute(select(EngagementMembership).where(EngagementMembership.engagement_id == engagement_id, EngagementMembership.user_id == user_id, EngagementMembership.tenant_id == admin.tenant_id))).scalar_one_or_none()
    if membership is None:
        raise HTTPException(404, "Membership not found")
    membership.status = "revoked"
    membership.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(membership)
    return membership
