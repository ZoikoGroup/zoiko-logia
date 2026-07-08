from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.source_library.models import Source, SourceVersion
from app.domains.source_library.schemas import SourceCreateRequest


async def _latest_version(db: AsyncSession, source_id: str) -> SourceVersion:
    result = await db.execute(
        select(SourceVersion)
        .where(SourceVersion.source_id == source_id)
        .order_by(SourceVersion.created_at.desc())
    )
    return result.scalars().first()


async def list_sources(db: AsyncSession, category: str | None = None) -> list[dict]:
    query = select(Source)
    if category:
        query = query.where(Source.category == category)
    result = await db.execute(query)
    sources = result.scalars().all()

    combined = []
    for source in sources:
        latest = await _latest_version(db, source.id)
        combined.append({**source.__dict__, "latest_version": latest})
    return combined


async def create_source(
    db: AsyncSession, submitted_by: str, payload: SourceCreateRequest, tenant_id: str = "GLOBAL_CONTROL"
) -> dict:
    source = Source(
        category=payload.category,
        title=payload.title,
        source_class=payload.source_class,
        jurisdiction_scope=payload.jurisdiction_scope,
        framework_scope=payload.framework_scope,
    )
    db.add(source)
    await db.flush()

    version = SourceVersion(
        source_id=source.id,
        status="PROPOSED",
        note=payload.note,
        submitted_by=submitted_by,
        file_path=payload.file_path,
    )
    db.add(version)
    await db.commit()
    await db.refresh(source)
    await db.refresh(version)

    await record_event_async(
        db,
        event_name="source_ingestion_event",
        emitting_service="source_library",
        subject_type="source",
        subject_id=source.id,
        actor_id=submitted_by,
        tenant_id=tenant_id,
        classification="INTERNAL",
        replay_relevance="REQUIRED",
        payload={
            "category": source.category,
            "title": source.title,
            "source_class": source.source_class,
            "version_id": version.id,
            "status": version.status,
        },
    )
    return {**source.__dict__, "latest_version": version}


async def approve_source_version(
    db: AsyncSession, approver_id: str, source_id: str, version_id: str, tenant_id: str = "GLOBAL_CONTROL"
) -> dict:
    result = await db.execute(
        select(SourceVersion).where(SourceVersion.id == version_id, SourceVersion.source_id == source_id)
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source version not found")

    if version.submitted_by == approver_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Maker-checker violation: the submitter of a source version cannot approve it.",
        )

    version.status = "APPROVED"
    version.approved_by = approver_id
    await db.commit()
    await db.refresh(version)

    source_result = await db.execute(select(Source).where(Source.id == source_id))
    source = source_result.scalar_one()

    await record_event_async(
        db,
        event_name="source_version_approved",
        emitting_service="source_library",
        subject_type="source",
        subject_id=source_id,
        actor_id=approver_id,
        correlation_id=source_id,
        tenant_id=tenant_id,
        classification="INTERNAL",
        replay_relevance="REQUIRED",
        payload={
            "version_id": version_id,
            "submitted_by": version.submitted_by,
            "approved_by": approver_id,
        },
    )
    return {**source.__dict__, "latest_version": version}
