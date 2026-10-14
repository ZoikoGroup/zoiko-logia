from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.command_center import service
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user

router = APIRouter(prefix="/command-center", tags=["Command Center"])


class ContextSwitchRequest(BaseModel):
    jurisdiction: str
    framework: str
    period: str
    previous_context_token: str


@router.post("/context")
async def switch_command_center_context(
    payload: ContextSwitchRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    allowed_jurisdictions = {"US", "GB"}
    allowed_frameworks = {"US-GAAP", "IFRS"}
    if payload.jurisdiction.upper() not in allowed_jurisdictions or payload.framework.upper() not in allowed_frameworks:
        await record_event_async(
            db, tenant_id=current_user.tenant_id, event_name="command_center.context_switch_denied",
            emitting_service="command_center", actor_id=current_user.id,
            subject_type="workspace", subject_id=current_user.tenant_id,
            payload={"reason": "context_not_entitled", "idempotency_key": idempotency_key},
        )
        raise HTTPException(status_code=403, detail="The requested accounting context is not available")

    await record_event_async(
        db, tenant_id=current_user.tenant_id, event_name="command_center.context_selected",
        emitting_service="command_center", actor_id=current_user.id,
        subject_type="workspace", subject_id=current_user.tenant_id,
        payload={
            "jurisdiction": payload.jurisdiction.upper(), "framework": payload.framework.upper(),
            "period": payload.period, "previous_context_token": payload.previous_context_token,
            "boundary_type": "workspace", "idempotency_key": idempotency_key,
        },
    )
    return {"accepted": True, "boundaryType": "workspace"}


@router.get("")
async def get_command_center(
    background: BackgroundTasks,
    jurisdiction: str = Query(default="US", min_length=2, max_length=8),
    framework: str = Query(default="US-GAAP", min_length=2, max_length=24),
    period: str = Query(default="FY2026", min_length=2, max_length=24),
    fresh: bool = False,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return one tenant- and permission-bound operational view model.

    Every count is read live from the tenant's records (see service.py); a
    panel with no records stays empty rather than showing an invented count.
    """
    now = datetime.now(timezone.utc)
    permission_version = current_user.updated_at.isoformat()
    context_token = f"{current_user.tenant_id}:{current_user.id}:{permission_version}:{jurisdiction}:{framework}:{period}"

    background.add_task(
        service.record_opened, current_user,
        event_name="command_center.opened", emitting_service="command_center", subject_type="workspace",
        payload={
            "boundary_type": "workspace",
            "jurisdiction": jurisdiction.upper(),
            "framework": framework.upper(),
            "period": period,
            "role": current_user.role,
            "permission_set_version": permission_version,
        },
    )

    view = await service.cached(
        ("command_center", current_user.tenant_id, current_user.id, current_user.role, permission_version),
        lambda: service.build_command_center(current_user, now), fresh=fresh,
    )
    return {
        "contextToken": context_token,
        "activeContext": {
            "tenantId": current_user.tenant_id, "workspaceId": current_user.tenant_id,
            "workspaceName": view["workspaceName"],
            "jurisdictionCode": jurisdiction.upper(), "frameworkCode": framework.upper(),
            "periodId": period.lower(), "periodLabel": period, "boundaryType": "workspace",
            "roleId": current_user.role, "permissionSetVersion": permission_version,
        },
        **view,
    }


@router.get("/workspace")
async def get_my_workspace(
    fresh: bool = False,
    current_user: User = Depends(get_current_user),
) -> dict:
    """The signed-in user's own recent work and pending tasks."""
    return await service.cached(
        ("my_workspace", current_user.tenant_id, current_user.id, current_user.role, current_user.updated_at.isoformat()),
        lambda: service.build_my_workspace(current_user, datetime.now(timezone.utc)), fresh=fresh,
    )
