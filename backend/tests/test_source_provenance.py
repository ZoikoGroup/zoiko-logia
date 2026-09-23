from datetime import date, datetime, timedelta, timezone
import os
import sys
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.base import Base
from app.domains.source_library.licensing import SourceUseContext, can_use
from app.domains.source_library.models import Source, SourceRight, SourceUsage, SourceVersion
from app.domains.source_library.service import (
    find_impacted_usages,
    list_sources,
    revoke_source_version,
)


@pytest.fixture
async def source_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _version(source_db, *, tenant_id="tenant-a", status="ACTIVE"):
    source = Source(
        tenant_id=tenant_id,
        category="standards",
        title="Registered standard",
        publisher="Standards Board",
        owner="Standards Board",
        source_class="authoritative",
        jurisdiction_scope="GB",
        framework_scope="IFRS",
    )
    source_db.add(source)
    await source_db.flush()
    version = SourceVersion(
        tenant_id=tenant_id,
        source_id=source.id,
        status=status,
        version_label="2026",
        content_hash=uuid.uuid4().hex * 2,
        submitted_by="maker",
        approved_by="checker" if status in {"ACTIVE", "APPROVED"} else None,
    )
    source_db.add(version)
    await source_db.flush()
    return source, version


async def _right(source_db, version, operation, *, decision="allow", rights_version=1, **kwargs):
    source_db.add(SourceRight(
        tenant_id=version.tenant_id,
        source_version_id=version.id,
        operation=operation,
        decision=decision,
        rights_version=rights_version,
        reason_code="LICENCE_GRANTED" if decision == "allow" else "LICENCE_DENIED",
        **kwargs,
    ))
    await source_db.flush()


async def test_unknown_right_is_denied(source_db):
    _, version = await _version(source_db)
    decision = await can_use(
        source_db, version.id,
        SourceUseContext(tenant_id="tenant-a", jurisdiction="GB", framework="IFRS"),
        "model_transmission",
    )
    assert decision.allowed is False
    assert decision.reason_code == "RIGHT_UNKNOWN"


async def test_right_is_operation_specific_and_latest_version_wins(source_db):
    _, version = await _version(source_db)
    await _right(source_db, version, "retrieval", decision="allow", rights_version=1)
    await _right(source_db, version, "retrieval", decision="deny", rights_version=2)
    retrieval = await can_use(
        source_db, version.id, SourceUseContext(tenant_id="tenant-a"), "retrieval"
    )
    export = await can_use(
        source_db, version.id, SourceUseContext(tenant_id="tenant-a"), "export"
    )
    assert retrieval.allowed is False
    assert retrieval.reason_code == "LICENCE_DENIED"
    assert retrieval.rights_version == 2
    assert export.reason_code == "RIGHT_UNKNOWN"


async def test_expired_and_context_inapplicable_rights_are_denied(source_db):
    _, version = await _version(source_db)
    await _right(
        source_db, version, "retrieval",
        valid_to=datetime.now(timezone.utc) - timedelta(days=1),
    )
    expired = await can_use(
        source_db, version.id,
        SourceUseContext(tenant_id="tenant-a", jurisdiction="GB", framework="IFRS"),
        "retrieval",
    )
    wrong_jurisdiction = await can_use(
        source_db, version.id,
        SourceUseContext(tenant_id="tenant-a", jurisdiction="US", framework="IFRS"),
        "retrieval",
    )
    assert expired.reason_code == "RIGHT_EXPIRED"
    assert wrong_jurisdiction.reason_code == "JURISDICTION_MISMATCH"


async def test_retrieval_prefilter_returns_only_explicitly_allowed_sources(source_db):
    allowed_source, allowed_version = await _version(source_db)
    await _right(source_db, allowed_version, "retrieval")
    denied_source, _ = await _version(source_db)
    denied_source.title = "No retrieval right"
    await source_db.commit()

    sources = await list_sources(
        source_db,
        "standards",
        tenant_id="tenant-a",
        operation="retrieval",
        jurisdiction="GB",
        framework="IFRS",
        effective_date=date(2026, 9, 22),
    )
    assert [source["id"] for source in sources] == [allowed_source.id]


async def test_approved_source_content_is_immutable(source_db):
    _, version = await _version(source_db)
    await source_db.commit()
    version.content_hash = "b" * 64
    with pytest.raises(ValueError, match="immutable"):
        await source_db.flush()
    await source_db.rollback()


async def test_revocation_preserves_and_reports_affected_artifacts(source_db):
    _, version = await _version(source_db)
    source_db.add(SourceUsage(
        tenant_id="tenant-a",
        source_version_id=version.id,
        artifact_type="answer",
        artifact_id="qry-123",
        operation="model_transmission",
    ))
    await source_db.commit()

    revoked = await revoke_source_version(
        source_db, version_id=version.id, tenant_id="tenant-a", reason="Publisher withdrew permission"
    )
    impacts = await find_impacted_usages(source_db, version_id=version.id, tenant_id="tenant-a")
    decision = await can_use(
        source_db, version.id, SourceUseContext(tenant_id="tenant-a"), "model_transmission"
    )

    assert revoked.status == "WITHDRAWN"
    assert revoked.revoked_at is not None
    assert [impact.artifact_id for impact in impacts] == ["qry-123"]
    assert decision.allowed is False
    assert decision.reason_code == "SOURCE_REVOKED"
