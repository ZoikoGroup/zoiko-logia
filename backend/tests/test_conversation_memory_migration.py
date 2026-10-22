"""Exercise the additive migration only against an isolated SQLite DB."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_conversation_migration_is_additive_and_reentrant(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/a6t7u8v9w0x1_conversation_turns.py'
    spec = importlib.util.spec_from_file_location('memory_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f'sqlite:///{tmp_path / "migration.db"}')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE tenants (id VARCHAR PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE users (id VARCHAR PRIMARY KEY)'))
        connection.execute(text("INSERT INTO tenants VALUES ('original-tenant')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.upgrade()
        assert inspect(connection).has_table('conversation_turns')
        assert connection.scalar(text('SELECT id FROM tenants')) == 'original-tenant'
        names = {c['name'] for c in inspect(connection).get_columns('conversation_turns')}
        assert {'tenant_id', 'user_id', 'conversation_id', 'query_id', 'snapshot', 'expires_at'} <= names
        assert len(inspect(connection).get_unique_constraints('conversation_turns')) == 1
    engine.dispose()
