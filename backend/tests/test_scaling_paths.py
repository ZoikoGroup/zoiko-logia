from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.kriton_workspace.documents import retrieve_document_sources
from app.domains.orchestration_state.models import IdempotencyRecord
from app.orchestration.identifiers import check_idempotency, store_idempotency


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _DocumentSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _statement):
        return _Rows(self.rows)


@pytest.mark.asyncio
async def test_full_document_retrieval_is_not_limited_to_question_top_k():
    document = SimpleNamespace(id="doc-1", filename="large.xlsx")
    rows = [
        (SimpleNamespace(text=f"row {index}", ordinal=index, location=f"Sheet!{index}"), document)
        for index in range(12)
    ]
    db = _DocumentSession(rows)

    full = await retrieve_document_sources(
        db, query="management report", document_ids=["doc-1"],
        tenant_id="tenant-1", user_id="user-1", full_document=True,
    )
    targeted = await retrieve_document_sources(
        db, query="row", document_ids=["doc-1"],
        tenant_id="tenant-1", user_id="user-1", full_document=False,
    )

    assert len(full) == 12
    assert len(targeted) == 8


@pytest.mark.asyncio
async def test_idempotency_response_is_shared_through_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: IdempotencyRecord.__table__.create(sync_connection)
        )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as first:
            await store_idempotency(
                first, "key-1", "tenant-1", "request-a", {"outcome": "answered"}
            )
        async with sessions() as second:
            cached = await check_idempotency(second, "key-1", "tenant-1", "request-a")
            assert cached == {"outcome": "answered"}
            with pytest.raises(ValueError, match="different request"):
                await check_idempotency(second, "key-1", "tenant-1", "request-b")
    finally:
        await engine.dispose()

