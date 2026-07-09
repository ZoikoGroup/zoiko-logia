"""
Ask Kriton REST API — the single entry point that runs retrieve -> classify
-> compose -> audit for one query.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.orchestration.schemas import AskKritonRequest, AskKritonResponse
from app.orchestration.service import ask_kriton

router = APIRouter(prefix="/kriton", tags=["orchestration"])


@router.post("/ask", response_model=AskKritonResponse)
async def post_ask(
    payload: AskKritonRequest,
    db: AsyncSession = Depends(get_db),
    sync_db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
) -> AskKritonResponse:
    return await ask_kriton(
        db,
        sync_db,
        actor_id=current_user.id,
        tenant_id=current_user.tenant_id,
        role=current_user.role,
        request=payload,
    )
