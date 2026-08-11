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
    tenant_b_private_ids: set[str],
    id_column: str = "id",
) -> None:
    """Test helper — proves cross-tenant leakage is impossible at the query
    layer, not just the API layer (Acceptance Criterion 5). Both reads use a
    plain unfiltered `SELECT <id_column> FROM <table>`, so even a query that
    forgets to filter by tenant_id must still come back without another
    tenant's private rows, because RLS is doing the filtering.

    Takes the specific private row ids owned by tenant_b rather than comparing
    what the two tenants can each see. Intersecting the two visible sets looks
    equivalent but is not: non-private rows are deliberately shared with every
    tenant (massarius/license_gate.py's Checkpoint A), so that intersection is
    full of shared-by-design rows and reports leakage on a correctly isolated
    database. Naming the private ids tests the claim that is actually made.

    Also asserts tenant_b can still see its own rows. Without that, the
    isolation assertion would pass trivially on a database where RLS hides
    everything from everyone — a broken policy would look like a clean pass.

    Raises AssertionError on leakage; returns None on success.
    """
    expected = set(tenant_b_private_ids)

    async with request_sessionmaker() as session:
        await set_session_tenant(session, tenant_b)
        result = await session.execute(text(f"SELECT {id_column} FROM {table}"))
        owner_visible = {row[0] for row in result.all()}

    missing = expected - owner_visible
    assert not missing, (
        f"Setup invalid on {table}: tenant_b cannot see its own rows {missing} — "
        "the isolation assertion below would pass vacuously."
    )

    async with request_sessionmaker() as session:
        await set_session_tenant(session, tenant_a)
        result = await session.execute(text(f"SELECT {id_column} FROM {table}"))
        other_visible = {row[0] for row in result.all()}

    leaked = expected & other_visible
    assert not leaked, (
        f"Tenant isolation violated on {table}: tenant_a saw tenant_b private rows {leaked}"
    )
