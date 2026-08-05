from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin, require_service_role
from app.orchestration import visualization_personalization as personalization

router = APIRouter(prefix="/orchestration/analytics/visualization-personalization", tags=["Visualization Personalization"])


@router.post("/recompute", response_model=personalization.RecomputationRunResult)
async def post_visualization_personalization_recompute(db=Depends(get_db), admin: User = Depends(require_admin)):
    """V10 — explicitly-invokable, admin-triggered profile recomputation.
    Recomputes only for actors with active consent (requirement 3); never
    reads or exposes an individual behavioral profile to the admin caller
    (requirement: SECURITY #3/#4) — only aggregate run outcome counts."""
    try:
        return await personalization.recompute_tenant_profiles(db, admin.tenant_id, triggered_by=admin.id)
    except personalization.MonitoringRunAlreadyActiveError:
        raise HTTPException(409, "A personalization recomputation run is already active for this tenant.")


@router.post("/scheduled-recompute", response_model=personalization.RecomputationRunResult)
async def post_visualization_personalization_scheduled_recompute(
    tenant_id: str, db=Depends(get_db), _service: None = Depends(require_service_role),
):
    """V10 — protected operational endpoint for the external daily
    scheduler (see scripts/recompute_personalization_profiles.py, wired to
    Railway Cron alongside V8.5's evidence-monitoring job). Service-role
    only, tenant-scoped, idempotent — same contract as V8.5's
    scheduled-run endpoint."""
    try:
        return await personalization.recompute_tenant_profiles(db, tenant_id, triggered_by="scheduled:railway-cron")
    except personalization.MonitoringRunAlreadyActiveError:
        raise HTTPException(409, "A personalization recomputation run is already active for this tenant — safe to retry later.")
