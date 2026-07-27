"""
Chat History domain (app/domains/chat_history) — persisted conversations and
messages for Ask Kriton™, so a conversation survives a page reload and is
browsable like ChatGPT's sidebar.

Requires a live DB (creates real Tenant/User rows) — run inside the backend
container:
    docker compose exec backend python3 tests/test_chat_history.py
"""
import asyncio
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import HTTPException

from app.core.database import AsyncSessionLocal
from app.domains.chat_history import service as chat_history_service
from app.domains.chat_history.models import ChatMessage, Conversation
from app.domains.identity.models import Tenant, User


async def _make_tenant_and_user(db) -> tuple[str, str]:
    tenant = Tenant(name=f"Chat History Test Tenant {uuid.uuid4().hex[:8]}")
    db.add(tenant)
    await db.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"{uuid.uuid4().hex[:8]}@chat-history-test.local",
        full_name="Chat History Test User",
        role="Learner",
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return tenant.id, user.id


async def test_new_conversation_gets_auto_title_and_first_turn_persists():
    async with AsyncSessionLocal() as db:
        tenant_id, user_id = await _make_tenant_and_user(db)
        conversation = await chat_history_service.resolve_conversation(
            db, tenant_id=tenant_id, user_id=user_id, conversation_id=None,
            first_message="What is the VAT registration threshold in the UK?",
        )
        assert conversation.title == "What is the VAT registration threshold in the UK?"

        citations = [{"ref_id": "1", "source_id": "src-1", "title": "HMRC VAT Notice 700/1", "source_type": "document"}]
        await chat_history_service.record_turn(
            db, conversation=conversation, tenant_id=tenant_id, user_id=user_id,
            query="What is the VAT registration threshold in the UK?",
            answer_text="The UK VAT registration threshold is £90,000 [REF-1].",
            route="LLM", risk_level="LOW", citations=citations,
        )

        detail = await chat_history_service.get_conversation_detail(db, user_id, conversation.id)
        assert len(detail.messages) == 2
        assert detail.messages[0].role == "user"
        assert detail.messages[0].citations is None
        assert detail.messages[1].role == "assistant"
        assert detail.messages[1].risk_level == "LOW"
        assert detail.messages[1].citations == citations, "citations must round-trip so a reopened chat shows sources"

        await db.delete(conversation)
        await db.commit()
    print("test_new_conversation_gets_auto_title_and_first_turn_persists: PASSED")


async def test_long_first_message_title_is_truncated():
    async with AsyncSessionLocal() as db:
        tenant_id, user_id = await _make_tenant_and_user(db)
        long_query = "Can you explain in detail " + "the full IFRS 16 lease accounting treatment " * 3
        conversation = await chat_history_service.resolve_conversation(
            db, tenant_id=tenant_id, user_id=user_id, conversation_id=None, first_message=long_query,
        )
        assert len(conversation.title) <= 61  # 60 chars + ellipsis
        assert conversation.title.endswith("…")

        await db.delete(conversation)
        await db.commit()
    print("test_long_first_message_title_is_truncated: PASSED")


async def test_existing_conversation_id_reuses_conversation_not_new_one():
    async with AsyncSessionLocal() as db:
        tenant_id, user_id = await _make_tenant_and_user(db)
        first = await chat_history_service.resolve_conversation(
            db, tenant_id=tenant_id, user_id=user_id, conversation_id=None, first_message="First question",
        )
        await chat_history_service.record_turn(
            db, conversation=first, tenant_id=tenant_id, user_id=user_id,
            query="First question", answer_text="First answer", route="LLM", risk_level="LOW",
        )

        second_turn = await chat_history_service.resolve_conversation(
            db, tenant_id=tenant_id, user_id=user_id, conversation_id=first.id, first_message="Follow-up question",
        )
        assert second_turn.id == first.id
        await chat_history_service.record_turn(
            db, conversation=second_turn, tenant_id=tenant_id, user_id=user_id,
            query="Follow-up question", answer_text="Follow-up answer", route="LLM", risk_level="LOW",
        )

        detail = await chat_history_service.get_conversation_detail(db, user_id, first.id)
        assert len(detail.messages) == 4, "both turns must land in the SAME conversation, not two separate ones"

        await db.delete(first)
        await db.commit()
    print("test_existing_conversation_id_reuses_conversation_not_new_one: PASSED")


async def test_cannot_load_or_resolve_another_users_conversation():
    async with AsyncSessionLocal() as db:
        tenant_a, user_a = await _make_tenant_and_user(db)
        tenant_b, user_b = await _make_tenant_and_user(db)

        conversation = await chat_history_service.resolve_conversation(
            db, tenant_id=tenant_a, user_id=user_a, conversation_id=None, first_message="Private question",
        )

        raised = False
        try:
            await chat_history_service.get_conversation_detail(db, user_b, conversation.id)
        except HTTPException as e:
            raised = e.status_code == 404
        assert raised, "a different user must not be able to read another user's conversation"

        raised = False
        try:
            await chat_history_service.resolve_conversation(
                db, tenant_id=tenant_b, user_id=user_b, conversation_id=conversation.id, first_message="hijack attempt",
            )
        except HTTPException as e:
            raised = e.status_code == 404
        assert raised, "a different user must not be able to append to another user's conversation"

        await db.delete(conversation)
        await db.commit()
    print("test_cannot_load_or_resolve_another_users_conversation: PASSED")


async def test_delete_conversation_cascades_to_messages():
    async with AsyncSessionLocal() as db:
        tenant_id, user_id = await _make_tenant_and_user(db)
        conversation = await chat_history_service.resolve_conversation(
            db, tenant_id=tenant_id, user_id=user_id, conversation_id=None, first_message="Question to delete",
        )
        await chat_history_service.record_turn(
            db, conversation=conversation, tenant_id=tenant_id, user_id=user_id,
            query="Question to delete", answer_text="Answer to delete", route="LLM", risk_level="LOW",
        )
        conversation_id = conversation.id

        ok = await chat_history_service.delete_conversation(db, user_id, conversation_id)
        assert ok

        from sqlalchemy import select
        remaining = await db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id))
        assert remaining.scalars().all() == [], "deleting a conversation must cascade-delete its messages"
    print("test_delete_conversation_cascades_to_messages: PASSED")


async def test_list_orders_most_recently_updated_first():
    async with AsyncSessionLocal() as db:
        tenant_id, user_id = await _make_tenant_and_user(db)
        older = await chat_history_service.resolve_conversation(
            db, tenant_id=tenant_id, user_id=user_id, conversation_id=None, first_message="Older conversation",
        )
        newer = await chat_history_service.resolve_conversation(
            db, tenant_id=tenant_id, user_id=user_id, conversation_id=None, first_message="Newer conversation",
        )

        rows = await chat_history_service.list_conversations(db, user_id)
        ids_in_order = [r.id for r in rows]
        assert ids_in_order.index(newer.id) < ids_in_order.index(older.id), (
            "most-recently-created conversation must sort first when neither has new messages"
        )

        # Renaming (or any update) to the OLDER conversation must bump it back
        # to the top — "most recently active," matching ChatGPT's ordering,
        # not "most recently created."
        await chat_history_service.rename_conversation(db, user_id, older.id, "My renamed chat")
        rows = await chat_history_service.list_conversations(db, user_id)
        ids_in_order = [r.id for r in rows]
        assert ids_in_order.index(older.id) < ids_in_order.index(newer.id), (
            "renaming a conversation must bump it back to the top of the list"
        )

        await db.delete(older)
        await db.delete(newer)
        await db.commit()
    print("test_list_orders_most_recently_updated_first: PASSED")


async def main():
    await test_new_conversation_gets_auto_title_and_first_turn_persists()
    await test_long_first_message_title_is_truncated()
    await test_existing_conversation_id_reuses_conversation_not_new_one()
    await test_cannot_load_or_resolve_another_users_conversation()
    await test_delete_conversation_cascades_to_messages()
    await test_list_orders_most_recently_updated_first()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
