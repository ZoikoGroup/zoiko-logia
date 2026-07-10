"""
Ask Kriton™ REST API — ZL-ENG-02 §4.

POST /api/v1/orchestration/ask
Required header: Idempotency-Key: <client-generated-key>

Controls:
  - Authentication context (tenant_id, user_id) resolved from auth; never trusted from body.
  - Idempotency: duplicate Idempotency-Key returns original result without re-execution.
  - Rate limiting: enforced before retrieval or model work.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.orchestration.schemas import AskKritonRequest, AskKritonResponse
from app.orchestration.service import ask_kriton

router = APIRouter(prefix="/orchestration", tags=["Ask Kriton™ Orchestration"])


@router.post("/ask", response_model=AskKritonResponse)
async def post_ask(
    payload: AskKritonRequest,
    db: AsyncSession = Depends(get_db),
    sync_db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> AskKritonResponse:
    """
    Submit a query to Kriton™. Returns a deterministic route-driven response contract.

    The response outcome/route drives frontend rendering — do not infer state from answer text.
    Internal hashes, policy internals and audit chain material are not exposed (§12).
    """
    return await ask_kriton(
        db,
        sync_db,
        actor_id=current_user.id,
        tenant_id=current_user.tenant_id,
        role=current_user.role,
        request=payload,
        idempotency_key=idempotency_key,
    )
