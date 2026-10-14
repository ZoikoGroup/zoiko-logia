from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

from app.domains.command_center.service import build_governance, cached, record_opened
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user

router = APIRouter(prefix="/governance-dashboard", tags=["Governance Dashboard"])

# Matches the frontend menu (every role except Learner). The page is an
# aggregate; panels that expose individual records are further gated on the
# same permissions their own pages require.
_ALLOWED_ROLES = {
    "CFO", "Controller", "Audit Partner", "Tax Director", "Finance Manager",
    "Business Owner", "AI Governance Lead", "Admin",
    "Governance Ops Lead", "Source Admin", "Syllabus Admin", "Jurisdiction Lead",
    "Risk Admin", "System Auditor", "SME Reviewer",
}


@router.get("")
async def get_governance_dashboard(
    background: BackgroundTasks,
    environment: Literal["CONNECTED", "PRODUCTION"] = "CONNECTED",
    jurisdiction: str = Query(default="US", min_length=2, max_length=8),
    window_days: int = Query(default=30, ge=1, le=366),
    fresh: bool = False,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return an authorization-bound aggregate, never unrestricted raw rows.

    Every domain state is computed live from the tenant's escalations,
    incidents, review cases, sources and evaluation runs. A domain with no
    records reports "Not assessed" rather than an inferred healthy posture.
    """
    if current_user.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Governance Dashboard access is not available for this role")

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)
    permission_version = current_user.updated_at.isoformat()
    context_token = f"{current_user.tenant_id}:{current_user.id}:{permission_version}"

    background.add_task(
        record_opened, current_user,
        event_name="governance_dashboard.opened", emitting_service="governance_dashboard",
        subject_type="workspace_governance",
        payload={
            "environment": environment,
            "jurisdiction": jurisdiction.upper(),
            "assessment_window_days": window_days,
            "role": current_user.role,
            "permission_set_version": permission_version,
        },
    )

    view = await cached(
        ("governance", current_user.tenant_id, current_user.id, current_user.role, permission_version, environment, window_days),
        lambda: build_governance(current_user, now, window_days, "CONNECTED"), fresh=fresh,
    )
    return {
        "contextToken": context_token,
        "assessmentWindow": {"start": view["scope"]["windowStart"], "end": view["scope"]["windowEnd"], "label": f"Last {window_days} days"},
        **view,
    }


@router.get("/release-readiness")
async def get_release_readiness(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Release gate states for the Release Gates page, measured from live
    evidence by governance_dashboard.assessment (evaluation result packs, the
    audit ledger, incidents, risk policy, licences, escalation SLAs). Kept
    separate from the dashboard aggregate above, which this page doesn't need."""
    if current_user.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Release gates are not available for this role")
    from app.domains.governance_dashboard.assessment import assess

    return (await assess(db, current_user)).release
