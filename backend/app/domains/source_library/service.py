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

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_UPLOAD_ROOT = _BACKEND_ROOT / "data" / "uploads"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_EMPTY_READ_ATTEMPTS = 3

# The two roots SourceVersion.file_path is ever written under — save_uploaded_file
# writes into _UPLOAD_ROOT (data/uploads/<tenant>/...), the ingest_*.py scripts
# write data/sources/<jurisdiction>/<filename> (see e.g.
# scripts/ingest_reference_sources.py's DATA_DIR). resolve_source_file_path
# below refuses to serve anything outside these two roots, even if a
# file_path value somehow contained "..' — defense in depth on top of the
# _SAFE_NAME_RE sanitization already applied at upload time.
_SERVABLE_ROOTS = (_UPLOAD_ROOT, _BACKEND_ROOT / "data" / "sources")


def resolve_source_url(source_id: str, file_path: str | None) -> str | None:
    """Single source of truth for turning a SourceVersion.file_path into
    something a client can actually open — used identically for chat
    citations (orchestration/service.py) and the admin Source Library/
    Source Licensing pages, so the two surfaces can never disagree about
    what a source's link is.

    A live reference-data source's file_path is already a real external URL
    (see e.g. app/domains/reference_data/service.py's to_rag_chunk functions,
    which set metadata["file_path"] = bundle.source_url) — passed through
    unchanged. An uploaded/ingested document's file_path is a local disk
    path relative to the backend root — turned into this API's own
    file-serving endpoint instead, since the client has no other way to
    reach it. None (no file at all — e.g. a PROPOSED source awaiting
    upload) stays None; callers must not fabricate a link for that case."""
    if not file_path:
        return None
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path
    return f"/sources/{source_id}/file"


async def get_source_file(db: AsyncSession, source_id: str, *, tenant_id: str) -> Path:
    """Full authorization + path-resolution chain for GET /sources/{id}/file
    — the single place that decides whether a given user may actually
    download a source's file, so the router stays a thin HTTP wrapper
    around real business logic rather than re-implementing this check
    itself. All failure modes return the same 404 (never 403) — this
    endpoint must not let an unauthorized caller distinguish "wrong tenant"
    from "not governed for viewing" from "doesn't exist" from "no file was
    ever uploaded," any of which would leak information about a source's
    existence/governance state to someone not entitled to see it.

    Same tenant boundary as get_source_by_id (shared-unless-private), plus
    two checks that function doesn't make: the latest version must be in
    an eligible display status (ACTIVE/APPROVED — the same bar
    orchestration/retrieve.py applies before a source can ever be cited),
    and it must actually have a local file_path (a live reference-data
    source's citation link never reaches this endpoint at all — see
    resolve_source_url's docstring — so reaching here with no file_path
    means either a data inconsistency or someone probing an id by hand)."""
    source = await get_source_by_id(db, source_id, tenant_id=tenant_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    latest_version = source.get("latest_version")
    if latest_version is None or latest_version.status not in _ELIGIBLE_STATUSES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    file_path = latest_version.file_path
    if not file_path or file_path.startswith("http://") or file_path.startswith("https://"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    candidate = (_BACKEND_ROOT / file_path).resolve()
    servable_roots = [root.resolve() for root in _SERVABLE_ROOTS]
    if not any(candidate == root or root in candidate.parents for root in servable_roots):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if not candidate.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return candidate


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


async def list_sources(
    db: AsyncSession, category: str | None = None, *, tenant_id: str | None = None
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
    # A remote transaction-pooler incident can occasionally return an empty
    # scalar result for a catalogue read without raising an exception. That
    # previously made an ACTIVE purpose-built source disappear for one request
    # and forced a spurious clarification (observed with FRED). Retry only the
    # anomalous empty result, with a strict bound; every non-empty result and a
    # genuinely empty catalogue preserve their normal semantics. Licensing is
    # still evaluated from the returned governed rows—nothing is synthesized.
    sources = []
    for _attempt in range(_EMPTY_READ_ATTEMPTS):
        result = await db.execute(query)
        sources = result.scalars().all()
        if sources:
            break

    if not sources:
        return []

    # Fetch all versions in one round trip and retain the newest per source.
    # The previous implementation called _latest_version once for every
    # source (47 sequential database queries in the current catalog), adding
    # roughly 6-10 seconds to every Kriton request against a remote database.
    version_query = (
        select(SourceVersion)
        .where(SourceVersion.source_id.in_([source.id for source in sources]))
        .order_by(SourceVersion.source_id, SourceVersion.created_at.desc())
    )
    versions = []
    for _attempt in range(_EMPTY_READ_ATTEMPTS):
        version_result = await db.execute(version_query)
        versions = version_result.scalars().all()
        if versions:
            break
    latest_by_source: dict[str, SourceVersion] = {}
    for version in versions:
        latest_by_source.setdefault(version.source_id, version)

    return [
        {**source.__dict__, "latest_version": latest_by_source.get(source.id)}
        for source in sources
    ]


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
