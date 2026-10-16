"""Status-page ledger check: an altered event is "down", a fork from two
simultaneous writes is reported but is not tampering."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domains.audit_ledger.chain_integrity import compute_chain_hash
from app.domains.audit_ledger.models import AuditEvent
from app.domains.audit_ledger.service import verify_recent_tenant_chain

T0 = datetime(2026, 10, 14, tzinfo=timezone.utc)


def _event(n: int, previous: str | None) -> AuditEvent:
    chain = compute_chain_hash(f"e{n}", "x", "p", previous)
    return AuditEvent(id=f"e{n}", event_name="x", emitting_service="t", tenant_id="t", subject_type="s",
                      subject_id="s", payload={}, payload_hash="p", previous_chain_hash=previous,
                      chain_hash=chain, ingested_at=T0 + timedelta(seconds=n), event_time=T0)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(AuditEvent.__table__.create)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def test_linear_chain_passes(db):
    a = _event(1, None)
    b = _event(2, a.chain_hash)
    c = _event(3, b.chain_hash)
    db.add_all([a, b, c])
    await db.commit()
    result = await verify_recent_tenant_chain(db, "t")
    assert result["passed"] and result["forks"] == 0 and result["events_checked"] == 3


async def test_fork_is_reported_but_not_tampering(db):
    a = _event(1, None)
    b = _event(2, a.chain_hash)
    c = _event(3, a.chain_hash)  # b and c both chain onto a
    db.add_all([a, b, c])
    await db.commit()
    result = await verify_recent_tenant_chain(db, "t")
    assert result["altered_event_id"] is None and result["forks"] == 1 and not result["passed"]


async def test_altered_event_is_detected(db):
    a = _event(1, None)
    b = _event(2, a.chain_hash)
    b.payload_hash = "changed"
    db.add_all([a, b])
    await db.commit()
    result = await verify_recent_tenant_chain(db, "t")
    assert result["altered_event_id"] == "e2"
