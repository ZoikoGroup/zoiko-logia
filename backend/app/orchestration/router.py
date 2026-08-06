"""
Ask Kriton™ REST API — ZL-ENG-02 §4.

POST /api/v1/orchestration/ask
Required header: Idempotency-Key: <client-generated-key>

Controls:
  - Authentication context (tenant_id, user_id) resolved from auth; never trusted from body.
  - Idempotency: duplicate Idempotency-Key returns original result without re-execution.
  - Rate limiting: enforced before retrieval or model work.
"""
import logging

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.core.rate_limit import limiter
from app.core.supabase_auth import verify_token
from app.domains.chat_history import service as chat_history_service
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.orchestration.schemas import AskKritonRequest, AskKritonResponse
from app.orchestration.service import ask_kriton

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestration", tags=["Ask Kriton™ Orchestration"])


def _user_key(request: Request) -> str:
    """Rate-limit key: the authenticated user's id, not IP — this is an
    authenticated API and a shared NAT/office IP must not share one bucket."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    claims = verify_token(token) if token else None
    return claims.sub if claims else "anonymous"


def _transcript_text(response: AskKritonResponse) -> str:
    """What to store as the assistant's chat-history message for any
    outcome — ask_kriton() has ~10 distinct return branches (answered,
    refused, clarification, human review, security incident...) and only
    "answered" populates `answer`; every other branch puts its user-facing
    text in `next_action.message` instead."""
    if response.answer is not None:
        return response.answer.text
    if response.next_action is not None:
        return response.next_action.message
    return f"[{response.outcome}]"


@router.post("/ask", response_model=AskKritonResponse)
@limiter.limit("30/minute", key_func=_user_key)
async def post_ask(
    request: Request,
    payload: AskKritonRequest,
    db: AsyncSession = Depends(get_db),
    sync_db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
) -> AskKritonResponse:
    """
    Submit a query to Kriton™. Returns a deterministic route-driven response contract.

    The response outcome/route drives frontend rendering — do not infer state from answer text.
    Internal hashes, policy internals and audit chain material are not exposed (§12).
    """
    conversation = await chat_history_service.resolve_conversation(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
        first_message=payload.query,
        jurisdiction=payload.jurisdiction,
        mode=payload.mode,
    )

    response = await ask_kriton(
        db,
        sync_db,
        actor_id=current_user.id,
        tenant_id=current_user.tenant_id,
        role=current_user.role,
        request=payload,
        idempotency_key=idempotency_key,
    )

    # Persistence failure must not destroy an answer that already cost a full
    # retrieval + model run: raising here would surface as a 500 and lose the
    # composed response entirely, which is strictly worse than losing the
    # transcript row. Logged at exception level so a systematically failing
    # write is still visible rather than silently dropping history.
    try:
        await chat_history_service.record_turn(
            db,
            conversation=conversation,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            query=payload.query,
            answer_text=_transcript_text(response),
            route=response.route,
            risk_level=response.safety.risk_level,
            citations=[c.model_dump() for c in response.answer.citations] if response.answer else None,
        )
    except Exception:
        logger.exception(
            "chat history persistence failed for conversation %s; returning the answer anyway",
            conversation.id,
        )
        await db.rollback()

    response.conversation_id = conversation.id
    return response
