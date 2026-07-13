from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.domains.kriton_workspace.schemas import (
    DraftCreateRequest,
    DraftUpdateRequest,
    SavedAnswerCreateRequest,
)


async def list_saved_answers(db: AsyncSession, user_id: str) -> list[SavedAnswer]:
    result = await db.execute(
        select(SavedAnswer).where(SavedAnswer.user_id == user_id).order_by(SavedAnswer.created_at.desc())
    )
    return list(result.scalars().all())


async def create_saved_answer(
    db: AsyncSession, tenant_id: str, user_id: str, payload: SavedAnswerCreateRequest
) -> SavedAnswer:
    row = SavedAnswer(
        tenant_id=tenant_id,
        user_id=user_id,
        query_id=payload.query_id,
        query_text=payload.query_text,
        answer_text=payload.answer_text,
        risk_level=payload.risk_level,
        tags=payload.tags,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_saved_answer(db: AsyncSession, user_id: str, answer_id: str) -> bool:
    result = await db.execute(
        select(SavedAnswer).where(SavedAnswer.id == answer_id, SavedAnswer.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def list_drafts(db: AsyncSession, user_id: str) -> list[Draft]:
    result = await db.execute(select(Draft).where(Draft.user_id == user_id).order_by(Draft.updated_at.desc()))
    return list(result.scalars().all())


async def create_draft(db: AsyncSession, tenant_id: str, user_id: str, payload: DraftCreateRequest) -> Draft:
    row = Draft(
        tenant_id=tenant_id,
        user_id=user_id,
        title=payload.title,
        content=payload.content,
        saved_answer_id=payload.saved_answer_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_draft(db: AsyncSession, user_id: str, draft_id: str, payload: DraftUpdateRequest) -> Draft:
    result = await db.execute(select(Draft).where(Draft.id == draft_id, Draft.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    if payload.title is not None:
        row.title = payload.title
    if payload.content is not None:
        row.content = payload.content
    if payload.status is not None:
        row.status = payload.status

    await db.commit()
    await db.refresh(row)
    return row
