"""Exercises the saved_visualizations Alembic migration's upgrade()/
downgrade() functions directly against a scratch SQLite DB, via Alembic's
Operations API rather than the `alembic upgrade` CLI.

The CLI's full chain can't run against SQLite at all — an earlier,
unrelated migration (a1b2c3d4e5f6_supabase_auth_migration.py) issues raw
Postgres RLS DDL ("ALTER TABLE users ENABLE ROW LEVEL SECURITY"), which
SQLite doesn't understand. That's a pre-existing constraint of this
migration chain (Alembic here targets Postgres/Supabase only — see
conftest.py's own docstring), not something this test works around; it
tests this one migration's DDL directly and in isolation instead.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

# alembic/versions/ isn't an importable Python package (no __init__.py,
# loaded dynamically by Alembic's own script directory scanner) — load this
# one migration file directly by path instead.
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "b4682276e830_saved_visualizations.py"
)
_spec = importlib.util.spec_from_file_location("saved_visualizations_migration", _MIGRATION_PATH)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


@pytest.fixture
def scratch_engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path}/migration_scratch.db")
    metadata = sa.MetaData()
    # Only the two tables saved_visualizations foreign-keys against — enough
    # for the migration's create_table/FK constraints to apply cleanly.
    sa.Table("tenants", metadata, sa.Column("id", sa.String, primary_key=True))
    sa.Table("users", metadata, sa.Column("id", sa.String, primary_key=True))
    metadata.create_all(engine)
    yield engine
    engine.dispose()


def _table_names(engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def test_upgrade_creates_the_table_on_an_empty_database(scratch_engine):
    assert "saved_visualizations" not in _table_names(scratch_engine)
    with scratch_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        connection.commit()

    assert "saved_visualizations" in _table_names(scratch_engine)
    columns = {c["name"] for c in sa.inspect(scratch_engine).get_columns("saved_visualizations")}
    assert columns == {
        "id", "tenant_id", "user_id", "query_id", "visualization_type", "schema_version",
        "title", "summary", "payload", "source_references", "created_at", "updated_at",
    }


def test_downgrade_removes_the_table_cleanly(scratch_engine):
    with scratch_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        connection.commit()
    assert "saved_visualizations" in _table_names(scratch_engine)

    with scratch_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.downgrade()
        connection.commit()
    assert "saved_visualizations" not in _table_names(scratch_engine)
