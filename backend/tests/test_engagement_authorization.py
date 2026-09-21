from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.identity.authorization import ASK, MODEL_TRANSMIT, authorize
from app.domains.identity.models import Engagement, EngagementGrant, EngagementMembership, Tenant, User


@pytest.fixture
async def auth_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        tenant = Tenant(id="tenant-1", name="Tenant One")
        other_tenant = Tenant(id="tenant-2", name="Tenant Two")
        user = User(id="user-1", tenant_id="tenant-1", email="u1@example.com", full_name="User One", role="Accountant")
        engagement = Engagement(id="eng-1", tenant_id="tenant-1", name="Client A")
        membership = EngagementMembership(id="member-1", tenant_id="tenant-1", engagement_id="eng-1", user_id="user-1")
        db.add_all([tenant, other_tenant, user, engagement, membership])
        db.add(EngagementGrant(id="grant-1", tenant_id="tenant-1", membership_id="member-1", operation=ASK, effect="allow"))
        await db.commit()
        yield db, membership
    await engine.dispose()


@pytest.mark.asyncio
async def test_explicit_operation_grant_allows_access(auth_db) -> None:
    db, _ = auth_db
    decision = await authorize(db, actor_id="user-1", tenant_id="tenant-1", engagement_id="eng-1", operation=ASK)
    assert decision.allowed
    assert decision.reason_code == "AUTHORIZED"


@pytest.mark.asyncio
async def test_missing_operation_grant_denies_access(auth_db) -> None:
    db, _ = auth_db
    decision = await authorize(db, actor_id="user-1", tenant_id="tenant-1", engagement_id="eng-1", operation=MODEL_TRANSMIT)
    assert not decision.allowed
    assert decision.reason_code == "OPERATION_NOT_GRANTED"


@pytest.mark.asyncio
async def test_cross_tenant_access_is_denied(auth_db) -> None:
    db, _ = auth_db
    decision = await authorize(db, actor_id="user-1", tenant_id="tenant-2", engagement_id="eng-1", operation=ASK)
    assert not decision.allowed
    assert decision.reason_code == "ENGAGEMENT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_revocation_takes_effect_immediately(auth_db) -> None:
    db, membership = auth_db
    membership.status = "revoked"
    membership.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    decision = await authorize(db, actor_id="user-1", tenant_id="tenant-1", engagement_id="eng-1", operation=ASK)
    assert not decision.allowed
    assert decision.reason_code == "ENGAGEMENT_ACCESS_DENIED"
