"""
RG-02 — proves Postgres RLS actually isolates tenants at the DB layer, not
just in application code. Requires a live Postgres connection (the RLS
policies + the non-superuser APP_DATABASE_URL role only exist there); skips
itself under SQLite, same as app/main.py's own RLS setup does.

Run inside the backend container, where app.* and the Postgres connection
are both available:
    docker compose exec backend python3 tests/test_tenant_isolation.py
"""
import asyncio
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, RequestSessionLocal
from app.domains.identity.models import Tenant, User
from app.domains.source_library.models import Source, SourceVersion

settings = get_settings()


async def _make_tenant_with_source(
    db, *, tenant_name: str, source_title: str, is_tenant_private: bool = True
) -> tuple[str, str]:
    """Writes go through AsyncSessionLocal (the superuser connection) — this
    is trusted setup code, not a tenant-scoped request, so it must bypass
    RLS's WITH CHECK the same way the seed scripts do.

    is_tenant_private=True by default: this test proves *private* sources
    don't leak across tenants. Non-private sources (the column's own
    default) are deliberately shared across every tenant per
    massarius/license_gate.py's Checkpoint A — see
    test_non_private_source_is_shared_across_tenants below, which locks in
    that this is by design, not something a future change should "fix"
    back into strict isolation."""
    tenant = Tenant(name=tenant_name)
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=f"{uuid.uuid4().hex[:8]}@tenant-isolation-test.local",
        hashed_password="unused",
        full_name="Isolation Test User",
        role="Admin",
    )
    db.add(user)
    await db.flush()

    source = Source(
        tenant_id=tenant.id,
        category="tax",
        title=source_title,
        source_class="internal",
        is_tenant_private=is_tenant_private,
    )
    db.add(source)
    await db.flush()

    version = SourceVersion(tenant_id=tenant.id, source_id=source.id, status="ACTIVE", submitted_by=user.id)
    db.add(version)
    await db.commit()

    return tenant.id, source.id


async def _visible_titles_as_tenant(tenant_id: str) -> list[str]:
    """Reads go through RequestSessionLocal (the non-superuser APP_DATABASE_URL
    role) with app.tenant_id set for this transaction only — exactly what
    get_db() does per-request in app/core/database.py."""
    async with RequestSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
        result = await db.execute(text("SELECT title FROM sources"))
        return [row[0] for row in result.all()]


async def test_tenant_cannot_see_another_tenants_sources():
    if settings.is_sqlite:
        print("test_tenant_cannot_see_another_tenants_sources: SKIPPED (SQLite has no RLS)")
        return

    async with AsyncSessionLocal() as db:
        tenant_a_id, _ = await _make_tenant_with_source(
            db, tenant_name="Isolation Test Tenant A", source_title="Tenant A Only Doc"
        )
        tenant_b_id, _ = await _make_tenant_with_source(
            db, tenant_name="Isolation Test Tenant B", source_title="Tenant B Only Doc"
        )

    try:
        titles_a = await _visible_titles_as_tenant(tenant_a_id)
        titles_b = await _visible_titles_as_tenant(tenant_b_id)

        assert "Tenant A Only Doc" in titles_a
        assert "Tenant B Only Doc" not in titles_a
        assert "Tenant B Only Doc" in titles_b
        assert "Tenant A Only Doc" not in titles_b
        print("test_tenant_cannot_see_another_tenants_sources: PASSED")
    finally:
        async with AsyncSessionLocal() as db:
            for tid in (tenant_a_id, tenant_b_id):
                await db.execute(text("DELETE FROM source_versions WHERE tenant_id = :t"), {"t": tid})
                await db.execute(text("DELETE FROM sources WHERE tenant_id = :t"), {"t": tid})
                await db.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": tid})
                await db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
            await db.commit()


async def test_non_private_source_is_shared_across_tenants():
    """The RLS policy's other half: a source that is NOT marked tenant-private
    must be visible to every tenant, not just its owning tenant_id — matching
    massarius/license_gate.py's Checkpoint A, which treats is_tenant_private=False
    as shared-by-design (e.g. regulatory standards). A strict tenant_id-equality
    policy would hide these from everyone but the literal owning tenant."""
    if settings.is_sqlite:
        print("test_non_private_source_is_shared_across_tenants: SKIPPED (SQLite has no RLS)")
        return

    async with AsyncSessionLocal() as db:
        owner_tenant_id, _ = await _make_tenant_with_source(
            db, tenant_name="Isolation Test Shared Owner", source_title="Shared Standard Doc",
            is_tenant_private=False,
        )
        other_tenant_id, _ = await _make_tenant_with_source(
            db, tenant_name="Isolation Test Shared Viewer", source_title="Shared Viewer's Own Doc",
            is_tenant_private=True,
        )

    try:
        titles_as_other = await _visible_titles_as_tenant(other_tenant_id)
        assert "Shared Standard Doc" in titles_as_other, "non-private source must be visible to other tenants"
        assert "Shared Viewer's Own Doc" in titles_as_other
        print("test_non_private_source_is_shared_across_tenants: PASSED")
    finally:
        async with AsyncSessionLocal() as db:
            for tid in (owner_tenant_id, other_tenant_id):
                await db.execute(text("DELETE FROM source_versions WHERE tenant_id = :t"), {"t": tid})
                await db.execute(text("DELETE FROM sources WHERE tenant_id = :t"), {"t": tid})
                await db.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": tid})
                await db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
            await db.commit()


async def test_no_tenant_context_sees_nothing():
    """A session with no app.tenant_id set (current_setting returns NULL)
    must see zero rows — RLS fails closed, not open."""
    if settings.is_sqlite:
        print("test_no_tenant_context_sees_nothing: SKIPPED (SQLite has no RLS)")
        return

    async with RequestSessionLocal() as db:
        result = await db.execute(text("SELECT title FROM sources"))
        rows = result.all()
        assert rows == []
        print("test_no_tenant_context_sees_nothing: PASSED")


async def main():
    await test_tenant_cannot_see_another_tenants_sources()
    await test_non_private_source_is_shared_across_tenants()
    await test_no_tenant_context_sees_nothing()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
