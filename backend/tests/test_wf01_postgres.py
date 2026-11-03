"""WF-01 against a real, migrated Postgres: the append-only triggers refuse
UPDATE and DELETE, and the release verdict reads the ledger. Runs only when
WF01_TEST_DATABASE_URL names an isolated database (never the application's)."""
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domains.admin_governance import authority, release_verdict
from app.domains.evaluation import qa_ledger

URL = os.getenv("WF01_TEST_DATABASE_URL", "")
pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not URL, reason="WF01_TEST_DATABASE_URL is not set")]

APPEND_ONLY = ("authority_change_requests", "gap_ownership_decisions", "release_verdicts", "asbuilt_manifests",
               "asbuilt_mappings", "asbuilt_verifications", "qa_cases", "qa_baseline", "qa_runs",
               "qa_observations", "qa_adjudications", "qa_fixture_provisions")


@pytest.fixture
async def sessions():
    engine = create_async_engine(URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_the_database_is_migrated_with_the_triggers(sessions):
    async with sessions() as db:
        triggers = set((await db.execute(text(
            "SELECT event_object_table FROM information_schema.triggers WHERE action_statement LIKE '%wf01_refuse_mutation%'"
        ))).scalars())
    assert set(APPEND_ONLY) | {"authority_documents", "authority_aliases"} <= triggers


async def test_append_only_rows_cannot_be_changed_or_deleted(sessions):
    async with sessions() as db:
        await qa_ledger.import_pack(db)
        for statement in ("UPDATE qa_baseline SET status = 'PASSED'", "DELETE FROM qa_baseline",
                          "UPDATE qa_cases SET priority = 'P2'"):
            with pytest.raises(Exception, match="append-only|wf01"):
                await db.execute(text(statement))
            await db.rollback()
        assert (await db.execute(text("SELECT count(*) FROM qa_baseline WHERE status <> 'NOT_RUN'"))).scalar() == 0


async def test_verdict_reads_no_go_from_the_migrated_ledger(sessions):
    async with sessions() as db:
        await authority.import_register(db)
        computed = await release_verdict.compute(db)
        assert computed["verdict"] == "NO_GO"
        assert computed["gates"]["authority"]["state"] == "BLOCKED"
        actor = type("Actor", (), {"id": f"pg-test-{uuid.uuid4()}"})()
        recorded = await release_verdict.record(db, actor, f"pg-{uuid.uuid4()}")
        assert recorded["verdict"] == "NO_GO"
        with pytest.raises(Exception, match="append-only|wf01"):
            await db.execute(text("UPDATE release_verdicts SET verdict = 'GO' WHERE id = :id"), {"id": recorded["id"]})
        await db.rollback()


async def test_a_database_built_from_migrations_has_every_orm_column(sessions):
    # A migrated database lacked safety_events.tenant_id (and two others), so
    # every /ask failed with 503 there (found by the WF-01 end-to-end run).
    from app.db.base import Base

    async with sessions() as db:
        rows = (await db.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"))).all()
    present = {(t, c) for t, c in rows}
    missing = [f"{t}.{c.name}" for t, table in Base.metadata.tables.items() for c in table.columns
               if (t, c.name) not in present]
    assert missing == []
