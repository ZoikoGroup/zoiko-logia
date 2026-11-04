import hashlib
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.domains.source_library.models import SourceVersion, SourcePassage, SourceRight

spec = importlib.util.spec_from_file_location('ingest_govuk_test', Path(__file__).resolve().parents[1] / 'scripts/ingest_govuk.py')
ingestion = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ingestion
spec.loader.exec_module(ingestion)


@pytest.fixture
def storage(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(ingestion, 'SessionLocal', factory)
    yield factory
    engine.dispose()


def document(text='The VAT rate is 20%.'):
    return ingestion.Document('/vat-rates', 'VAT rates', 'https://www.gov.uk/vat-rates',
        datetime(2026, 1, 1, tzinfo=timezone.utc), hashlib.sha256(text.encode()).hexdigest(),
        [ingestion.Passage('#standard', 'Standard rate', text)])


def test_refresh_is_immutable_and_unchanged_versions_are_not_duplicated(storage):
    embedder = SimpleNamespace(embed_passages=lambda texts: [[0.0] * 384 for _ in texts])
    assert ingestion.ingest(document(), 'general', 'reviewer', embedder) == 'proposed'
    assert ingestion.ingest(document(), 'general', 'reviewer', embedder) == 'unchanged'
    assert ingestion.ingest(document('Changed guidance.'), 'general', 'reviewer', embedder) == 'proposed'
    with storage() as db:
        versions = db.scalars(select(SourceVersion)).all()
        assert len(versions) == 2 and all(v.status == 'PROPOSED' for v in versions)
        assert sum(v.superseded_by_version_id is not None for v in versions) == 0
        assert all(v.approved_by is None and v.effective_from is None for v in versions)
        assert all(v.quality_state == "EXTRACTED" and v.published_at is not None for v in versions)
        assert len(db.scalars(select(SourcePassage)).all()) == 2
        assert 'training' not in {right.operation for right in db.scalars(select(SourceRight)).all()}


@pytest.mark.parametrize('vectors', [[], [[0.0] * 383], [[float('nan')] * 384]])
def test_invalid_embeddings_cannot_approve_or_persist_a_version(storage, vectors):
    with pytest.raises(ValueError, match='384-dimensional'):
        ingestion.ingest(document(), 'general', 'reviewer', SimpleNamespace(embed_passages=lambda texts: vectors))
    with storage() as db:
        assert db.scalars(select(SourceVersion)).all() == []


def test_long_lines_keep_preceding_text_and_respect_chunk_bound():
    content = 'Introduction.\n' + 'x' * (ingestion.MAX_PASSAGE_CHARS + 10)
    chunks = ingestion._split_long(content)
    assert chunks[0] == 'Introduction.'
    assert all(len(chunk) <= ingestion.MAX_PASSAGE_CHARS for chunk in chunks)
    assert ''.join(chunks[1:]) == 'x' * (ingestion.MAX_PASSAGE_CHARS + 10)


def test_proposal_preserves_existing_approved_versions_and_history(storage):
    embedder = SimpleNamespace(embed_passages=lambda texts: [[0.0] * 384 for _ in texts])
    ingestion.ingest(document(), 'general', 'submitter', embedder)
    with storage() as db:
        existing = db.scalar(select(SourceVersion))
        existing.status = 'APPROVED'
        existing.approved_by = 'independent-reviewer'
        existing.quality_state = 'APPROVED'
        db.commit()
        fields = ('status', 'approved_by', 'quality_state', 'effective_from',
                  'effective_to', 'superseded_by_version_id', 'published_at', 'content_hash')
        before = {name: getattr(existing, name) for name in fields}
        existing_id = existing.id
    assert ingestion.ingest(document('Changed rule.'), 'general', 'submitter', embedder) == 'proposed'
    with storage() as db:
        existing = db.get(SourceVersion, existing_id)
        assert {name: getattr(existing, name) for name in fields} == before
        proposal = db.scalar(select(SourceVersion).where(SourceVersion.id != existing_id))
        assert proposal.status == 'PROPOSED'
        assert proposal.approved_by is None
        assert proposal.effective_from is None
