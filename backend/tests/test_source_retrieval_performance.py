import asyncio
from types import SimpleNamespace

import pytest

from app.domains.source_library.models import Source, SourceVersion
from app.domains.source_library.service import list_sources
from app.orchestration import retrieve


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _CountingSession:
    def __init__(self, rows):
        self.rows = rows
        self.execute_count = 0

    async def execute(self, _query):
        self.execute_count += 1
        return _RowsResult(self.rows)


@pytest.mark.asyncio
async def test_list_sources_fetches_sources_and_latest_versions_in_one_query():
    source_a = Source(id="source-a", tenant_id="tenant-a", category="standards", title="A", source_class="standard")
    source_b = Source(id="source-b", tenant_id="tenant-a", category="standards", title="B", source_class="standard")
    version_a = SourceVersion(id="version-a", tenant_id="tenant-a", source_id="source-a", status="ACTIVE", submitted_by="user-a")
    version_b = SourceVersion(id="version-b", tenant_id="tenant-a", source_id="source-b", status="APPROVED", submitted_by="user-a")
    db = _CountingSession([(source_a, version_a), (source_b, version_b)])

    rows = await list_sources(db, "standards", tenant_id="tenant-a")

    assert db.execute_count == 1
    assert [row["latest_version"].id for row in rows] == ["version-a", "version-b"]


@pytest.mark.asyncio
async def test_source_retrieval_has_a_bounded_fail_soft_deadline(monkeypatch):
    async def never_returns(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(retrieve, "list_sources", never_returns)
    monkeypatch.setenv("SOURCE_RETRIEVAL_TIMEOUT_SECONDS", "0.01")

    # The configured value is clamped to one second to prevent accidental
    # zero/negative production deadlines; patch the helper for a fast unit test.
    monkeypatch.setattr(retrieve, "_retrieval_timeout_seconds", lambda: 0.01)

    with pytest.raises(TimeoutError):
        await retrieve.build_source_bundle(
            SimpleNamespace(), query="What is IFRS?", jurisdiction="", tenant_id="tenant-a"
        )
