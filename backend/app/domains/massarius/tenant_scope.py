"""
Massarius™ retrieval and evidence subsystem — tenant isolation enforcement
(ZL-ENG-03 §5.8, Acceptance Criterion 5).

Enforcement lives at the data-access layer, not only in application logic:
Postgres RLS on tenant-scoped tables, backed by a non-superuser DB role
(see app/core/database.py's request_engine / app/main.py's _provision_app_role,
built for sources/source_versions earlier and extended here to cover the
vector-store table the live semantic retrieval layer uses).

This module must NOT contain retrieval or licence logic itself — only tenant
scoping enforcement and the test helpers used to prove it holds.

Known, flagged limitation (see docstring on ensure_vector_table_rls below):
kriton_vector_nodes RLS can only take effect for a connection made through
the non-superuser role. The live vector retrieval in
app/domains/rag/retrieval.py opens its own connection directly from
settings.DATABASE_URL (the superuser role), which unconditionally bypasses
RLS — Postgres exempts superusers regardless of any policy. Closing that
would mean changing which connection string retrieval.py uses, which is
inside app/domains/rag/ and out of scope here. What this module provides is
real, correct DB-level enforcement for any connection that *does* go through
the scoped role (proven by the test helpers below), plus the same enable/
force/policy setup already applied to sources/source_versions — it does not
yet reach the vector table's actual live query path.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

VECTOR_TABLE = "kriton_vector_nodes"


def _pg_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def table_exists(conn: AsyncConnection, table_name: str) -> bool:
    result = await conn.execute(text("SELECT to_regclass(:name)"), {"name": table_name})
    return result.scalar() is not None


async def ensure_vector_table_rls(conn: AsyncConnection, *, role: str) -> bool:
    """Enable + force RLS and install a tenant_id policy on kriton_vector_nodes,
    matching the same non-superuser role already provisioned for
    sources/source_versions in app/main.py's _provision_app_role.

    kriton_vector_nodes is created lazily by llama-index's PGVectorStore on
    first real retrieval call, not by Base.metadata.create_all — so this is a
    no-op (returns False) until that first call has happened at least once.
    Re-running this after ingestion is safe and idempotent; call it again
    once you know the table exists (e.g. after a manual ingestion run) if it
    returned False at startup.
    """
    if not await table_exists(conn, VECTOR_TABLE):
        return False

    policy = f"tenant_isolation_{VECTOR_TABLE}"
    await conn.execute(text(f"ALTER TABLE {VECTOR_TABLE} ENABLE ROW LEVEL SECURITY"))
    await conn.execute(text(f"ALTER TABLE {VECTOR_TABLE} FORCE ROW LEVEL SECURITY"))
    await conn.execute(text(f"DROP POLICY IF EXISTS {policy} ON {VECTOR_TABLE}"))
    # llama-index's PGVectorStore stores arbitrary node metadata (including
    # tenant_id) in a JSONB column, not a plain string column — this differs
    # from sources/source_versions, which have a real tenant_id column.
    await conn.execute(
        text(
            f"CREATE POLICY {policy} ON {VECTOR_TABLE} "
            "USING (metadata_->>'tenant_id' = current_setting('app.tenant_id', true))"
        )
    )
    await conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {VECTOR_TABLE} TO {_pg_ident(role)}'))
    return True


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
