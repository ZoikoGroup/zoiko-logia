"""Deleting a CPD entry: own entries only, and the removal is audited
(learning_cpd/router.py delete_cpd_entry)."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Tenant, User
from app.domains.learning_cpd.models import CPDEntry
from app.domains.learning_cpd.router import delete_cpd_entry


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="T"),
            CPDEntry(id="c-mine", tenant_id="t1", user_id="u1", topic="Revenue Recognition", minutes=30),
            CPDEntry(id="c-theirs", tenant_id="t1", user_id="u2", topic="Leases", minutes=20),
        ])
        await session.commit()
        yield session
    await engine.dispose()


def _user(user_id="u1") -> User:
    return User(id=user_id, tenant_id="t1", email=f"{user_id}@example.com", full_name=user_id, role="Learner")


async def test_own_entry_is_deleted_and_audited(db):
    response = await delete_cpd_entry("c-mine", db=db, current_user=_user())
    assert response.status_code == 204
    assert await db.get(CPDEntry, "c-mine") is None
    event = (await db.execute(select(AuditEvent).where(AuditEvent.event_name == "learning.cpd_entry_deleted"))).scalar_one()
    assert event.subject_id == "c-mine" and event.payload == {"topic": "Revenue Recognition", "minutes": 30}


async def test_another_users_entry_is_not_found(db):
    with pytest.raises(HTTPException) as err:
        await delete_cpd_entry("c-theirs", db=db, current_user=_user())
    assert err.value.status_code == 404
    assert await db.get(CPDEntry, "c-theirs") is not None
