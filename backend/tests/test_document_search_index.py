"""Retrieval reads the materialised tsvector, and degrades instead of breaking.

The speed-up has two halves and only pays off with both: the STORED generated
column (parse once at write time) and the GIN index over it. A GIN index over
the inline expression measured 11.98ms -> 11.88ms, because ts_rank_cd must build
a tsvector for every surviving row to score it. With the column stored, the same
corpus measured 0.77ms.

None of this can run against SQLite, which has no tsvector — so these assert on
the SQL that gets built and on the DDL the startup step issues, which is where
the two mistakes that matter would actually show up: ranking the inline
expression while believing the index is being used, or hard-failing every
question on a boot where the migration was skipped.
"""
from __future__ import annotations

import pytest

from app.domains.documents import service


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    """The availability probe caches per process; tests must not leak into each
    other, nor into the rest of the suite."""
    service._SEARCH_VECTOR_READY = None
    yield
    service._SEARCH_VECTOR_READY = None


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeDb:
    """Records what was executed and answers the column probe."""

    def __init__(self, *, column_exists: bool):
        self._column_exists = column_exists
        self.executed: list[str] = []

    async def execute(self, statement, params=None):
        self.executed.append(str(statement))
        return _FakeResult((1,) if self._column_exists else None)


def test_ranks_on_the_stored_column_when_it_exists():
    sql = service._search_sql(service.STORED_VECTOR)
    assert "ts_rank_cd(\n                   c.search_vector," in sql
    # Both the ranking and the match must use the column. Leaving the @@ on the
    # inline expression would keep the sequential scan while looking correct.
    assert sql.count("c.search_vector") == 2
    assert "to_tsvector" not in sql


def test_falls_back_to_the_inline_expression():
    sql = service._search_sql(service.INLINE_VECTOR)
    assert sql.count("to_tsvector('english', c.content)") == 2
    assert "search_vector" not in sql


def test_both_forms_keep_the_ownership_filters():
    # RLS is the guarantee, these are the belt-and-braces. A rewritten query
    # that dropped them would leak another user's chunks on a superuser
    # connection, which Postgres exempts from RLS entirely.
    for vector in (service.STORED_VECTOR, service.INLINE_VECTOR):
        sql = service._search_sql(vector)
        assert "c.tenant_id = :tenant_id" in sql
        assert "c.user_id = :user_id" in sql
        assert "c.document_id = ANY(:document_ids)" in sql


@pytest.mark.asyncio
async def test_probe_detects_a_present_column():
    db = _FakeDb(column_exists=True)
    assert await service._search_vector_available(db) is True
    assert "information_schema.columns" in db.executed[0]


@pytest.mark.asyncio
async def test_probe_detects_a_missing_column():
    # The boot where _migrate_document_search_vector could not take the table
    # lock. Search must get slower, not start raising UndefinedColumn.
    db = _FakeDb(column_exists=False)
    assert await service._search_vector_available(db) is False


@pytest.mark.asyncio
async def test_probe_runs_once_per_process():
    db = _FakeDb(column_exists=True)
    for _ in range(5):
        await service._search_vector_available(db)
    assert len(db.executed) == 1


def test_startup_migration_stores_the_column_and_indexes_it():
    import inspect

    from app import main

    source = inspect.getsource(main._migrate_document_search_vector)
    # STORED, not VIRTUAL: a virtual column is recomputed on read, which is the
    # cost this change exists to remove, and Postgres cannot index one.
    assert "STORED" in source
    assert "GENERATED ALWAYS AS" in source
    assert "USING GIN" in source
    # Re-running a startup step must be safe — the lifespan retries skipped
    # steps on the next boot.
    assert "IF NOT EXISTS" in source
    # SQLite has no tsvector; the step must not run there.
    assert "is_sqlite" in source


def test_startup_migration_is_registered_in_the_lifespan():
    import inspect

    from app import main

    source = inspect.getsource(main.lifespan)
    assert "_migrate_document_search_vector" in source
