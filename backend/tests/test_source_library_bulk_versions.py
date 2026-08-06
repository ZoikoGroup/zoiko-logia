import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace
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


@pytest.mark.asyncio
async def test_list_sources_retries_a_transient_empty_catalogue_read():
    source = SimpleNamespace(id="src-fred", category="interest-rates")
    version = SimpleNamespace(source_id="src-fred")

    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    source_result = MagicMock()
    source_result.scalars.return_value.all.return_value = [source]
    version_result = MagicMock()
    version_result.scalars.return_value.all.return_value = [version]

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[empty_result, source_result, version_result])

    rows = await list_sources(db, "interest-rates", tenant_id="tenant")

    assert len(rows) == 1
    assert rows[0]["id"] == "src-fred"
    assert rows[0]["latest_version"] is version
    assert db.execute.await_count == 3
