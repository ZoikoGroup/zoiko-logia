from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.documents import service as documents_service
from app.domains.documents.extract import SUPPORTED_EXTENSIONS
from app.domains.documents.models import STATUS_READY
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.kriton_workspace.schemas import (
    DraftCreateRequest,
    DraftPublic,
    DraftUpdateRequest,
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

router = APIRouter(prefix="/kriton-workspace", tags=["kriton_workspace"])

_ALLOWED_ATTACHMENT_EXTENSIONS = SUPPORTED_EXTENSIONS
_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB per file

# Lifetime cap per user. Not a licence tier - a backstop, so a stuck
# automated uploader cannot fill the tenant storage before anyone notices.
_MAX_DOCUMENTS_PER_USER = 200

# Uploads are ONE FILE PER REQUEST by deliberate design, even though the UI
# lets the user pick five at once (it sends them sequentially). Five 20MB
# files in a single request would be a 100MB body: ~300-500MB of peak RSS
# with the whole payload read into memory, plus 60-200s of extraction inside
# one request, which exceeds every sane proxy timeout and would force the
# work into a Celery worker. Sequential single-file requests get the same
# result for the user, keep each request inside its timeout, and need no
# broker at all.


@router.post("/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Ingest one attachment for an Ask Kriton turn: extract its text, chunk it
    and index it so the user can ask questions about it.

    chunk_count is now the real number of indexed chunks, not a function of the
    byte size. status is "ready" when the file is genuinely answerable and
    "failed" when it is not, with failure_reason saying why — a scanned PDF
    yields no text, and the uploader has to be told that rather than handed a
    green tick and answers that quietly ignore their file.
    """
    name = file.filename or "attachment"
    suffix = name[name.rfind(".") :].lower() if "." in name else ""
    if suffix not in _ALLOWED_ATTACHMENT_EXTENSIONS:
        allowed = ", ".join(sorted(_ALLOWED_ATTACHMENT_EXTENSIONS))
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type {suffix or 'unknown'} — allowed: {allowed}",
        )

    existing = await documents_service.count_documents(
        db, tenant_id=current_user.tenant_id, user_id=current_user.id
    )
    if existing >= _MAX_DOCUMENTS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=(
                f"You have reached the {_MAX_DOCUMENTS_PER_USER}-document limit. "
                "Delete a document before uploading another."
            ),
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="The uploaded file is empty")
    if len(content) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 20MB upload limit")

    result = await documents_service.ingest_document(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        filename=name,
        extension=suffix,
        data=content,
    )

    # Audited with the real outcome. A failed extraction is recorded as failed
    # rather than as an upload that happened to produce zero chunks.
    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name=(
            "kriton_workspace.attachment_indexed"
            if result.status == STATUS_READY
            else "kriton_workspace.attachment_rejected"
        ),
        emitting_service="kriton_workspace",
        actor_id=current_user.id,
        subject_type="attachment",
        subject_id=result.document_id,
        payload={
            "filename": name,
            "size_bytes": len(content),
            "status": result.status,
            "chunk_count": result.chunk_count,
            "char_count": result.char_count,
            "failure_reason": result.failure_reason,
        },
    )

    return {
        "document_id": result.document_id,
        "filename": result.filename,
        "status": result.status,
        "chunk_count": result.chunk_count,
        "char_count": result.char_count,
        "failure_reason": result.failure_reason,
    }


@router.get("/attachments")
async def list_attachments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """The caller own indexed documents, newest first."""
    rows = await documents_service.list_documents(
        db, tenant_id=current_user.tenant_id, user_id=current_user.id
    )
    return [
        {
            "document_id": d.id,
            "filename": d.filename,
            "status": d.status,
            "chunk_count": d.chunk_count,
            "size_bytes": d.size_bytes,
            "failure_reason": d.failure_reason,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]


@router.delete("/attachments/{document_id}")
async def delete_attachment(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    deleted = await documents_service.delete_document(
        db, document_id=document_id,
        tenant_id=current_user.tenant_id, user_id=current_user.id,
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
        payload={"document_id": document_id},
    )
    return {"deleted": True}


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
