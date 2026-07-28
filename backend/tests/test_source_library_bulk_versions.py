import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.source_library.models import Source, SourceVersion
from app.domains.source_library.service import list_sources


@pytest.mark.asyncio
async def test_list_sources_selects_latest_versions_in_bulk():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add(Source(id="src-1", category="audit", title="Source", source_class="authority"))
        db.add_all([
            SourceVersion(id="v1", source_id="src-1", version_label="old", submitted_by="user", status="ACTIVE"),
            SourceVersion(id="v2", source_id="src-1", version_label="new", submitted_by="user", status="ACTIVE"),
        ])
        await db.commit()
        rows = await list_sources(db, tenant_id="tenant")
        assert len(rows) == 1
        assert rows[0]["latest_version"].version_label == "new"
    await engine.dispose()
