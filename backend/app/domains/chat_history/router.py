from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.chat_history import service as chat_history_service
from app.domains.chat_history.schemas import ConversationDetail, ConversationRenameRequest, ConversationSummary
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user

router = APIRouter(prefix="/conversations", tags=["Chat History"])


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ConversationSummary]:
    rows = await chat_history_service.list_conversations(db, current_user.id)
    return [ConversationSummary.model_validate(r) for r in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationDetail:
    row = await chat_history_service.get_conversation_detail(db, current_user.id, conversation_id)
    return ConversationDetail.model_validate(row)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str,
    payload: ConversationRenameRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationSummary:
    row = await chat_history_service.rename_conversation(db, current_user.id, conversation_id, payload.title)
    return ConversationSummary.model_validate(row)


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    ok = await chat_history_service.delete_conversation(db, current_user.id, conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True}
