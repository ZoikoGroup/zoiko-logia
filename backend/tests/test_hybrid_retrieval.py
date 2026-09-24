import hashlib
import os
import sys
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.base import Base
from app.domains.massarius import bundle_builder, license_gate
from app.domains.source_library.models import (
    Source, SourcePassage, SourceRelationship, SourceRight, SourceVersion,
)
from app.orchestration.models import EvidenceBundleEntry, EvidenceBundleManifest
from app.orchestration.retrieve import build_source_bundle


@pytest.fixture
async def retrieval_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _source(
    db, *, title: str, text: str, tenant_id: str = "tenant-a",
    retrieval: bool = True, transmission: bool = True,
):
    source = Source(
        tenant_id=tenant_id, category="standards", title=title,
        publisher="Standards Board", owner="Standards Board",
        source_class="authoritative", jurisdiction_scope="GB",
        framework_scope="IFRS", authority_level="primary",
    )
    db.add(source)
    await db.flush()
    version = SourceVersion(
        tenant_id=tenant_id, source_id=source.id, version_label="2026",
        status="ACTIVE", content_hash=hashlib.sha256(title.encode()).hexdigest(),
        submitted_by="maker", approved_by="checker",
    )
    db.add(version)
    await db.flush()
    passage = SourcePassage(
        tenant_id=tenant_id, source_version_id=version.id, locator="paragraph 1",
        sequence=1, content=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(), language="en",
    )
    db.add(passage)
    for operation, allowed in (
        ("retrieval", retrieval), ("model_transmission", transmission),
        ("display", True), ("summary", True),
    ):
        db.add(SourceRight(
            tenant_id=tenant_id, source_version_id=version.id,
            operation=operation, decision="allow" if allowed else "deny",
            rights_version=1, reason_code="TEST_ALLOW" if allowed else "TEST_DENY",
        ))
    await db.flush()
    return source, version, passage


async def test_retrieval_selects_exact_authorized_passage_and_records_denial(retrieval_db):
    allowed_source, _, allowed_passage = await _source(
        retrieval_db, title="IFRS 15",
        text="Revenue is recognised when a performance obligation is satisfied.",
    )
    denied_source, _, _ = await _source(
        retrieval_db, title="Restricted commentary",
        text="Revenue performance obligation commentary.", retrieval=False,
    )

    bundle = await build_source_bundle(
        retrieval_db,
        query="revenue performance obligation",
        jurisdiction="GB", framework="IFRS", tenant_id="tenant-a",
    )

    assert [item.passage_id for item in bundle.passages] == [allowed_passage.id]
    assert [source.id for source in bundle.sources] == [allowed_source.id]
    assert any(
        item.source_id == denied_source.id and item.reason_code == "TEST_DENY"
        for item in bundle.excluded_evidence
    )
    assert bundle.retrieval_plan.strategy == "rights_filtered_lexical_passages"


async def test_model_transmission_gate_removes_retrieved_passage(retrieval_db):
    source, _, _ = await _source(
        retrieval_db, title="Internal standard",
        text="Impairment uses expected credit losses.", transmission=False,
    )
    preliminary = await build_source_bundle(
        retrieval_db, query="expected credit losses", jurisdiction="GB",
        framework="IFRS", tenant_id="tenant-a",
    )
    decision = await license_gate.check_eligibility(
        retrieval_db, preliminary.sources, tenant_id="tenant-a",
        jurisdiction="GB", framework="IFRS",
    )
    final = bundle_builder.build_bundle(preliminary, decision)

    assert final.sources == []
    assert final.passages == []
    assert any(item.source_id == source.id for item in final.excluded_evidence)


async def test_bundle_is_persisted_and_replay_hash_is_verified(retrieval_db):
    _, _, passage = await _source(
        retrieval_db, title="IFRS 15",
        text="Allocate the transaction price to performance obligations.",
    )
    preliminary = await build_source_bundle(
        retrieval_db, query="transaction price performance obligations",
        jurisdiction="GB", framework="IFRS", tenant_id="tenant-a",
    )
    decision = await license_gate.check_eligibility(
        retrieval_db, preliminary.sources, tenant_id="tenant-a",
        jurisdiction="GB", framework="IFRS",
    )
    final = bundle_builder.build_bundle(preliminary, decision)
    await bundle_builder.persist_bundle(
        retrieval_db, bundle=final, tenant_id="tenant-a", query_id="qry-1",
    )

    manifest = await retrieval_db.get(EvidenceBundleManifest, final.source_bundle_id)
    entries = (await retrieval_db.execute(
        select(EvidenceBundleEntry).where(EvidenceBundleEntry.bundle_id == final.source_bundle_id)
    )).scalars().all()
    replay = await bundle_builder.load_bundle_passage_text(retrieval_db, final)

    assert manifest.manifest["index_version"] == "source-passages-lexical-v1"
    assert any(entry.passage_id == passage.id and entry.disposition == "selected" for entry in entries)
    assert replay == [(passage.id, "paragraph 1", passage.content)]


async def test_conflicting_selected_versions_are_explicit(retrieval_db):
    _, first_version, _ = await _source(
        retrieval_db, title="Standard A", text="Revenue is recognised on delivery.",
    )
    _, second_version, _ = await _source(
        retrieval_db, title="Standard B", text="Revenue is recognised before delivery.",
    )
    retrieval_db.add(SourceRelationship(
        tenant_id="tenant-a", from_version_id=first_version.id,
        to_version_id=second_version.id, relationship_type="conflicts",
    ))
    await retrieval_db.flush()

    bundle = await build_source_bundle(
        retrieval_db, query="revenue recognised delivery", jurisdiction="GB",
        framework="IFRS", tenant_id="tenant-a",
    )

    assert bundle.confidence_state == "conflicting_sources"
    assert set(bundle.conflict_version_ids) == {first_version.id, second_version.id}
