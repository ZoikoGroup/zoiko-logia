"""Provision the schema and RLS policies for Postgres integration tests."""

import asyncio

from app.db.base import Base
from app.main import (
    _migrate_safety_tenant_columns,
    _migrate_source_licence_columns,
    _migrate_tenant_columns,
    _migrate_user_profile_columns,
    _setup_source_rls,
    _setup_user_rls,
    async_engine,
)


async def main() -> None:
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    await _migrate_tenant_columns()
    await _migrate_source_licence_columns()
    await _migrate_user_profile_columns()
    await _migrate_safety_tenant_columns()
    await _setup_source_rls()
    await _setup_user_rls()
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
