"""
Chat History domain — persisted conversations and messages for Ask Kriton™,
so a conversation survives a page reload and is browsable the way ChatGPT's
sidebar is (list past conversations, reopen one, see the full transcript).

Deliberately separate from kriton_workspace's SavedAnswer/Draft models
(explicit "save this one answer for reuse" actions) — this is the passive,
automatic transcript of every turn, not a user-curated collection.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="New conversation")
    jurisdiction: Mapped[str] = mapped_column(String, nullable=False, default="")
    mode: Mapped[str] = mapped_column(String, nullable=False, default="Workflow")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    # Bumped on every new message so the sidebar can sort "most recently
    # active first," matching ChatGPT's ordering.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )

    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized onto the message (not just reachable via conversation_id)
    # so a message row can be scoped/queried on its own without a join —
    # same convention kriton_workspace's SavedAnswer/Draft already use.
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Assistant-message metadata only (None for role="user") — enough for the
    # sidebar/transcript to show why an answer looks the way it does
    # (e.g. a HUMAN_REVIEW badge) without re-deriving it from scratch.
    route: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String, nullable=True)
    # List[SourceCitation]-shaped dicts (ref_id/source_id/title/source_type/
    # source_url) from AskKritonResponse.answer.citations at persist time —
    # without this, reopening a past conversation had no citations to show
    # at all (responseFromMessage() on the frontend had nothing but an
    # empty list to fall back to). None for role="user" or non-answered routes.
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),
    )
