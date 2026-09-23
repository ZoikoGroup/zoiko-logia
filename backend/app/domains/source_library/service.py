import asyncio
import hashlib
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.documents.extract import ExtractionError, extract
from app.domains.source_library.licensing import SOURCE_OPERATIONS, SourceUseContext, can_use
from app.domains.source_library.models import (
    Source, SourcePassage, SourceRelationship, SourceRight, SourceUsage, SourceVersion,
)
from app.domains.source_library.relationships import RELATIONSHIP_TYPES
from app.domains.source_library.schemas import SourceCreateRequest, SourceRightGrantRequest

_ELIGIBLE_STATUSES = ("ACTIVE", "APPROVED")

_UPLOAD_ROOT = Path(__file__).resolve().parents[3] / "data" / "uploads"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".txt", ".md"}
_MAX_SOURCE_BYTES = 25 * 1024 * 1024


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _file_from_relative_path(file_path: str) -> Path:
    backend_root = _UPLOAD_ROOT.parents[1].resolve()
    candidate = (backend_root / file_path).resolve()
    if backend_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Invalid source file path")
    return candidate


def _validate_url(source_url: str | None) -> None:
    if not source_url:
        return
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="Source URL must be an absolute HTTP(S) URL")


async def save_uploaded_file(file: UploadFile, tenant_id: str) -> str:
    """Persist an uploaded source document to disk and return its relative
    path (recorded on the SourceVersion, mirroring how ingest_reference_sources.py
    links records back to the original file that was ingested)."""
    safe_name = _SAFE_NAME_RE.sub("_", file.filename or "upload")
    extension = Path(safe_name).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported source file type: {extension or 'none'}")
    tenant_dir = _UPLOAD_ROOT / _SAFE_NAME_RE.sub("_", tenant_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex[:12]}_{safe_name}"
    dest = tenant_dir / stored_name
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=422, detail="The source file is empty")
    if len(contents) > _MAX_SOURCE_BYTES:
        raise HTTPException(status_code=413, detail="Source file exceeds the 25MB limit")
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


async def list_sources(
    db: AsyncSession, category: str | None = None, *, tenant_id: str | None = None,
    operation: str | None = None, jurisdiction: str = "", framework: str = "",
    effective_date: date | None = None,
) -> list[dict]:
    """tenant_id, when given, enforces the same tenant-private boundary
    massarius/license_gate.py's Checkpoint A applies downstream: non-private
    sources (is_tenant_private=False) are shared across all tenants by
    design (e.g. regulatory standards), so only rows actually marked private
    are restricted to their owning tenant. This mirrors that logic at the
    data-access layer as well, not just app-layer, per ZL-ENG-03 §7.1 —
    filtering strictly on tenant_id equality here would incorrectly hide
    shared sources from every tenant that doesn't literally own the row."""
    query = select(Source)
    if category:
        query = query.where(Source.category == category)
    if tenant_id is not None:
        query = query.where((Source.is_tenant_private.is_(False)) | (Source.tenant_id == tenant_id))
    result = await db.execute(query)
    sources = result.scalars().all()

    combined = []
    for source in sources:
        latest = await _latest_version(db, source.id)
        if latest is None:
            continue
        if operation is not None:
            decision = await can_use(
                db, latest.id,
                SourceUseContext(
                    tenant_id=tenant_id or source.tenant_id,
                    jurisdiction=jurisdiction,
                    framework=framework,
                    effective_date=effective_date,
                ),
                operation,
            )
            if not decision.allowed:
                continue
        combined.append({**source.__dict__, "latest_version": latest})
    return combined


async def get_source_by_id(
    db: AsyncSession, source_id: str, *, tenant_id: str | None = None
) -> dict | None:
    """Single-row counterpart to list_sources(), for callers (e.g. vector
    retrieval) that only have a source_id from chunk metadata and need to
    verify it against a real, tenant-visible governance record — rather than
    trusting whatever status/jurisdiction the chunk's own metadata claims.
    Applies the same shared-unless-private tenant boundary as list_sources().
    Returns None if the id doesn't exist or isn't visible to this tenant."""
    query = select(Source).where(Source.id == source_id)
    if tenant_id is not None:
        query = query.where((Source.is_tenant_private.is_(False)) | (Source.tenant_id == tenant_id))
    result = await db.execute(query)
    source = result.scalar_one_or_none()
    if source is None:
        return None
    latest = await _latest_version(db, source.id)
    return {**source.__dict__, "latest_version": latest}


async def create_source(
    db: AsyncSession, submitted_by: str, payload: SourceCreateRequest, tenant_id: str = "GLOBAL_CONTROL"
) -> dict:
    _validate_url(payload.source_url)
    unknown_operations = set(payload.rights) - SOURCE_OPERATIONS
    if unknown_operations:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown source-right operations: {', '.join(sorted(unknown_operations))}",
        )
    if payload.file_path:
        required_storage_rights = ("ingestion", "indexing", "retention")
        missing_storage_rights = [op for op in required_storage_rights if payload.rights.get(op) is not True]
        if missing_storage_rights:
            raise HTTPException(
                status_code=409,
                detail=(
                    "File registration requires explicit allow rights for: "
                    + ", ".join(missing_storage_rights)
                ),
            )
    file_bytes = b""
    segments = []
    content_hash = payload.content_hash.strip().lower()
    if payload.file_path:
        stored_file = _file_from_relative_path(payload.file_path)
        file_bytes = stored_file.read_bytes()
        content_hash = hashlib.sha256(file_bytes).hexdigest()
        try:
            segments = await asyncio.to_thread(extract, file_bytes, stored_file.suffix.lower())
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not content_hash and payload.source_url:
        # URL registrations do not claim a content hash until retrieved bytes
        # are supplied. They remain unapprovable and fail closed meanwhile.
        content_hash = ""
    if content_hash:
        duplicate = await db.execute(
            select(SourceVersion.id).where(
                SourceVersion.tenant_id == tenant_id,
                SourceVersion.content_hash == content_hash,
            ).limit(1)
        )
        if duplicate.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="This exact source content is already registered")

    source = Source(
        tenant_id=tenant_id,
        category=payload.category,
        title=payload.title,
        publisher=payload.publisher,
        owner=payload.owner,
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
        source_url=payload.source_url,
        content_hash=content_hash,
        published_at=payload.published_at,
        retrieved_at=payload.retrieved_at or _utcnow(),
        original_language=payload.original_language,
        translation_of_version_id=payload.translation_of_version_id,
        quality_state="EXTRACTED" if segments else "UNREVIEWED",
    )
    db.add(version)
    await db.flush()

    for operation in sorted(SOURCE_OPERATIONS):
        allowed = payload.rights.get(operation)
        db.add(SourceRight(
            tenant_id=tenant_id,
            source_version_id=version.id,
            operation=operation,
            decision="allow" if allowed is True else "deny",
            rights_version=1,
            reason_code="EXPLICITLY_GRANTED" if allowed is True else "RIGHT_UNKNOWN",
            terms_reference=payload.terms_reference,
            granted_by=submitted_by,
        ))

    # Extraction is stored only when both ingestion and indexing were
    # explicitly granted. Bytes may be retained for review, but denied content
    # never enters the passage index.
    if payload.rights.get("ingestion") is True and payload.rights.get("indexing") is True:
        for sequence, segment in enumerate(segments, start=1):
            content = segment.text.strip()
            db.add(SourcePassage(
                tenant_id=tenant_id,
                source_version_id=version.id,
                locator=segment.locator,
                sequence=sequence,
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                language=payload.original_language,
                is_translation=payload.translation_of_version_id is not None,
            ))

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

    if not version.content_hash:
        raise HTTPException(status_code=409, detail="A version cannot be approved without a content hash")

    passage_result = await db.execute(
        select(func.count(SourcePassage.id)).where(SourcePassage.source_version_id == version.id)
    )
    if (passage_result.scalar_one() or 0) == 0:
        raise HTTPException(status_code=409, detail="A version cannot be approved without indexed passages")

    required_for_release = ("retrieval", "model_transmission", "display")
    # can_use requires approval itself, so inspect explicit rights here while
    # the version is still PROPOSED.
    rights_result = await db.execute(
        select(SourceRight).where(
            SourceRight.source_version_id == version.id,
            SourceRight.operation.in_(required_for_release),
        ).order_by(SourceRight.rights_version.desc())
    )
    rights = {}
    for right in rights_result.scalars().all():
        rights.setdefault(right.operation, right)
    now = _utcnow()

    def right_is_current(right: SourceRight | None) -> bool:
        if right is None or right.decision != "allow":
            return False
        valid_from = right.valid_from
        valid_to = right.valid_to
        if valid_from and valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        if valid_to and valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=timezone.utc)
        return not ((valid_from and now < valid_from) or (valid_to and now > valid_to))

    missing = [op for op in required_for_release if not right_is_current(rights.get(op))]
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"Approval requires explicit allow rights for: {', '.join(missing)}",
        )

    version.status = "APPROVED"
    version.quality_state = "APPROVED"
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


async def grant_source_right(
    db: AsyncSession, *, version_id: str, tenant_id: str, actor_id: str,
    grant: SourceRightGrantRequest,
) -> SourceRight:
    version_result = await db.execute(
        select(SourceVersion).where(
            SourceVersion.id == version_id,
            SourceVersion.tenant_id == tenant_id,
        )
    )
    if version_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Source version not found")
    latest_result = await db.execute(
        select(func.max(SourceRight.rights_version)).where(
            SourceRight.source_version_id == version_id,
            SourceRight.operation == grant.operation,
        )
    )
    next_version = (latest_result.scalar_one() or 0) + 1
    right = SourceRight(
        tenant_id=tenant_id,
        source_version_id=version_id,
        operation=grant.operation,
        decision=grant.decision,
        rights_version=next_version,
        reason_code=grant.reason_code,
        terms_reference=grant.terms_reference,
        valid_from=grant.valid_from,
        valid_to=grant.valid_to,
        granted_by=actor_id,
    )
    db.add(right)
    await db.commit()
    await db.refresh(right)
    return right


async def list_passages(db: AsyncSession, *, version_id: str, tenant_id: str) -> list[SourcePassage]:
    result = await db.execute(
        select(SourcePassage)
        .where(SourcePassage.source_version_id == version_id, SourcePassage.tenant_id == tenant_id)
        .order_by(SourcePassage.sequence)
    )
    return list(result.scalars().all())


async def add_relationship(
    db: AsyncSession, *, from_version_id: str, to_version_id: str,
    relationship_type: str, tenant_id: str, actor_id: str,
) -> SourceRelationship:
    if relationship_type not in RELATIONSHIP_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported source relationship")
    versions = await db.execute(
        select(SourceVersion).where(
            SourceVersion.id.in_([from_version_id, to_version_id]),
            SourceVersion.tenant_id == tenant_id,
        )
    )
    found = {version.id: version for version in versions.scalars().all()}
    if len(found) != 2:
        raise HTTPException(status_code=404, detail="Both source versions must exist in this tenant")
    relationship = SourceRelationship(
        tenant_id=tenant_id,
        from_version_id=from_version_id,
        to_version_id=to_version_id,
        relationship_type=relationship_type,
        created_by=actor_id,
    )
    db.add(relationship)
    if relationship_type == "supersedes":
        found[to_version_id].superseded_by_version_id = from_version_id
        found[to_version_id].status = "SUPERSEDED"
    await db.commit()
    await db.refresh(relationship)
    return relationship


async def revoke_source_version(
    db: AsyncSession, *, version_id: str, tenant_id: str, reason: str,
) -> SourceVersion:
    result = await db.execute(
        select(SourceVersion).where(
            SourceVersion.id == version_id,
            SourceVersion.tenant_id == tenant_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Source version not found")
    if not reason.strip():
        raise HTTPException(status_code=422, detail="A revocation reason is required")
    version.status = "WITHDRAWN"
    version.revoked_at = _utcnow()
    version.revocation_reason = reason.strip()
    await db.commit()
    await db.refresh(version)
    return version


async def find_impacted_usages(
    db: AsyncSession, *, version_id: str, tenant_id: str,
) -> list[SourceUsage]:
    result = await db.execute(
        select(SourceUsage)
        .where(SourceUsage.source_version_id == version_id, SourceUsage.tenant_id == tenant_id)
        .order_by(SourceUsage.recorded_at.desc())
    )
    return list(result.scalars().all())


async def record_source_usages(
    db: AsyncSession, *, sources, tenant_id: str, artifact_type: str,
    artifact_id: str, operation: str,
) -> None:
    """Persist an idempotent reverse reference for later revocation impact."""
    for source in sources:
        version_id = getattr(source, "version_id", "")
        if not version_id:
            continue
        existing = await db.execute(
            select(SourceUsage.id).where(
                SourceUsage.source_version_id == version_id,
                SourceUsage.artifact_type == artifact_type,
                SourceUsage.artifact_id == artifact_id,
                SourceUsage.operation == operation,
            )
        )
        if existing.scalar_one_or_none() is None:
            db.add(SourceUsage(
                tenant_id=tenant_id,
                source_version_id=version_id,
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                operation=operation,
            ))
    await db.commit()


async def expire_source_versions(db: AsyncSession, *, today: date | None = None) -> int:
    cutoff = today or date.today()
    result = await db.execute(
        select(SourceVersion).where(
            SourceVersion.status.in_(_ELIGIBLE_STATUSES),
            SourceVersion.effective_to.is_not(None),
            SourceVersion.effective_to < cutoff,
        )
    )
    versions = list(result.scalars().all())
    for version in versions:
        version.status = "EXPIRED"
    await db.commit()
    return len(versions)
