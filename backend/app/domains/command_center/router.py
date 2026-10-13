from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.command_center.home import build_home
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """The signed-in user's home view (Command Center and My Workspace):
    their real attention items, review queue, deadlines, engagements and
    recent work — see home.py. Empty means empty: no sample matters."""
    model = await build_home(db, current_user)
    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="command_center.opened",
        emitting_service="command_center",
        actor_id=current_user.id,
        subject_type="workspace",
        subject_id=current_user.tenant_id,
        payload={"boundary_type": "workspace", "role": current_user.role},
    )
    return model
