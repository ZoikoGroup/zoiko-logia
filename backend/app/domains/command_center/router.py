from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import Tenant, User
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
    jurisdiction: str = Query(default="US", min_length=2, max_length=8),
    framework: str = Query(default="US-GAAP", min_length=2, max_length=24),
    period: str = Query(default="FY2026", min_length=2, max_length=24),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return one tenant- and permission-bound operational view model.

    This endpoint intentionally returns empty professional collections until
    their authoritative services contain records. Absence of evidence never
    becomes an invented healthy count or assurance claim.
    """
    tenant_name = (await db.execute(select(Tenant.name).where(Tenant.id == current_user.tenant_id))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    permission_version = current_user.updated_at.isoformat()
    context_token = f"{current_user.tenant_id}:{current_user.id}:{permission_version}:{jurisdiction}:{framework}:{period}"

    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="command_center.opened",
        emitting_service="command_center",
        actor_id=current_user.id,
        subject_type="workspace",
        subject_id=current_user.tenant_id,
        payload={
            "boundary_type": "workspace",
            "jurisdiction": jurisdiction.upper(),
            "framework": framework.upper(),
            "period": period,
            "role": current_user.role,
            "permission_set_version": permission_version,
        },
    )

    unavailable = {"state": "unavailable", "failedReason": "The authoritative service has not completed its first assessment."}
    return {
        "contextToken": context_token,
        "activeContext": {
            "tenantId": current_user.tenant_id, "workspaceId": current_user.tenant_id,
            "workspaceName": tenant_name or "Current workspace",
            "jurisdictionCode": jurisdiction.upper(), "frameworkCode": framework.upper(),
            "periodId": period.lower(), "periodLabel": period, "boundaryType": "workspace",
            "roleId": current_user.role, "permissionSetVersion": permission_version,
        },
        "professionalSummary": {
            "attentionCount": 0, "reviewCount": 0, "deadlineCount": 0,
            "summaryGeneratedAt": now.isoformat(), "dataFreshnessState": "current",
        },
        "attentionItems": [], "activeMatters": [], "deadlines": [], "reviewQueue": [], "recentWork": [],
        "assuranceStatus": {
            "overallState": "unknown",
            "controls": {
                "source_authority": "unavailable", "citation_validation": "unavailable",
                "effective_date_control": "unavailable", "jurisdiction_control": "unavailable",
                "boundary_enforcement": "ok", "human_review_policy": "unavailable",
                "source_licensing": "unavailable", "audit_recording": "ok",
            },
            "lastEvaluatedAt": now.isoformat(), "policyVersion": "not-assessed",
            "exceptionIds": [],
        },
        "moduleFreshness": {
            "attentionItems": dict(unavailable), "activeMatters": dict(unavailable),
            "deadlines": dict(unavailable), "reviewQueue": dict(unavailable),
            "recentWork": dict(unavailable),
            "assuranceStatus": {"state": "current"},
        },
    }
