"""Explicit schema setup, run before uvicorn or as a pre-deploy command.

No schema changes or seeds run during application startup. Existing databases
must have a valid Alembic revision; --adopt-existing is only for a verified
legacy database created using ORM create_all, not a normal deployment.
"""
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def migrate(*, adopt_existing: bool = False) -> None:
    from app.core.database import engine
    config = Config(str(BACKEND / "alembic.ini"))
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar() if "alembic_version" in tables else None
    if tables - {"alembic_version"} and not version:
        if not adopt_existing:
            raise RuntimeError("Unversioned existing database: audit it and use --adopt-existing once")
        # Adopt only a schema already containing the previous release's tables
        # and columns, after compatibility setup has reconciled them.
        from app.db.base import Base
        with engine.connect() as conn:
            inspector = inspect(conn)
            missing = [f"{table.name}.{column.name}" for table in Base.metadata.sorted_tables
                       if table.name in tables for column in table.columns
                       if column.name not in {c["name"] for c in inspector.get_columns(table.name)}
                       and column.name not in {"tenant_id", "category", "key_facts"}]
        if missing:
            raise RuntimeError("Cannot adopt incomplete schema: " + ", ".join(missing))
        command.stamp(config, "o4h5i6j7k8l9")
    command.upgrade(config, "head")


async def prepare(*, adopt_existing: bool = False) -> None:
    from app import main
    from app.core.database import async_engine
    try:
        # Legacy compatibility is explicit, and failed steps stop deployment.
        if adopt_existing:
            if not await main._apply_schema_and_seeds():
                raise RuntimeError("Legacy database compatibility setup failed")
        await asyncio.to_thread(migrate, adopt_existing=adopt_existing)
        if not await main._apply_schema_and_seeds():
            raise RuntimeError("Database compatibility setup failed")
        await main._with_ddl_retry(main._setup_source_rls)
        await main._with_ddl_retry(main._setup_user_rls)
        await main._verify_security_policies()
        await main._write_fingerprint(main._startup_fingerprint())
        print("Database prepared; application startup will perform read-only checks.")
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adopt-existing", action="store_true")
    args = parser.parse_args()
    asyncio.run(prepare(adopt_existing=args.adopt_existing))
