from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
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
