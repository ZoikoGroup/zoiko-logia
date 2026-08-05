from fastapi import APIRouter, Depends, Header, HTTPException
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
    SavedVisualizationCreateRequest,
    SavedVisualizationPublic,
)
from app.domains.kriton_workspace.service import (
    create_draft,
    create_saved_answer,
    create_saved_visualization,
    delete_saved_answer,
    delete_saved_visualization,
    list_drafts,
    list_saved_answers,
    list_saved_visualizations,
    update_draft,
)
from app.orchestration.identifiers import check_idempotency, store_idempotency

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


@router.get("/saved-visualizations", response_model=list[SavedVisualizationPublic])
async def get_saved_visualizations(
    query_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SavedVisualizationPublic]:
    rows = await list_saved_visualizations(db, current_user.id, query_id)
    return [SavedVisualizationPublic.model_validate(r) for r in rows]


@router.post("/saved-visualizations", response_model=SavedVisualizationPublic)
async def post_saved_visualization(
    payload: SavedVisualizationCreateRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavedVisualizationPublic:
    # A repeated click resends the same client-generated key — return the
    # original save instead of creating a duplicate row. IdempotencyRecord's
    # uniqueness is (tenant_id, idempotency_key) only — it has no user_id
    # column, so two different users in the same tenant could theoretically
    # collide on the same raw key. Namespacing by user here avoids that
    # without changing the shared table's schema (it's also used by the
    # unrelated ask-kriton flow).
    scoped_key = f"{current_user.id}:{idempotency_key}"
    cached = await check_idempotency(db, scoped_key, current_user.tenant_id)
    if cached is not None:
        return SavedVisualizationPublic(**cached)
    row = await create_saved_visualization(db, current_user.tenant_id, current_user.id, payload)
    public = SavedVisualizationPublic.model_validate(row)
    await store_idempotency(db, scoped_key, current_user.tenant_id, public.model_dump(mode="json"))
    return public


@router.delete("/saved-visualizations/{visualization_id}")
async def delete_saved_visualization_endpoint(
    visualization_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    ok = await delete_saved_visualization(db, current_user.id, visualization_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Saved visualization not found")
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
