from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.governance_dashboard.service import build_governance_dashboard
from app.domains.identity.models import Tenant, User
from app.domains.identity.rbac import get_current_user

router = APIRouter(prefix="/governance-dashboard", tags=["Governance Dashboard"])

_ALLOWED_ROLES = {
    "CFO", "Controller", "Audit Partner", "Tax Director", "Finance Manager",
    "Business Owner", "AI Governance Lead", "Admin",
}


@router.get("")
async def get_governance_dashboard(
    environment: Literal["PRODUCTION", "PREPRODUCTION", "SANDBOX"] = "PRODUCTION",
    jurisdiction: str = Query(default="US", min_length=2, max_length=8),
    window_days: int = Query(default=30, ge=1, le=366),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return an authorization-bound aggregate, never unrestricted raw rows.

    Exceptions, decisions and domain states are read from Kriton's own
    records (see service.py). Parts with no authoritative service yet stay
    not-assessed, and no open exception is never presented as a healthy
    posture: absent evidence is not inferred to be effective.
    """
    if current_user.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Governance Dashboard access is not available for this role")

    tenant_name = (await db.execute(select(Tenant.name).where(Tenant.id == current_user.tenant_id))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)
    context_token = f"{current_user.tenant_id}:{current_user.id}:{current_user.updated_at.isoformat()}"

    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="governance_dashboard.opened",
        emitting_service="governance_dashboard",
        actor_id=current_user.id,
        subject_type="workspace_governance",
        subject_id=current_user.tenant_id,
        payload={
            "environment": environment,
            "jurisdiction": jurisdiction.upper(),
            "assessment_window_days": window_days,
            "role": current_user.role,
            "permission_set_version": current_user.updated_at.isoformat(),
        },
    )

    freshness = {"state": "UNKNOWN", "evaluatedAt": now.isoformat(), "failedReason": "Initial governance assessment has not completed."}
    keys = ["exceptions", "decisions", "domainStates", "releaseReadiness", "sourceGovernanceSummary", "accountabilitySummary", "auditIncidentSummary", "jurisdictionProviderSummary", "materialChanges"]
    panels = await build_governance_dashboard(db, current_user, now)
    accountability, sources, incidents = panels["accountability"], panels["sourceGovernance"], panels["incidents"]
    return {
        "contextToken": context_token,
        "governanceScope": {
            "scopeClass": "WORKSPACE", "tenantId": current_user.tenant_id,
            "workspaceId": current_user.tenant_id, "workspaceName": tenant_name or "Current workspace",
            "entityIds": [], "entitySetLabel": "All authorized entities",
            "jurisdictionCodes": [jurisdiction.upper()], "environment": environment,
            "assessmentWindow": {"start": start.isoformat(), "end": now.isoformat(), "label": f"Last {window_days} days", "includesUnresolvedMaterial": True},
            "roleId": current_user.role, "permissionSetVersion": current_user.updated_at.isoformat(),
            "policyMatrixVersion": "not-assessed",
        },
        "governanceSummary": panels["governanceSummary"],
        "domainStates": panels["domainStates"], "exceptions": panels["exceptions"], "decisions": panels["decisions"],
        "releaseReadiness": panels["releaseReadiness"], "materialChanges": [],
        "accountabilitySummary": {"mandatoryReviews": accountability["mandatoryReviews"], "overdueReviews": accountability["overdueEscalations"], "boundaryEscalations": accountability["boundaryEscalations"], "acceptedExceptions": 0, "reviewerCoverageState": "not_assessed", "traceCompletenessState": "not_assessed", "drilldownTarget": "/professional-boundaries"},
        "sourceGovernanceSummary": {"state": "attention_required" if sources["expiringWithin30Days"] or sources["expired"] else "no_open_exceptions", "licenseStates": sources["licenseStates"], "expiringWithin30Days": sources["expiringWithin30Days"], "expired": sources["expired"], "blockedBundles": 0, "delayedBundleEvidence": 0, "provenanceExceptions": 0, "freshnessExceptions": 0, "ontologyExceptions": 0, "syllabusMappingExceptions": 0, "drilldownTarget": "/source-licensing"},
        "auditIncidentSummary": {"ledgerState": panels["ledger"]["state"], "ledgerEventsChecked": panels["ledger"]["eventsChecked"],"replayState": "not_assessed", "traceCompletenessState": "not_assessed", "retentionState": "not_assessed", "exportIntegrityState": "not_assessed", "openIncidentCounts": incidents["openIncidentCounts"], "escalationCounts": incidents["escalationCounts"], "correctiveActionCounts": {"overdue": 0, "total": 0}, "lastVerifiedAt": now.isoformat(), "drilldownTarget": "/audit-replay"},
        "jurisdictionProviderSummary": {"jurisdictionStates": {}, "rolloutBlocks": 0, "providerAssessmentStates": {}, "integrationExceptions": 0, "nextObligations": [], "drilldownTarget": "/jurisdiction-rollout"},
        "moduleFreshness": {**{key: dict(freshness) for key in keys}, **panels["moduleFreshness"]},
    }
