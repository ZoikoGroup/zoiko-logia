from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.governance_dashboard.assessment import assess, overall_state
from app.domains.identity.models import Tenant, User
from app.domains.identity.permissions import ASSIGNABLE_ROLES
from app.domains.identity.rbac import get_current_user

router = APIRouter(prefix="/governance-dashboard", tags=["Governance Dashboard"])

# Every governance role in the permission registry plus the legacy demo
# personas the frontend still knows. Learners (students) have no governance
# view; the sidebar hides it from them too.
_ALLOWED_ROLES = (ASSIGNABLE_ROLES - {"Learner"}) | {
    "CFO", "Controller", "Audit Partner", "Tax Director", "Finance Manager",
    "Business Owner", "AI Governance Lead",
}


@router.get("")
async def get_governance_dashboard(
    environment: Literal["PRODUCTION", "PREPRODUCTION", "SANDBOX"] = "PRODUCTION",
    window_days: int = Query(default=30, ge=1, le=366),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Authorization-bound aggregate of the tenant's real governance records
    (see assessment.py) — never raw rows, and never sample values: anything
    the platform cannot measure yet is returned as not_assessed with a reason."""
    if current_user.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Governance Dashboard access is not available for this role")

    tenant_name = (await db.execute(select(Tenant.name).where(Tenant.id == current_user.tenant_id))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    result = await assess(db, current_user, now=now)

    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="governance_dashboard.opened",
        emitting_service="governance_dashboard",
        actor_id=current_user.id,
        subject_type="workspace_governance",
        subject_id=current_user.tenant_id,
        payload={"environment": environment, "assessment_window_days": window_days, "role": current_user.role},
    )

    severities = [alert["severity"] for alert in result.alerts]
    return {
        "governanceScope": {
            "tenantId": current_user.tenant_id,
            "workspaceName": tenant_name or "Current workspace",
            "environment": environment,
            "assessmentWindow": {
                "start": (now - timedelta(days=window_days)).isoformat(), "end": now.isoformat(),
                "label": f"Last {window_days} days",
            },
            "roleId": current_user.role,
        },
        "governanceSummary": {
            "overallState": overall_state(result.domains),
            "criticalExceptionCount": severities.count("critical"),
            "highExceptionCount": severities.count("high"),
            "pendingDecisionCount": len(result.queue),
            "blockedGateCount": sum(1 for gate in result.release if gate["state"] == "blocked"),
            "notAssessedDomains": [d["label"] for d in result.domains if d["state"] == "not_assessed"],
            "lastEvaluatedAt": now.isoformat(),
        },
        "domainStates": result.domains,
        "exceptions": result.alerts,
        "decisions": result.queue,
        "releaseReadiness": result.release,
    }
