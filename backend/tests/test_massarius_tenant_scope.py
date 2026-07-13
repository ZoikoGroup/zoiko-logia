"""
ZL-ENG-03 Acceptance Criterion 5 — tenant_id is enforced at the data-access
layer; a test that bypasses application-layer checks directly at the query
layer must confirm isolation still holds.

Requires live Postgres (RLS is Postgres-only) — run inside the backend
container:
    docker compose exec backend python3 tests/test_massarius_tenant_scope.py
"""
import asyncio
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, RequestSessionLocal
from app.domains.massarius.tenant_scope import assert_tenant_isolated, table_exists
from app.domains.source_library.models import Source

settings = get_settings()


async def test_sources_table_isolated_bypassing_application_layer():
    """Proves isolation at the query layer itself: two raw, unfiltered
    `SELECT id FROM sources` calls, one per tenant session, using
    RequestSessionLocal (the non-superuser role) directly — no
    application-layer WHERE tenant_id=... clause written by this test."""
    if settings.is_sqlite:
        print("test_sources_table_isolated_bypassing_application_layer: SKIPPED (SQLite has no RLS)")
        return

    tenant_a = f"tenant-a-{uuid.uuid4().hex[:8]}"
    tenant_b = f"tenant-b-{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        source_a = Source(tenant_id=tenant_a, category="tax", title="Tenant A Only", source_class="internal")
        source_b = Source(tenant_id=tenant_b, category="tax", title="Tenant B Only", source_class="internal")
        db.add_all([source_a, source_b])
        await db.commit()
        ids = [source_a.id, source_b.id]

    try:
        await assert_tenant_isolated(
            RequestSessionLocal, table="sources", tenant_a=tenant_a, tenant_b=tenant_b,
        )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(Source.__table__.delete().where(Source.id.in_(ids)))
            await db.commit()
    print("test_sources_table_isolated_bypassing_application_layer: PASSED")


async def test_no_tenant_context_sees_nothing():
    """RLS must fail closed: a session with no app.tenant_id set sees zero
    rows, not the full unfiltered table."""
    if settings.is_sqlite:
        print("test_no_tenant_context_sees_nothing: SKIPPED (SQLite has no RLS)")
        return
    async with RequestSessionLocal() as db:
        result = await db.execute(text("SELECT id FROM sources"))
        assert result.all() == []
    print("test_no_tenant_context_sees_nothing: PASSED")


async def test_vector_table_rls_known_limitation():
    """Documents rather than silently skips the flagged gap: kriton_vector_nodes
    RLS (if the table exists) only applies to a connection made through the
    non-superuser role. The live retrieval path in
    app/domains/rag/retrieval.py connects via the superuser DATABASE_URL
    directly, so RLS does not reach that query path yet — see
    massarius/tenant_scope.py's module docstring."""
    if settings.is_sqlite:
        print("test_vector_table_rls_known_limitation: SKIPPED (SQLite has no RLS)")
        return
    async with AsyncSessionLocal() as db:
        exists = await table_exists(db, "kriton_vector_nodes")  # type: ignore[arg-type]
    print(
        f"test_vector_table_rls_known_limitation: NOTED (table_exists={exists}) — "
        "RLS policy applies only to non-superuser connections; the live vector "
        "retrieval path does not use one. This is a known, flagged gap, not a pass."
    )


async def main():
    await test_sources_table_isolated_bypassing_application_layer()
    await test_no_tenant_context_sees_nothing()
    await test_vector_table_rls_known_limitation()
    print("All tests completed (see notes above for the flagged vector-table limitation).")


if __name__ == "__main__":
    asyncio.run(main())
