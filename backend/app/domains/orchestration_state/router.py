from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.orchestration_state.schemas import AgentRunCancel, AgentRunCreate, AgentRunPublic
from app.domains.orchestration_state.service import (
    cancel_agent_run, create_agent_run, execute_agent_run, get_agent_run, serialize_agent_run,
)


router = APIRouter(prefix="/agent-runs", tags=["agent_runtime"])


@router.post("", response_model=AgentRunPublic)
async def start_agent_run(
    payload: AgentRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunPublic:
    run = await create_agent_run(
        db,
        payload=payload,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )
    run = await execute_agent_run(db, run)
    return await serialize_agent_run(db, run)


@router.get("/{run_id}", response_model=AgentRunPublic)
async def read_agent_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunPublic:
    run = await get_agent_run(
        db, run_id=run_id, tenant_id=current_user.tenant_id, user_id=current_user.id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return await serialize_agent_run(db, run)


@router.post("/{run_id}/resume", response_model=AgentRunPublic)
async def resume_agent_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunPublic:
    run = await get_agent_run(
        db, run_id=run_id, tenant_id=current_user.tenant_id, user_id=current_user.id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.status == "CANCELLED":
        raise HTTPException(status_code=409, detail="A cancelled agent run cannot be resumed")
    run = await execute_agent_run(db, run)
    return await serialize_agent_run(db, run)


@router.post("/{run_id}/cancel", response_model=AgentRunPublic)
async def cancel_run(
    run_id: str,
    payload: AgentRunCancel,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunPublic:
    run = await get_agent_run(
        db, run_id=run_id, tenant_id=current_user.tenant_id, user_id=current_user.id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    run = await cancel_agent_run(db, run, payload.reason)
    return await serialize_agent_run(db, run)
