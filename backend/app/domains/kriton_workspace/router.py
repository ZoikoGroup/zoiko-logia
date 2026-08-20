from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
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

_ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx"}
_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
_ATTACHMENT_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


@router.post("/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Persist, parse and index an attachment for grounded Ask Kriton turns."""
    name = file.filename or "attachment"
    suffix = name[name.rfind(".") :].lower() if "." in name else ""
    if suffix not in _ALLOWED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{suffix or 'unknown'}' — allowed: .pdf, .docx, .xlsx, .pptx")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="The uploaded file is empty")
    if len(content) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 20MB upload limit")

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
        payload={"filename": name, "size_bytes": len(content), "chunk_count": chunk_count, "status": document.status},
    )

    return {"document_id": document.id, "filename": name, "chunk_count": chunk_count, "status": document.status}


@router.get("/attachments", response_model=list[DocumentPublic])
async def get_attachments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DocumentPublic]:
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
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
        payload={},
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
