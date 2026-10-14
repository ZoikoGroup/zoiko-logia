from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.identity.authorization import DOCUMENT_READ, DOCUMENT_WRITE, authorize
from app.domains.kriton_workspace.schemas import (
    DraftCreateRequest,
    DraftPublic,
    DraftUpdateRequest,
    DocumentPublic,
    SavedAnswerCreateRequest,
    SavedAnswerPublic,
)
from app.domains.kriton_workspace.service import (
    create_draft,
    create_saved_answer,
    delete_saved_answer,
    list_drafts,
    list_saved_answers,
    update_draft,
)
from app.domains.kriton_workspace.documents import (
    create_document_upload,
    delete_document,
    get_document,
    ingest_document,
    list_documents,
)
from app.core.config import get_settings
from app.domains.kriton_workspace.artifacts import artifact_absolute_path, artifact_bytes, get_generated_artifact

router = APIRouter(prefix="/kriton-workspace", tags=["kriton_workspace"])

_ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".csv"}
_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
_ATTACHMENT_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv",
}


@router.post("/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    engagement_id: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Persist, parse and index an attachment for grounded Ask Kriton turns."""
    name = file.filename or "attachment"
    suffix = name[name.rfind(".") :].lower() if "." in name else ""
    if suffix not in _ALLOWED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{suffix or 'unknown'}' — allowed: .pdf, .docx, .xlsx, .pptx, .csv")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="The uploaded file is empty")
    if len(content) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 20MB upload limit")

    if engagement_id:
        decision = await authorize(
            db, actor_id=current_user.id, tenant_id=current_user.tenant_id,
            engagement_id=engagement_id, operation=DOCUMENT_WRITE,
        )
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason_code)

    if get_settings().ASYNC_DOCUMENT_INGESTION:
        document = await create_document_upload(
            db, filename=name, mime_type=_ATTACHMENT_MIME_TYPES[suffix],
            content=content, tenant_id=current_user.tenant_id, user_id=current_user.id,
        )
        from app.jobs.ingestion_jobs import enqueue_document_ingestion
        enqueue_document_ingestion(document.id)
        chunk_count = 0
    else:
        document, chunk_count = await ingest_document(
            db,
            filename=name,
            mime_type=_ATTACHMENT_MIME_TYPES[suffix],
            content=content,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
    if document.status == "FAILED":
        raise HTTPException(status_code=422, detail=f"The document could not be processed: {document.processing_error}")

    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="kriton_workspace.attachment_uploaded",
        emitting_service="kriton_workspace",
        actor_id=current_user.id,
        subject_type="attachment",
        subject_id=document.id,
        payload={
            "filename": name,
            "size_bytes": len(content),
            "chunk_count": chunk_count,
            "status": document.status,
            "engagement_id": engagement_id,
        },
    )

    return {"document_id": document.id, "filename": name, "chunk_count": chunk_count, "status": document.status}


@router.get("/attachments", response_model=list[DocumentPublic])
async def get_attachments(
    engagement_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DocumentPublic]:
    """The caller own indexed documents, newest first."""
    if engagement_id:
        decision = await authorize(
            db, actor_id=current_user.id, tenant_id=current_user.tenant_id,
            engagement_id=engagement_id, operation=DOCUMENT_READ,
        )
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason_code)
    rows = await list_documents(db, tenant_id=current_user.tenant_id, user_id=current_user.id)
    return [
        DocumentPublic(
            id=document.id,
            filename=document.filename,
            mime_type=document.mime_type,
            status=document.status,
            processing_error=document.processing_error,
            chunk_count=chunk_count,
            created_at=document.created_at,
            expires_at=document.expires_at,
        )
        for document, chunk_count in rows
    ]


@router.get("/attachments/{document_id}", response_model=DocumentPublic)
async def get_attachment(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentPublic:
    row = await get_document(
        db, document_id=document_id,
        tenant_id=current_user.tenant_id, user_id=current_user.id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    document, chunk_count = row
    return DocumentPublic(
        id=document.id, filename=document.filename, mime_type=document.mime_type,
        status=document.status, processing_error=document.processing_error,
        chunk_count=chunk_count, created_at=document.created_at,
        expires_at=document.expires_at,
    )


@router.delete("/attachments/{document_id}")
async def delete_attachment(
    document_id: str,
    engagement_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if engagement_id:
        decision = await authorize(
            db, tenant_id=current_user.tenant_id, actor_id=current_user.id,
            engagement_id=engagement_id, operation=DOCUMENT_WRITE,
        )
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason_code)
    deleted = await delete_document(
        db, document_id=document_id, tenant_id=current_user.tenant_id, user_id=current_user.id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="kriton_workspace.attachment_deleted",
        emitting_service="kriton_workspace",
        actor_id=current_user.id,
        subject_type="attachment",
        subject_id=document_id,
        payload={"document_id": document_id, "engagement_id": engagement_id},
    )
    return {"deleted": True}


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = await get_generated_artifact(
        db, artifact_id=artifact_id, tenant_id=current_user.tenant_id, user_id=current_user.id
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Generated document not found")
    if artifact.storage_provider == "supabase":
        content = await artifact_bytes(artifact)
        return Response(
            content=content,
            media_type=artifact.mime_type,
            headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
        )
    path = artifact_absolute_path(artifact)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Generated document file is unavailable")
    return FileResponse(path, media_type=artifact.mime_type, filename=artifact.filename)


@router.get("/saved-answers", response_model=list[SavedAnswerPublic])
async def get_saved_answers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SavedAnswerPublic]:
    rows = await list_saved_answers(db, current_user.id)
    return [SavedAnswerPublic.model_validate(r) for r in rows]


@router.post("/saved-answers", response_model=SavedAnswerPublic)
async def post_saved_answer(
    payload: SavedAnswerCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavedAnswerPublic:
    row = await create_saved_answer(db, current_user.tenant_id, current_user.id, payload)
    return SavedAnswerPublic.model_validate(row)


@router.delete("/saved-answers/{answer_id}")
async def delete_saved_answer_endpoint(
    answer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    ok = await delete_saved_answer(db, current_user.id, answer_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Saved answer not found")
    return {"deleted": True}


@router.get("/drafts", response_model=list[DraftPublic])
async def get_drafts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DraftPublic]:
    rows = await list_drafts(db, current_user.id)
    return [DraftPublic.model_validate(r) for r in rows]


@router.post("/drafts", response_model=DraftPublic)
async def post_draft(
    payload: DraftCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DraftPublic:
    row = await create_draft(db, current_user.tenant_id, current_user.id, payload)
    return DraftPublic.model_validate(row)


@router.patch("/drafts/{draft_id}", response_model=DraftPublic)
async def patch_draft(
    draft_id: str,
    payload: DraftUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DraftPublic:
    row = await update_draft(db, current_user.id, draft_id, payload)
    return DraftPublic.model_validate(row)


# Drafts & Reports: delete, sources and export (see draft_tools.py). Imported
# here so the draft additions stay in one block.
@router.delete("/drafts/{draft_id}", status_code=204)
async def remove_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    from app.domains.kriton_workspace.draft_tools import delete_draft

    row = await delete_draft(db, current_user.tenant_id, current_user.id, draft_id)
    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="kriton_workspace.draft_deleted",
        emitting_service="kriton_workspace",
        actor_id=current_user.id,
        subject_type="draft",
        subject_id=draft_id,
        payload={"title": row.title, "status": row.status},
    )
    return Response(status_code=204)


@router.get("/drafts/{draft_id}/sources")
async def get_draft_sources(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    from app.domains.kriton_workspace.draft_tools import draft_sources

    return await draft_sources(db, current_user.tenant_id, current_user.id, draft_id)


@router.get("/drafts/{draft_id}/export")
async def export_draft_file(
    draft_id: str,
    format: str = "docx",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    from app.domains.kriton_workspace.draft_tools import export_draft

    content, filename, mime_type, title = await export_draft(
        db, current_user.tenant_id, current_user.id, draft_id, format.lower(),
    )
    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="kriton_workspace.draft_exported",
        emitting_service="kriton_workspace",
        actor_id=current_user.id,
        subject_type="draft",
        subject_id=draft_id,
        payload={"title": title, "format": format.lower()},
    )
    return Response(
        content=content, media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Reports & Insights: tenant usage aggregates (see insights.py).
@router.get("/insights")
async def get_insights(
    window_days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from app.domains.kriton_workspace.insights import build_insights

    return await build_insights(db, current_user, window_days)


# Evidence Packs: an on-demand ZIP for a saved answer or a draft (see evidence_pack.py).
@router.get("/evidence-packs/{kind}/{item_id}")
async def download_evidence_pack(
    kind: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    from app.domains.kriton_workspace.evidence_pack import build_evidence_pack

    content, filename, manifest = await build_evidence_pack(db, current_user, kind, item_id)
    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="kriton_workspace.evidence_pack_exported",
        emitting_service="kriton_workspace",
        actor_id=current_user.id,
        subject_type=kind,
        subject_id=item_id,
        payload={"query_id": manifest["query_id"], "counts": manifest["counts"],
                 "files": {name: f["sha256"] for name, f in manifest["files"].items()}},
    )
    return Response(
        content=content, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Compliance Calendar: general statutory deadlines from rules (see compliance_calendar.py).
@router.get("/compliance-calendar")
async def get_compliance_calendar(
    days: int = 90,
    jurisdiction: str = "",
    current_user: User = Depends(get_current_user),
) -> dict:
    from datetime import date

    from app.domains.kriton_workspace.compliance_calendar import upcoming_deadlines

    return upcoming_deadlines(date.today(), days, jurisdiction)


# Workpapers: client job files with a maker-checker sign-off (see workpapers.py).
from pydantic import BaseModel as _WorkpaperBody  # noqa: E402 - kept with the workpaper block

from app.domains.kriton_workspace import workpaper_models  # noqa: E402,F401 - registers the tables at startup


class WorkpaperCreateRequest(_WorkpaperBody):
    title: str
    period: str = ""
    engagement_id: str | None = None
    reviewer_id: str | None = None


class WorkpaperUpdateRequest(_WorkpaperBody):
    title: str | None = None
    period: str | None = None
    notes: str | None = None
    engagement_id: str | None = None
    reviewer_id: str | None = None


class WorkpaperReviewRequest(_WorkpaperBody):
    decision: str  # sign_off | return
    note: str = ""


class WorkpaperItemRequest(_WorkpaperBody):
    kind: str  # saved_answer | draft | document
    item_id: str
    note: str = ""


async def _audit_workpaper(db: AsyncSession, user: User, event: str, workpaper_id: str, payload: dict) -> None:
    await record_event_async(
        db, tenant_id=user.tenant_id, event_name=f"workpaper.{event}", emitting_service="kriton_workspace",
        actor_id=user.id, subject_type="workpaper", subject_id=workpaper_id, payload=payload,
    )


@router.get("/workpapers")
async def get_workpapers(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    from app.domains.kriton_workspace import workpapers

    return await workpapers.list_workpapers(db, current_user)


@router.get("/workpapers/reviewers")
async def get_workpaper_reviewers(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    from app.domains.kriton_workspace import workpapers

    return await workpapers.reviewers(db, current_user)


@router.post("/workpapers")
async def post_workpaper(payload: WorkpaperCreateRequest, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)) -> dict:
    from app.domains.kriton_workspace import workpapers

    wp = await workpapers.create_workpaper(db, current_user, payload.title, payload.period,
                                           payload.engagement_id, payload.reviewer_id)
    await _audit_workpaper(db, current_user, "created", wp.id, {"title": wp.title, "engagement_id": wp.engagement_id})
    return await workpapers.summary(db, wp, current_user, with_items=True)


@router.get("/workpapers/{workpaper_id}")
async def get_workpaper(workpaper_id: str, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user)) -> dict:
    from app.domains.kriton_workspace import workpapers

    return await workpapers.summary(db, await workpapers._get(db, current_user, workpaper_id), current_user, with_items=True)


@router.patch("/workpapers/{workpaper_id}")
async def patch_workpaper(workpaper_id: str, payload: WorkpaperUpdateRequest, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)) -> dict:
    from app.domains.kriton_workspace import workpapers

    changes = payload.model_dump(exclude_unset=True)
    wp = await workpapers.update_workpaper(db, current_user, workpaper_id, changes)
    await _audit_workpaper(db, current_user, "updated", wp.id, {"fields": sorted(changes)})
    return await workpapers.summary(db, wp, current_user, with_items=True)


@router.post("/workpapers/{workpaper_id}/submit")
async def submit_workpaper(workpaper_id: str, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)) -> dict:
    from app.domains.kriton_workspace import workpapers

    wp = await workpapers.submit(db, current_user, workpaper_id)
    await _audit_workpaper(db, current_user, "submitted", wp.id, {"reviewer_id": wp.reviewer_id})
    return await workpapers.summary(db, wp, current_user, with_items=True)


@router.post("/workpapers/{workpaper_id}/review")
async def review_workpaper(workpaper_id: str, payload: WorkpaperReviewRequest, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)) -> dict:
    from app.domains.kriton_workspace import workpapers

    wp = await workpapers.review(db, current_user, workpaper_id, payload.decision, payload.note)
    await _audit_workpaper(db, current_user, "signed_off" if wp.status == "signed_off" else "returned",
                           wp.id, {"note": wp.review_note})
    return await workpapers.summary(db, wp, current_user, with_items=True)


@router.post("/workpapers/{workpaper_id}/items")
async def add_workpaper_item(workpaper_id: str, payload: WorkpaperItemRequest, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_user)) -> dict:
    from app.domains.kriton_workspace import workpapers

    row = await workpapers.add_item(db, current_user, workpaper_id, payload.kind, payload.item_id, payload.note)
    await _audit_workpaper(db, current_user, "item_added", workpaper_id, {"kind": row.kind, "item_id": row.item_id})
    return await workpapers.summary(db, await workpapers._get(db, current_user, workpaper_id), current_user, with_items=True)


@router.delete("/workpapers/{workpaper_id}/items/{row_id}")
async def remove_workpaper_item(workpaper_id: str, row_id: str, db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(get_current_user)) -> dict:
    from app.domains.kriton_workspace import workpapers

    row = await workpapers.remove_item(db, current_user, workpaper_id, row_id)
    await _audit_workpaper(db, current_user, "item_removed", workpaper_id, {"kind": row.kind, "item_id": row.item_id})
    return await workpapers.summary(db, await workpapers._get(db, current_user, workpaper_id), current_user, with_items=True)


@router.get("/workpapers/{workpaper_id}/evidence-pack")
async def download_workpaper_pack(workpaper_id: str, db: AsyncSession = Depends(get_db),
                                  current_user: User = Depends(get_current_user)) -> Response:
    from app.domains.kriton_workspace import workpapers

    content, filename, manifest = await workpapers.workpaper_pack(db, current_user, workpaper_id)
    await _audit_workpaper(db, current_user, "pack_exported", workpaper_id,
                           {"evidence_packs": len(manifest["evidencePacks"])})
    return Response(content=content, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
