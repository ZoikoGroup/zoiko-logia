from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
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

    Until a tenant has completed its first governance assessment the honest
    result is an empty/not-assessed model. This deliberately avoids presenting
    sample metrics or inferring a healthy posture from absent evidence.
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
        "governanceSummary": {
            "overallState": "not_assessed", "criticalExceptionCount": 0, "highExceptionCount": 0,
            "pendingDecisionCount": 0, "blockedGateCount": 0,
            "partialDataDomains": ["All governance domains"], "lastEvaluatedAt": now.isoformat(), "freshnessState": "UNKNOWN",
        },
        "domainStates": [], "exceptions": [], "decisions": [], "releaseReadiness": [], "materialChanges": [],
        "accountabilitySummary": {"mandatoryReviews": 0, "overdueReviews": 0, "boundaryEscalations": 0, "acceptedExceptions": 0, "reviewerCoverageState": "not_assessed", "traceCompletenessState": "not_assessed", "drilldownTarget": "/professional-boundaries"},
        "sourceGovernanceSummary": {"state": "not_assessed", "licenseStates": {}, "expiringWithin30Days": 0, "blockedBundles": 0, "delayedBundleEvidence": 0, "provenanceExceptions": 0, "freshnessExceptions": 0, "ontologyExceptions": 0, "syllabusMappingExceptions": 0, "drilldownTarget": "/source-licensing"},
        "auditIncidentSummary": {"ledgerState": "effective", "replayState": "not_assessed", "traceCompletenessState": "not_assessed", "retentionState": "not_assessed", "exportIntegrityState": "not_assessed", "openIncidentCounts": {s: 0 for s in ["critical", "high", "medium", "low", "informational"]}, "escalationCounts": {}, "correctiveActionCounts": {"overdue": 0, "total": 0}, "lastVerifiedAt": now.isoformat(), "drilldownTarget": "/audit-replay"},
        "jurisdictionProviderSummary": {"jurisdictionStates": {}, "rolloutBlocks": 0, "providerAssessmentStates": {}, "integrationExceptions": 0, "nextObligations": [], "drilldownTarget": "/jurisdiction-rollout"},
        "moduleFreshness": {key: dict(freshness) for key in keys},
    }
