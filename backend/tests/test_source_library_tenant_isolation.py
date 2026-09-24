"""Tenant isolation regression tests for the source-library read/mutation
helpers that were previously unscoped.

Each test seeds two tenants' private sources and asserts that calling the
function in tenant A's context never returns or mutates tenant B's private
rows, matching the boundary list_sources already enforces (non-private
sources are shared by design — Checkpoint A; is_tenant_private=True rows are
owner-only).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.identity.models import Tenant, User
from app.domains.source_library.models import Source, SourceVersion
from app.domains.source_library.service import (
    expire_source_versions,
    get_jurisdiction_summary,
    get_soonest_expiring,
)


@pytest.fixture
async def source_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        yield db
    await engine.dispose()


async def _seed_private_source(
    db, tenant, *, title: str, jurisdiction: str, category: str, status: str, effective_to: date | None,
) -> Source:
    user = User(
        tenant_id=tenant.id, email=f"{uuid.uuid4().hex[:8]}@tenant-isolation.local",
        full_name="Isolation User", role="Admin",
    )
    db.add(user)
    await db.flush()
    source = Source(
        tenant_id=tenant.id, category=category, title=title, source_class="internal",
        jurisdiction_scope=jurisdiction, is_tenant_private=True,
    )
    db.add(source)
    await db.flush()
    db.add(SourceVersion(
        tenant_id=tenant.id, source_id=source.id, status=status,
        submitted_by=user.id, effective_to=effective_to,
    ))
    await db.flush()
    return source


async def _new_tenant(db, name: str) -> Tenant:
    tenant = Tenant(name=name)
    db.add(tenant)
    await db.flush()
    return tenant


async def test_get_soonest_expiring_never_leaks_another_tenants_private_source(source_db) -> None:
    tenant_a = await _new_tenant(source_db, "A")
    tenant_b = await _new_tenant(source_db, "B")
    await _seed_private_source(
        source_db, tenant_a, title="A private", jurisdiction="GR", category="tax",
        status="ACTIVE", effective_to=date.today() + timedelta(days=30),
    )
    await _seed_private_source(
        source_db, tenant_b, title="B private", jurisdiction="FR", category="tax",
        status="ACTIVE", effective_to=date.today() + timedelta(days=3),
    )
    await source_db.commit()

    a = await get_soonest_expiring(source_db, tenant_a.id)
    assert a is not None and a["title"] == "A private", "B's sooner-expiring private source shadowed A's result"
    b = await get_soonest_expiring(source_db, tenant_b.id)
    assert b is not None and b["title"] == "B private"

    no_owner = await get_soonest_expiring(source_db, "tenant-that-owns-nothing")
    assert no_owner is None, "a tenant owning no private/shared sources must not see another tenant's rows"


async def test_get_jurisdiction_summary_only_counts_own_tenants_private_sources(source_db) -> None:
    tenant_a = await _new_tenant(source_db, "A")
    tenant_b = await _new_tenant(source_db, "B")
    for jurisdiction in ("GR", "EU"):
        await _seed_private_source(
            source_db, tenant_a, title=f"A {jurisdiction}", jurisdiction=jurisdiction,
            category="tax", status="ACTIVE", effective_to=None,
        )
    await _seed_private_source(
        source_db, tenant_b, title="B one", jurisdiction="FR", category="tax",
        status="APPROVED", effective_to=None,
    )
    await _seed_private_source(
        source_db, tenant_b, title="B two", jurisdiction="FR", category="tax",
        status="APPROVED", effective_to=None,
    )
    await source_db.commit()

    summaries = await get_jurisdiction_summary(source_db, tenant_a.id)
    jurisdictions = {s["jurisdiction_scope"] for s in summaries}
    assert jurisdictions == {"GR", "EU"}, f"tenant B's private FR sources leaked into A's summary: {jurisdictions}"
    gr = next(s for s in summaries if s["jurisdiction_scope"] == "GR")
    assert gr["approved_count"] == 1


async def test_expire_source_versions_only_expires_own_tenants_private_sources(source_db) -> None:
    past = date.today() - timedelta(days=10)
    future = date.today() + timedelta(days=10)
    tenant_a = await _new_tenant(source_db, "A")
    tenant_b = await _new_tenant(source_db, "B")
    tenant_c = await _new_tenant(source_db, "C")
    a_src = await _seed_private_source(source_db, tenant_a, title="A past", jurisdiction="GR", category="tax", status="ACTIVE", effective_to=past)
    b_src = await _seed_private_source(source_db, tenant_b, title="B past", jurisdiction="FR", category="tax", status="ACTIVE", effective_to=past)
    c_src = await _seed_private_source(source_db, tenant_c, title="C future", jurisdiction="DE", category="tax", status="ACTIVE", effective_to=future)
    await source_db.commit()

    expired = await expire_source_versions(source_db, tenant_id=tenant_a.id, today=date.today())
    assert expired == 1, "tenant A must expire exactly its own one past-due version"

    async def _status(source: Source) -> str:
        row = (
            await source_db.execute(
                select(SourceVersion.status)
                .where(SourceVersion.source_id == source.id)
            )
        ).scalar_one()
        return row

    assert await _status(a_src) == "EXPIRED"
    assert await _status(b_src) == "ACTIVE", "tenant A's expire job mutated tenant B's private version"
    assert await _status(c_src) == "ACTIVE", "a version not yet past-due must not be expired"