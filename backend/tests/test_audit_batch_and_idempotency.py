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


async def test_source_dates_survive_response_persistence_and_retry():
    from datetime import date, datetime, timezone
    from app.orchestration.schemas import SourceBundle, SourceSummary
    bundle = SourceBundle(
        source_bundle_id="bundle-vat", as_of=date(2026, 10, 4),
        sources=[SourceSummary(id="hmrc", title="VAT registration", category="tax",
            jurisdiction_scope="GB", version_label="2026", status="APPROVED",
            effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))],
    )
    response = {"outcome": "answered", "source_bundle": bundle.model_dump(),
                "recorded_at": datetime(2026, 10, 4, tzinfo=timezone.utc)}
    engine, sessions = await _sessions()
    try:
        async with sessions() as db:
            assert await claim_idempotency(db, "vat-with-dates", "tenant-a")
            await store_idempotency(db, "vat-with-dates", "tenant-a", "request-vat", response)
        async with sessions() as db:
            cached = await check_idempotency(db, "vat-with-dates", "tenant-a", "request-vat")
            assert cached["source_bundle"]["as_of"] == "2026-10-04"
            assert cached["source_bundle"]["sources"][0]["effective_from"] == "2026-01-01"
            assert cached["source_bundle"]["sources"][0]["effective_to"] == "2026-12-31"
            assert SourceBundle.model_validate(cached["source_bundle"]) == bundle
            # Also cover the legacy store call and insertion without reservation.
            await store_idempotency(db, "legacy-with-dates", "tenant-a", response)
        async with sessions() as db:
            assert (await check_idempotency(db, "legacy-with-dates", "tenant-a"))["source_bundle"]["as_of"] == "2026-10-04"
    finally:
        await engine.dispose()
