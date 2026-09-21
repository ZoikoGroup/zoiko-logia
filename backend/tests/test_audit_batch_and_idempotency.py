from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.event_envelope import (
    begin_audit_batch,
    commit_audit_batch,
    record_event_async,
)
from app.domains.audit_ledger.models import AuditEvent
from app.orchestration.identifiers import (
    claim_idempotency,
    check_idempotency,
    store_idempotency,
)


async def _sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_audit_events_are_committed_as_one_ordered_batch():
    engine, sessions = await _sessions()
    try:
        async with sessions() as db:
            token = begin_audit_batch()
            first = await record_event_async(
                db, tenant_id="tenant-a", event_name="first",
                emitting_service="test", subject_type="query", subject_id="q1", payload={},
            )
            second = await record_event_async(
                db, tenant_id="tenant-a", event_name="second",
                emitting_service="test", subject_type="query", subject_id="q1", payload={},
            )

            # Buffered rows are not visible to a separate session yet.
            async with sessions() as observer:
                assert not (await observer.execute(AuditEvent.__table__.select())).all()

            await commit_audit_batch(db, token)
            assert second.previous_chain_hash == first.chain_hash

        async with sessions() as observer:
            rows = (await observer.execute(AuditEvent.__table__.select())).all()
            assert len(rows) == 2
    finally:
        await engine.dispose()


async def test_idempotency_is_durable_and_blocks_a_second_owner():
    engine, sessions = await _sessions()
    try:
        async with sessions() as first:
            assert await claim_idempotency(first, "key-1", "tenant-a") is True

        async with sessions() as second:
            assert await claim_idempotency(second, "key-1", "tenant-a") is False
            assert await check_idempotency(second, "key-1", "tenant-a") is None
            await store_idempotency(second, "key-1", "tenant-a", {"outcome": "answered"})
            await second.commit()

        async with sessions() as third:
            assert await check_idempotency(third, "key-1", "tenant-a") == {
                "outcome": "answered"
            }
    finally:
        await engine.dispose()
