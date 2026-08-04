from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.chat_history.models import ChatMessage, Conversation

_TITLE_MAX_LEN = 60


def _auto_title(first_message: str) -> str:
    """ChatGPT-style auto title: first message, trimmed to one line and
    capped in length. No LLM call — cheap, deterministic, and good enough
    for a sidebar label; nothing stops swapping in an LLM-generated title
    later without touching callers, since this is the only place it's built."""
    single_line = " ".join(first_message.split())
    if len(single_line) <= _TITLE_MAX_LEN:
        return single_line or "New conversation"
    return single_line[:_TITLE_MAX_LEN].rstrip() + "…"


async def list_conversations(db: AsyncSession, user_id: str) -> list[Conversation]:
    result = await db.execute(
        select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_conversation_detail(db: AsyncSession, user_id: str, conversation_id: str) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return row


async def resolve_conversation(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str | None,
    first_message: str,
    jurisdiction: str = "",
    mode: str = "Workflow",
) -> Conversation:
    """Load the caller's existing conversation, or start a new one — the
    single place a conversation gets created, so every ask-kriton call goes
    through the same ownership check rather than each caller re-deriving it."""
    if conversation_id:
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        return row

    conversation = Conversation(
        tenant_id=tenant_id,
        user_id=user_id,
        title=_auto_title(first_message),
        jurisdiction=jurisdiction,
        mode=mode,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def record_turn(
    db: AsyncSession,
    *,
    conversation: Conversation,
    tenant_id: str,
    user_id: str,
    query: str,
    answer_text: str,
    route: str | None,
    risk_level: str | None,
    citations: list[dict] | None = None,
) -> None:
    """Append the user's question and Kriton's answer as two messages, and
    bump the conversation's updated_at so the sidebar sorts it to the top."""
    db.add(ChatMessage(
        conversation_id=conversation.id, tenant_id=tenant_id, user_id=user_id,
        role="user", content=query,
    ))
    db.add(ChatMessage(
        conversation_id=conversation.id, tenant_id=tenant_id, user_id=user_id,
        role="assistant", content=answer_text, route=route, risk_level=risk_level,
        citations=citations or None,
    ))
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()


async def rename_conversation(db: AsyncSession, user_id: str, conversation_id: str, title: str) -> Conversation:
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    row.title = title.strip() or row.title
    await db.commit()
    await db.refresh(row)
    return row


async def delete_conversation(db: AsyncSession, user_id: str, conversation_id: str) -> bool:
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True
