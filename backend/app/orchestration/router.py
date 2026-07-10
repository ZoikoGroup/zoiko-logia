"""
Ask Kriton REST API — the single entry point that runs retrieve -> classify
-> compose -> audit for one query.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.core.rate_limit import limiter
from app.core.security import decode_access_token
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.orchestration.schemas import AskKritonRequest, AskKritonResponse
from app.orchestration.service import ask_kriton, get_idempotent_response, store_idempotent_response

router = APIRouter(prefix="/kriton", tags=["orchestration"])


def _user_key(request: Request) -> str:
    """Rate-limit key: the authenticated user's id, not IP — this is an
    authenticated API and a shared NAT/office IP must not share one bucket."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    payload = decode_access_token(token) if token else None
    return payload.sub if payload else "anonymous"


@router.post("/ask", response_model=AskKritonResponse)
@limiter.limit("30/minute", key_func=_user_key)
async def post_ask(
    request: Request,
    payload: AskKritonRequest,
    db: AsyncSession = Depends(get_db),
    sync_db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> AskKritonResponse:
    if idempotency_key:
        cached = get_idempotent_response(sync_db, tenant_id=current_user.tenant_id, idempotency_key=idempotency_key)
        if cached is not None:
            return AskKritonResponse.model_validate(cached)

    response = await ask_kriton(
        db,
        sync_db,
        actor_id=current_user.id,
        tenant_id=current_user.tenant_id,
        role=current_user.role,
        request=payload,
    )

    if idempotency_key:
        store_idempotent_response(
            sync_db,
            tenant_id=current_user.tenant_id,
            idempotency_key=idempotency_key,
            response=response.model_dump(mode="json"),
        )

    return response
