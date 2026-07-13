import re
import uuid
from datetime import date
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.source_library.models import Source, SourceVersion
from app.domains.source_library.schemas import SourceCreateRequest

_ELIGIBLE_STATUSES = ("ACTIVE", "APPROVED")

_UPLOAD_ROOT = Path(__file__).resolve().parents[3] / "data" / "uploads"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


async def save_uploaded_file(file: UploadFile, tenant_id: str) -> str:
    """Persist an uploaded source document to disk and return its relative
    path (recorded on the SourceVersion, mirroring how ingest_reference_sources.py
    links records back to the original file that was ingested)."""
    safe_name = _SAFE_NAME_RE.sub("_", file.filename or "upload")
    tenant_dir = _UPLOAD_ROOT / _SAFE_NAME_RE.sub("_", tenant_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex[:12]}_{safe_name}"
    dest = tenant_dir / stored_name
    contents = await file.read()
    dest.write_bytes(contents)

    backend_root = _UPLOAD_ROOT.parents[1]
    return str(dest.relative_to(backend_root))


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
        tenant_id=tenant_id,
        category=payload.category,
        title=payload.title,
        source_class=payload.source_class,
        jurisdiction_scope=payload.jurisdiction_scope,
        framework_scope=payload.framework_scope,
    )
    db.add(source)
    await db.flush()

    version = SourceVersion(
        tenant_id=tenant_id,
        source_id=source.id,
        status="PROPOSED",
        note=payload.note,
        submitted_by=submitted_by,
        file_path=payload.file_path,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
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


async def get_soonest_expiring(db: AsyncSession) -> dict | None:
    """The single approved/active source version with the nearest
    effective_to date, for the license-expiry countdown. Returns None if
    nothing has an expiry date on file — an honest "nothing expiring" state
    rather than fabricating one."""
    result = await db.execute(
        select(SourceVersion, Source)
        .join(Source, Source.id == SourceVersion.source_id)
        .where(
            SourceVersion.status.in_(_ELIGIBLE_STATUSES),
            SourceVersion.effective_to.is_not(None),
        )
        .order_by(SourceVersion.effective_to.asc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None

    version, source = row
    days_remaining = (version.effective_to - date.today()).days
    return {
        "source_id": source.id,
        "version_id": version.id,
        "title": source.title,
        "category": source.category,
        "jurisdiction_scope": source.jurisdiction_scope,
        "effective_to": version.effective_to,
        "days_remaining": days_remaining,
    }


async def get_jurisdiction_summary(db: AsyncSession) -> list[dict]:
    """Real rollout readiness computed from the actual source register — how
    many approved/pending sources exist per jurisdiction and category. No
    fabricated launch-gate checklist; readiness is derived from real counts."""
    result = await db.execute(select(Source, SourceVersion).join(SourceVersion, SourceVersion.source_id == Source.id))
    rows = result.all()

    by_jurisdiction: dict[str, dict[str, dict[str, int]]] = {}
    for source, version in rows:
        j = by_jurisdiction.setdefault(source.jurisdiction_scope, {})
        c = j.setdefault(source.category, {"approved": 0, "pending": 0})
        if version.status in _ELIGIBLE_STATUSES:
            c["approved"] += 1
        elif version.status in ("PROPOSED", "UNDER_REVIEW"):
            c["pending"] += 1

    summaries = []
    for jurisdiction, categories in by_jurisdiction.items():
        approved_total = sum(c["approved"] for c in categories.values())
        pending_total = sum(c["pending"] for c in categories.values())
        approved_categories = sum(1 for c in categories.values() if c["approved"] > 0)

        if approved_total >= 5 and approved_categories >= 2:
            readiness = "READY"
        elif approved_total > 0:
            readiness = "PARTIAL"
        else:
            readiness = "NOT_STARTED"

        summaries.append({
            "jurisdiction_scope": jurisdiction,
            "approved_count": approved_total,
            "pending_count": pending_total,
            "categories": [
                {"category": cat, "approved_count": c["approved"], "pending_count": c["pending"]}
                for cat, c in sorted(categories.items())
            ],
            "readiness": readiness,
        })

    return sorted(summaries, key=lambda s: s["approved_count"], reverse=True)


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
