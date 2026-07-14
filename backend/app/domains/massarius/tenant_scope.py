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

Corrected: this previously targeted the wrong table name. LlamaIndex's
PGVectorStore prefixes whatever table_name you pass with "data_" — this
project passes table_name="kriton_vector_nodes" (see rag/retrieval.py,
source_library/ingestion_service.py), so the real table Postgres creates is
"data_kriton_vector_nodes". VECTOR_TABLE here was "kriton_vector_nodes"
(no prefix), which never exists — table_exists() always returned False, so
ensure_vector_table_rls() silently no-op'd on every boot and RLS was never
actually applied to the vector store at all, independent of the
superuser-bypass issue below. Found by actually getting rows into the table
for the first time and checking pg_tables directly.

app/domains/rag/retrieval.py no longer opens a superuser connection for
live vector retrieval either (it now routes through APP_DATABASE_URL and
stamps app.tenant_id via a pool checkout listener — see that module's
docstring) — so with both fixes, this module's RLS setup now actually
reaches the real table on the real live query path, not just the test
helpers below.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

VECTOR_TABLE = "data_kriton_vector_nodes"


def _pg_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def table_exists(conn: AsyncConnection, table_name: str) -> bool:
    result = await conn.execute(text("SELECT to_regclass(:name)"), {"name": table_name})
    return result.scalar() is not None


async def ensure_vector_table_rls(conn: AsyncConnection, *, role: str) -> bool:
    """Enable + force RLS and install a tenant_id policy on
    data_kriton_vector_nodes, matching the same non-superuser role already
    provisioned for sources/source_versions in app/main.py's
    _provision_app_role.

    The table is created lazily by llama-index's PGVectorStore on first
    real ingestion/retrieval call, not by Base.metadata.create_all — so this
    is a no-op (returns False) until that first call has happened at least
    once. Re-running this after ingestion is safe and idempotent; call it
    again once you know the table exists (e.g. after a manual ingestion
    run) if it returned False at startup.

    Known gap, unlike the sources/source_versions policy: this is strict
    tenant_id equality, not the shared-unless-private model
    massarius/license_gate.py applies to sources (is_tenant_private=False
    rows shared across every tenant). Vector chunk metadata (see
    source_library/ingestion_service.py) has no is_tenant_private field yet,
    so a standard embedded under one tenant won't be found via vector
    search by another tenant even when the equivalent Source row is
    public. That's a functional gap (under-sharing), not a security one —
    it fails closed, which is the safe direction — but worth knowing before
    relying on cross-tenant shared standards through the vector path.
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
