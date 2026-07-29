"""
Massarius™ retrieval and evidence subsystem — tenant isolation enforcement
(ZL-ENG-03 §5.8, Acceptance Criterion 5).

Enforcement lives at the data-access layer, not only in application logic:
Postgres RLS on tenant-scoped tables, backed by a non-superuser DB role
(see app/core/database.py's request_engine / app/main.py's _provision_app_role).

This module must NOT contain retrieval or licence logic itself — only tenant
scoping enforcement and the test helpers used to prove it holds.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_session_tenant(session: AsyncSession, tenant_id: str) -> None:
    """Scope a session to a tenant for the remainder of its transaction —
    the same set_config(..., true) pattern app/core/database.py's get_db()
    uses per-request. Exposed here so tests and any Massarius™ module that
    opens its own session can scope it without reimplementing this."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id}
    )


async def assert_tenant_isolated(
    request_sessionmaker,
    *,
    table: str,
    tenant_a: str,
    tenant_b: str,
    id_column: str = "id",
) -> None:
    """Test helper — proves cross-tenant leakage is impossible at the query
    layer, not just the API layer (Acceptance Criterion 5). Opens a fresh
    session scoped to tenant_a and asserts it cannot see any row belonging
    to tenant_b in `table`, using a plain unfiltered SELECT * — i.e. even a
    query that forgets to filter by tenant_id itself must still come back
    empty for another tenant's rows, because RLS is doing the filtering.

    Raises AssertionError on leakage; returns None on success.
    """
    async with request_sessionmaker() as session:
        await set_session_tenant(session, tenant_a)
        result = await session.execute(text(f"SELECT {id_column} FROM {table}"))
        visible_ids = {row[0] for row in result.all()}

    async with request_sessionmaker() as session:
        await set_session_tenant(session, tenant_b)
        result = await session.execute(text(f"SELECT {id_column} FROM {table}"))
        tenant_b_ids = {row[0] for row in result.all()}

    leaked = visible_ids & tenant_b_ids
    assert not leaked, f"Tenant isolation violated on {table}: tenant_a saw tenant_b rows {leaked}"
