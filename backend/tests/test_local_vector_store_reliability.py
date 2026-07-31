import pytest
from llama_index.core import StorageContext
from llama_index.core.embeddings import MockEmbedding

import app.domains.source_library.ingestion_service as ingestion
from app.domains.rag.embeddings import EMBED_DIM


class _SourceLookup:
    def scalar_one_or_none(self):
        return False


class _Database:
    async def execute(self, statement):
        return _SourceLookup()


def _metadata(source_id: str, title: str) -> dict:
    return {
        "source_id": source_id,
        "title": title,
        "category": "tax",
        "jurisdiction_scope": "US",
        "version_label": "v1",
        "tenant_id": "tenant-1",
    }


@pytest.mark.asyncio
async def test_local_ingestion_appends_without_overwriting(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        ingestion.settings,
        "DATABASE_URL",
        "sqlite+aiosqlite:///:memory:",
    )
    monkeypatch.setattr(
        ingestion.settings,
        "LOCAL_VECTOR_STORE_DIR",
        str(tmp_path),
    )
    monkeypatch.setattr(
        ingestion,
        "get_embed_model",
        lambda: MockEmbedding(embed_dim=EMBED_DIM),
    )

    await ingestion.ingest_document_content(
        "first.md",
        "# First\nFirst governed document.",
        _metadata("source-1", "First"),
        _Database(),
    )
    first = StorageContext.from_defaults(
        persist_dir=str(tmp_path),
    )
    first_count = len(
        first.vector_store.data.embedding_dict
    )

    await ingestion.ingest_document_content(
        "second.md",
        "# Second\nSecond governed document.",
        _metadata("source-2", "Second"),
        _Database(),
    )
    second = StorageContext.from_defaults(
        persist_dir=str(tmp_path),
    )
    second_count = len(
        second.vector_store.data.embedding_dict
    )

    assert first_count > 0
    assert second_count > first_count
