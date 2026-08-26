from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user, require_admin
from app.domains.learning_system.models import LearningCandidate, MemoryItem, SourceUpdateReview, WorkflowDefinition
from app.domains.learning_system.schemas import (
    CandidateOut, CandidateReview, FeedbackCreate, FeedbackOut, MemoryCreate, MemoryOut,
    SourceUpdateCreate, SourceUpdateOut, SourceUpdateReviewIn, WorkflowCreate, WorkflowOut,
)
from app.domains.learning_system.service import review_candidate, review_source_update, submit_feedback

router = APIRouter(prefix="/learning-system", tags=["governed-learning"])


@router.post("/feedback", response_model=FeedbackOut)
async def create_feedback(payload: FeedbackCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item, candidate_id, memory_id = await submit_feedback(db, payload, user)
    return FeedbackOut.model_validate(item).model_copy(update={"learning_candidate_id": candidate_id, "memory_id": memory_id})


@router.get("/memories", response_model=list[MemoryOut])
async def memories(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = await db.execute(select(MemoryItem).where(MemoryItem.tenant_id == user.tenant_id, MemoryItem.user_id == user.id).order_by(MemoryItem.updated_at.desc()))
    return list(rows.scalars())


@router.post("/memories", response_model=MemoryOut)
async def create_memory(payload: MemoryCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = MemoryItem(tenant_id=user.tenant_id, user_id=user.id, key=payload.key, value=payload.value, confirmed=payload.confirmed)
    db.add(item); await db.commit(); await db.refresh(item); return item


@router.post("/memories/{memory_id}/confirm", response_model=MemoryOut)
async def confirm_memory(memory_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = await db.execute(select(MemoryItem).where(MemoryItem.id == memory_id, MemoryItem.tenant_id == user.tenant_id, MemoryItem.user_id == user.id))
    item = row.scalar_one_or_none()
    if not item: raise HTTPException(404, "Memory not found")
    item.confirmed = True; await db.commit(); await db.refresh(item); return item


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = await db.execute(select(MemoryItem).where(MemoryItem.id == memory_id, MemoryItem.tenant_id == user.tenant_id, MemoryItem.user_id == user.id))
    item = row.scalar_one_or_none()
    if not item: raise HTTPException(404, "Memory not found")
    await db.delete(item); await db.commit(); return Response(status_code=204)


@router.get("/candidates", response_model=list[CandidateOut])
async def candidates(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    rows = await db.execute(select(LearningCandidate).where(LearningCandidate.tenant_id == admin.tenant_id).order_by(LearningCandidate.created_at.desc()))
    return list(rows.scalars())


@router.post("/candidates/{candidate_id}/review", response_model=CandidateOut)
async def candidate_review(candidate_id: str, payload: CandidateReview, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    row = await db.execute(select(LearningCandidate).where(LearningCandidate.id == candidate_id, LearningCandidate.tenant_id == admin.tenant_id))
    item = row.scalar_one_or_none()
    if not item: raise HTTPException(404, "Learning candidate not found")
    return await review_candidate(db, item, payload.decision, payload.note, admin.id, payload.promote_to_benchmark)


@router.get("/workflows", response_model=list[WorkflowOut])
async def workflows(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    rows = await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.tenant_id.in_([admin.tenant_id, "GLOBAL_CONTROL"])).order_by(WorkflowDefinition.created_at.desc()))
    return list(rows.scalars())


@router.post("/workflows", response_model=WorkflowOut)
async def create_workflow(payload: WorkflowCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    item = WorkflowDefinition(tenant_id=admin.tenant_id, approved_by=admin.id if payload.active else None, **payload.model_dump())
    db.add(item); await db.commit(); await db.refresh(item); return item


@router.post("/source-updates", response_model=SourceUpdateOut)
async def create_source_update(payload: SourceUpdateCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    item = SourceUpdateReview(tenant_id=admin.tenant_id, submitted_by=admin.id, **payload.model_dump())
    db.add(item); await db.commit(); await db.refresh(item); return item


@router.get("/source-updates", response_model=list[SourceUpdateOut])
async def source_updates(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    rows = await db.execute(select(SourceUpdateReview).where(SourceUpdateReview.tenant_id == admin.tenant_id).order_by(SourceUpdateReview.created_at.desc()))
    return list(rows.scalars())


@router.post("/source-updates/{item_id}/review", response_model=SourceUpdateOut)
async def source_update_review(item_id: str, payload: SourceUpdateReviewIn, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    row = await db.execute(select(SourceUpdateReview).where(SourceUpdateReview.id == item_id, SourceUpdateReview.tenant_id == admin.tenant_id))
    item = row.scalar_one_or_none()
    if not item: raise HTTPException(404, "Source update not found")
    return await review_source_update(db, item, payload.decision, payload.note, admin.id)
