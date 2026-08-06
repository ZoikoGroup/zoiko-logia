from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin, require_service_role
from app.orchestration import evidence_monitoring
from app.orchestration import visualization_gaps as gaps
from app.orchestration.models import VisualizationTelemetryEvent
from sqlalchemy import select

router = APIRouter(prefix="/orchestration/analytics/visualization-gaps", tags=["Visualization Gap Evidence"])


def _filters(admin: User, date_from, date_to, environment, analytical_intent, requested_chart_type, requested_visualization_family, data_shape_class, evidence_status):
    if date_from and date_to and date_from > date_to: raise HTTPException(422, "date_from must not be after date_to")
    return gaps.GapFilters(tenant_id=admin.tenant_id, date_from=date_from, date_to=date_to, environment=environment,
        analytical_intent=analytical_intent, requested_chart_type=requested_chart_type,
        requested_visualization_family=requested_visualization_family, data_shape_class=data_shape_class, evidence_status_filter=evidence_status)


@router.get("/summary", response_model=gaps.GapSummary)
@router.get("/by-requested-chart", response_model=gaps.GapSummary)
@router.get("/by-analytical-intent", response_model=gaps.GapSummary)
@router.get("/by-data-shape", response_model=gaps.GapSummary)
@router.get("/current-fallback-performance", response_model=gaps.GapSummary)
@router.get("/report-export", response_model=gaps.GapSummary)
async def get_gap_report(date_from: Optional[date]=None, date_to: Optional[date]=None,
    environment: gaps.EnvironmentMarker=Query(gaps.EnvironmentMarker.PRODUCTION), analytical_intent: Optional[str]=None,
    requested_chart_type: Optional[gaps.RequestedChartType]=None, requested_visualization_family: Optional[gaps.RequestedVisualizationFamily]=None,
    data_shape_class: Optional[gaps.DataShapeClass]=None, evidence_status: Optional[gaps.EvidenceStatus]=None,
    db=Depends(get_db), admin: User=Depends(require_admin)):
    filters = _filters(admin,date_from,date_to,environment,analytical_intent,requested_chart_type,requested_visualization_family,data_shape_class,evidence_status)
    gap_events = await gaps.fetch_gap_events(db, filters)
    stmt = select(VisualizationTelemetryEvent).where(
        VisualizationTelemetryEvent.tenant_id == admin.tenant_id,
        VisualizationTelemetryEvent.environment == environment.value,
    )
    if date_from: stmt = stmt.where(VisualizationTelemetryEvent.created_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
    if date_to: stmt = stmt.where(VisualizationTelemetryEvent.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    telemetry_events = list((await db.execute(stmt)).scalars().all())
    selected_query_ids = {event.query_id for event in telemetry_events if event.event_name == "visualization_selected" and event.query_id}
    no_chart_conversations = {event.conversation_id for event in gap_events if event.fallback_output_type != "chart" and event.conversation_id}
    result = gaps.aggregate_gaps(gap_events, len(selected_query_ids) + len(no_chart_conversations))
    for row in result.rows:
        relevant = [event for event in telemetry_events if event.original_chart_type == row.current_fallback]
        if relevant:
            conversations = {event.conversation_id for event in relevant if event.conversation_id}
            switched = {event.conversation_id for event in relevant if event.event_name == "alternative_view_selected" and event.conversation_id}
            denominator = len(conversations)
            row.fallback_switch_rate = len(switched) / denominator if denominator else None
            row.fallback_retention_rate = 1.0 - row.fallback_switch_rate if row.fallback_switch_rate is not None else None
    if evidence_status: result.rows = [row for row in result.rows if row.evidence_status == evidence_status]
    return result


@router.post("/reports", response_model=gaps.GapReportPublic)
async def post_report(payload: gaps.GapReportCreate, db=Depends(get_db), admin: User=Depends(require_admin)):
    try: return await gaps.create_report(db, admin.tenant_id, admin.id, payload)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/reports/{report_id}/{status}", response_model=gaps.GapReportPublic)
async def post_report_transition(report_id: str, status: str, db=Depends(get_db), admin: User=Depends(require_admin)):
    if status not in {"under_review","approved","rejected"}: raise HTTPException(422, "invalid report status")
    try: row = await gaps.transition_report(db, admin.tenant_id, report_id, admin.id, status)
    except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    if row is None: raise HTTPException(404, "Visualization gap report not found")
    return row


@router.post("/evidence-monitoring/run", response_model=evidence_monitoring.MonitoringRunResult)
async def post_evidence_monitoring_run(db=Depends(get_db), admin: User=Depends(require_admin)):
    """V8.4 — explicitly-invokable, admin-triggered evidence-monitoring run.
    Never approves anything; only ever creates a draft report
    (status="draft") when at least one finding clears both the sample-size
    and source-diversity thresholds, and only once per distinct evidence
    version. Rejects a second concurrent submission for the same tenant
    with 409 rather than racing it (V8.5 requirement: prevent duplicate
    manual submissions while a run is active)."""
    try:
        return await evidence_monitoring.run_evidence_monitoring(db, admin.tenant_id, trigger_source="manual", triggered_by=admin.id)
    except evidence_monitoring.MonitoringRunAlreadyActiveError:
        raise HTTPException(409, "A monitoring run is already active for this tenant — wait for it to finish.")


@router.post("/evidence-monitoring/scheduled-run", response_model=evidence_monitoring.MonitoringRunResult)
async def post_evidence_monitoring_scheduled_run(
    tenant_id: str, db=Depends(get_db), _service: None = Depends(require_service_role),
):
    """V8.5 — protected operational endpoint for the external daily
    scheduler (see scripts/run_evidence_monitoring_job.py, wired to Railway
    Cron). Service-role only: no human Supabase session/JWT involved, no
    report-approval capability (this only ever calls run_evidence_monitoring,
    which never transitions a report past "draft"), no visualization-
    selection side effects. Tenant-scoped by the required tenant_id — the
    scheduled job calls this once per tenant, never in bulk, so tenant
    isolation is preserved by construction the same way the manual path is."""
    try:
        return await evidence_monitoring.run_evidence_monitoring(db, tenant_id, trigger_source="scheduled", triggered_by="scheduled:railway-cron")
    except evidence_monitoring.MonitoringRunAlreadyActiveError:
        raise HTTPException(409, "A monitoring run is already active for this tenant — safe to retry later.")


@router.get("/evidence-monitoring/status", response_model=evidence_monitoring.MonitoringStatusResponse)
async def get_evidence_monitoring_status(db=Depends(get_db), admin: User=Depends(require_admin)):
    return await evidence_monitoring.get_monitoring_status(db, admin.tenant_id)
