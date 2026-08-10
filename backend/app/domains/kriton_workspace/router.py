import math
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
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

_ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx"}
_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
_CHARS_PER_CHUNK = 4000


@router.post("/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Lightweight attachment intake for an Ask Kriton turn.

    This validates and sizes the upload and records it in the audit ledger —
    it deliberately does NOT claim the file has been parsed, embedded, or made
    retrievable, since no text-extraction/indexing pipeline exists yet.
    chunk_count is a real, deterministic function of the uploaded byte size
    (not a fabricated number), sized for a future ingestion pipeline to use.
    """
    name = file.filename or "attachment"
    suffix = name[name.rfind(".") :].lower() if "." in name else ""
    if suffix not in _ALLOWED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{suffix or 'unknown'}' — allowed: .pdf, .docx, .xlsx, .pptx")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="The uploaded file is empty")
    if len(content) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 20MB upload limit")

    document_id = f"att-{uuid.uuid4().hex[:16]}"
    chunk_count = math.ceil(len(content) / _CHARS_PER_CHUNK)

    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="kriton_workspace.attachment_uploaded",
        emitting_service="kriton_workspace",
        actor_id=current_user.id,
        subject_type="attachment",
        subject_id=document_id,
        payload={"filename": name, "size_bytes": len(content), "chunk_count": chunk_count},
    )

    return {"document_id": document_id, "filename": name, "chunk_count": chunk_count}


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
