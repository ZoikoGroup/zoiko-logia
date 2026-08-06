"""V8.4/V8.5 — production evidence monitoring, review, and operationalization.

Reads the SAME production visualization_gap_events evidence V8.2/V8.3
already collect and aggregate (see visualization_gaps.py) and adds one
layer on top: a re-invocable aggregation run that (a) applies a source-
diversity gate no earlier version enforced (a finding cannot become
eligible_for_review off a single conversation or a single actor, however
many events it has), and (b) when at least one finding clears that gate,
deterministically drafts a governed report artifact for reviewers —
never approves it, never touches chart selection, never activates
anything (selection_activation is always "none").

This module never adds chart types, changes ranking weights, or reads its
own output back into presentation_dataprofile.py — same "proposal, never
autonomously activated" boundary as ranking_configuration.py's
RankingConfiguration and gap_report's manual VisualizationGapReport flow.
Draft reports created here go through the exact same maker-checker
transition_report() lifecycle as a manually created one (see
visualization_gaps.py) — there is no separate, weaker approval path for
monitoring-originated drafts.

Reviewer notification is a dedup record (VisualizationEvidenceAlert), not
a push channel — no email/Slack integration exists in this codebase (see
notifications_workflow, an empty stub domain). Its unique
(tenant_id, evidence_version) constraint is the CONTENT-level dedup: a
second run over the same underlying evidence can never create a second
alert or a second draft report for it.

V8.5 adds full run-lifecycle bookkeeping on top, for real production
scheduling (see scripts/run_evidence_monitoring_job.py and the
service-role-protected /evidence-monitoring/scheduled-run endpoint):

  * A RUN-level idempotency key — (tenant_id, monitoring_period) — distinct
    from the alert's CONTENT-level key. A retried/duplicate trigger for a
    tenant that already has a "running" row for today is rejected
    (MonitoringRunAlreadyActiveError); one that already has a "succeeded"
    row for today returns that prior outcome unchanged rather than
    re-aggregating — both are what make retries and Railway Cron's
    overlap-skip behavior safe no-ops instead of duplicate work.
  * A closed, safe FailureCategory a run can fail with — this module never
    stores str(exception), a query, a chart value, or any other raw
    content in a failure record, only one of a handful of category labels.
  * is_transient_failure_category() — the ONLY signal external retry logic
    (the scheduled job) should use to decide whether to retry a failed
    tenant run. Validation/authorization/schema failures are never
    transient and must not be retried automatically.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError, InterfaceError, ProgrammingError, DataError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.orchestration import visualization_gaps as gaps
from app.orchestration.models import (
    VisualizationEvidenceAggregationRun,
    VisualizationEvidenceAlert,
    VisualizationGapReport,
    VisualizationTelemetryEvent,
)

EVIDENCE_MONITORING_VERSION = "evidence-monitoring-1.0"
MONITORING_ACTOR = "system:evidence-monitoring"
MAX_DRAFT_FINDINGS = 3

# Structurally invalid chart/data combinations are a distinct product-input
# problem, not evidence toward a missing V9 capability — excluded from V9-
# candidate evidence here without touching the existing manual gap report
# (visualization_gaps.aggregate_gaps), which still surfaces them for
# support/UX triage under their own "invalid_user_request" classification.
_STRUCTURALLY_INVALID_GAP_TYPE = gaps.VisualizationGapType.INCOMPATIBLE_REQUEST_DATA.value

RunStatus = Literal["running", "succeeded", "failed"]
TriggerSource = Literal["scheduled", "manual"]


class FailureCategory(str, Enum):
    """Closed set — the only vocabulary a failed run's failure_category can
    ever hold. No member, and no code path that sets one, carries free text."""
    TRANSIENT_INFRA_ERROR = "transient_infra_error"
    VALIDATION_ERROR = "validation_error"
    AUTHORIZATION_ERROR = "authorization_error"
    SCHEMA_ERROR = "schema_error"
    UNKNOWN_ERROR = "unknown_error"


_TRANSIENT_CATEGORIES = {FailureCategory.TRANSIENT_INFRA_ERROR.value}
_TRANSIENT_EXCEPTION_TYPES = (OperationalError, InterfaceError, TimeoutError, ConnectionError)
_SCHEMA_EXCEPTION_TYPES = (ProgrammingError, DataError, LookupError)


def is_transient_failure_category(category: str | None) -> bool:
    """The single decision point external retry logic (the scheduled job)
    should use — requirement 8/9: retry only transient failures, never
    validation/authorization/schema failures."""
    return category in _TRANSIENT_CATEGORIES


def _classify_failure(exc: BaseException) -> str:
    """Never returns or is passed str(exc) — see module docstring."""
    if isinstance(exc, _TRANSIENT_EXCEPTION_TYPES):
        return FailureCategory.TRANSIENT_INFRA_ERROR.value
    if isinstance(exc, ValueError):
        return FailureCategory.VALIDATION_ERROR.value
    if isinstance(exc, PermissionError):
        return FailureCategory.AUTHORIZATION_ERROR.value
    if isinstance(exc, _SCHEMA_EXCEPTION_TYPES):
        return FailureCategory.SCHEMA_ERROR.value
    return FailureCategory.UNKNOWN_ERROR.value


class MonitoringRunAlreadyActiveError(Exception):
    """Raised when a run is requested for a tenant that already has a
    status="running" row for the current monitoring_period. Backs both the
    backend idempotency requirement and the frontend's "prevent duplicate
    manual submissions while a run is active" requirement — the router
    translates this to HTTP 409."""


class MonitoringSnapshot(BaseModel):
    tenant_id: str
    evidence_period_start: date | None
    evidence_period_end: date | None
    evidence_version: str
    valid_event_count: int
    distinct_conversation_count: int
    distinct_actor_count: int
    overall_evidence_status: gaps.EvidenceStatus
    findings: list[gaps.GapReportRow]
    eligible_findings: list[gaps.GapReportRow]
    next_eligible_finding: gaps.GapReportRow | None
    diversity_gate_blocking_next: bool


class MonitoringRunResult(BaseModel):
    tenant_id: str
    started_at: datetime
    completed_at: datetime | None
    status: RunStatus
    trigger_source: TriggerSource
    monitoring_period: str
    evidence_version: str
    valid_event_count: int
    distinct_conversation_count: int
    distinct_actor_count: int
    eligible_finding_count: int
    draft_created: bool
    alert_created: bool
    deduplicated: bool
    report_id: str | None
    failure_category: str | None


class RunSummary(BaseModel):
    """Privacy-safe summary of one persisted run row — used for the "last
    scheduled run" / "last manual run" / "current run" admin-panel fields.
    Deliberately the same shape as MonitoringRunResult minus deduplicated
    (a transient, in-request-only concept, not something worth persisting
    meaning for on an already-completed row)."""
    tenant_id: str
    started_at: datetime
    completed_at: datetime | None
    status: RunStatus
    trigger_source: TriggerSource
    monitoring_period: str
    evidence_version: str
    valid_event_count: int
    draft_created: bool
    alert_created: bool
    report_id: str | None
    failure_category: str | None


class MonitoringStatusResponse(BaseModel):
    tenant_id: str
    valid_event_count: int
    distinct_conversation_count: int
    distinct_actor_count: int
    overall_evidence_status: gaps.EvidenceStatus
    monitoring_status: Literal[
        "collecting_evidence", "directional_signal", "ready_for_review",
        "awaiting_approval", "approved_findings_available",
    ]
    next_eligible_finding: gaps.GapReportRow | None
    events_to_next_threshold: int | None
    diversity_gate_blocking_next: bool
    last_aggregation_at: datetime | None
    last_report: gaps.GapReportPublic | None
    last_scheduled_run: RunSummary | None
    last_manual_run: RunSummary | None
    current_run: RunSummary | None
    next_scheduled_run_at: datetime | None


def _evidence_version(tenant_id: str, findings: list[gaps.GapReportRow], period_start: date | None, period_end: date | None) -> str:
    """Deterministic — the SAME underlying evidence always hashes to the
    SAME version, which is the entire mechanism the alert/draft dedup
    relies on. Only fields that could change a reviewer's conclusion feed
    the hash; the row ordering is fixed (aggregate_gaps already sorts by
    -sample_size then requested_capability) so this is stable across runs.
    Period bounds are included explicitly (requirement 7: idempotency keys
    off tenant_id + evidence_version + monitoring period) even though they
    already move in lockstep with the evidence content itself."""
    parts = [tenant_id, str(period_start), str(period_end)]
    for row in findings:
        parts.append("|".join(str(x) for x in (
            row.analytical_intent, row.requested_capability, row.requested_visualization_family,
            row.validated_data_shape, row.current_fallback, row.sample_size,
            row.distinct_conversations, row.distinct_actors, row.evidence_status.value,
        )))
    digest = hashlib.sha256("::".join(parts).encode()).hexdigest()[:16]
    return f"{EVIDENCE_MONITORING_VERSION}:{digest}"


async def _apply_fallback_rates(db: AsyncSession, tenant_id: str, rows: list[gaps.GapReportRow]) -> None:
    """Same cross-reference the manual gap-report endpoint already does
    against VisualizationTelemetryEvent (visualization_gaps_router.py) —
    duplicated rather than imported from the router so this module has no
    dependency on FastAPI request handling, and so V1-V8.3 router behavior
    stays byte-for-byte untouched."""
    if not rows:
        return
    stmt = select(VisualizationTelemetryEvent).where(
        VisualizationTelemetryEvent.tenant_id == tenant_id,
        VisualizationTelemetryEvent.environment == gaps.EnvironmentMarker.PRODUCTION.value,
    )
    telemetry_events = list((await db.execute(stmt)).scalars().all())
    for row in rows:
        relevant = [e for e in telemetry_events if e.original_chart_type == row.current_fallback]
        if not relevant:
            continue
        conversations = {e.conversation_id for e in relevant if e.conversation_id}
        switched = {e.conversation_id for e in relevant if e.event_name == "alternative_view_selected" and e.conversation_id}
        denominator = len(conversations)
        row.fallback_switch_rate = len(switched) / denominator if denominator else None
        row.fallback_retention_rate = 1.0 - row.fallback_switch_rate if row.fallback_switch_rate is not None else None


def _apply_diversity_gate(rows: list[gaps.GapReportRow]) -> None:
    """V8.4 requirement 5: more than one distinct conversation AND more
    than one distinct actor are both required before a finding can be
    eligible_for_review, however large its sample size. A row that clears
    the numeric threshold but not this gate is capped at directional_signal
    (never bumped down to insufficient_evidence — it still is a real,
    if not-yet-diverse-enough, directional signal)."""
    for row in rows:
        if row.evidence_status == gaps.EvidenceStatus.ELIGIBLE_FOR_REVIEW and not (
            row.distinct_conversations > 1 and row.distinct_actors > 1
        ):
            row.evidence_status = gaps.EvidenceStatus.DIRECTIONAL_SIGNAL
            row.recommended_action = "collect_more_production_evidence"


async def aggregate_production_evidence(db: AsyncSession, tenant_id: str) -> MonitoringSnapshot:
    """Read-only — never writes anything. Production environment is
    enforced via GapFilters' own default, which also structurally excludes
    every test/development/staging-tagged event (including synthetic or
    fixture events seeded under those environments in tests)."""
    events = await gaps.fetch_gap_events(db, gaps.GapFilters(tenant_id=tenant_id))
    seen_dedup_keys: set[str] = set()
    filtered = []
    for event in events:
        if event.gap_type == _STRUCTURALLY_INVALID_GAP_TYPE:
            continue
        if event.dedup_key in seen_dedup_keys:
            continue  # defensive — the DB unique constraint already prevents this at write time.
        seen_dedup_keys.add(event.dedup_key)
        filtered.append(event)

    summary = gaps.aggregate_gaps(filtered)
    _apply_diversity_gate(summary.rows)
    await _apply_fallback_rates(db, tenant_id, summary.rows)

    valid_events = [e for e in filtered if e.valid_evidence]
    distinct_conversations = len({e.conversation_id for e in valid_events if e.conversation_id})
    distinct_actors = len({e.actor_id for e in valid_events if e.actor_id})
    period_start = min((e.created_at.date() for e in valid_events), default=None)
    period_end = max((e.created_at.date() for e in valid_events), default=None)

    eligible = [r for r in summary.rows if r.evidence_status == gaps.EvidenceStatus.ELIGIBLE_FOR_REVIEW]
    not_yet_eligible = [r for r in summary.rows if r.evidence_status != gaps.EvidenceStatus.ELIGIBLE_FOR_REVIEW]
    not_yet_eligible.sort(key=lambda r: -r.sample_size)
    next_finding = not_yet_eligible[0] if not_yet_eligible else None
    diversity_blocking = bool(
        next_finding is not None
        and next_finding.sample_size >= 100
        and not (next_finding.distinct_conversations > 1 and next_finding.distinct_actors > 1)
    )

    return MonitoringSnapshot(
        tenant_id=tenant_id,
        evidence_period_start=period_start,
        evidence_period_end=period_end,
        evidence_version=_evidence_version(tenant_id, summary.rows, period_start, period_end),
        valid_event_count=len(valid_events),
        distinct_conversation_count=distinct_conversations,
        distinct_actor_count=distinct_actors,
        overall_evidence_status=gaps.evidence_status(len(valid_events)),
        findings=summary.rows,
        eligible_findings=eligible,
        next_eligible_finding=next_finding,
        diversity_gate_blocking_next=diversity_blocking,
    )


def _draft_artifact(snapshot: MonitoringSnapshot, findings: list[gaps.GapReportRow]) -> dict:
    period = {
        "from": snapshot.evidence_period_start.isoformat() if snapshot.evidence_period_start else None,
        "to": snapshot.evidence_period_end.isoformat() if snapshot.evidence_period_end else None,
    }
    return {
        "evidence_period": period,
        "evidence_version": snapshot.evidence_version,
        "environment": "production",
        "findings": [f.model_dump(mode="json") for f in findings],
        "current_fallback": [f.current_fallback for f in findings],
        "recommended_issue_classification": [f.recommended_issue_classification for f in findings],
        "recommended_action": [f.recommended_action for f in findings],
        "approved_findings": [],
        "selection_activation": "none",
        "status": "draft",
    }


def _result_from_row(row: VisualizationEvidenceAggregationRun, *, deduplicated: bool) -> MonitoringRunResult:
    # draft_created/alert_created are always call-scoped ("did THIS
    # invocation create a new one"), never row-scoped — a deduplicated call
    # (whether short-circuited at the run level via monitoring_period, or
    # at the content level via evidence_version) did neither, even when the
    # PERSISTED row it is reporting on shows a draft/alert an earlier,
    # distinct call actually created.
    draft_created = row.draft_created and not deduplicated
    alert_created = row.alert_created and not deduplicated
    return MonitoringRunResult(
        tenant_id=row.tenant_id, started_at=row.started_at, completed_at=row.completed_at, status=row.status,
        trigger_source=row.trigger_source, monitoring_period=row.monitoring_period, evidence_version=row.evidence_version,
        valid_event_count=row.valid_event_count, distinct_conversation_count=row.distinct_conversation_count,
        distinct_actor_count=row.distinct_actor_count, eligible_finding_count=row.eligible_finding_count,
        draft_created=draft_created, alert_created=alert_created, deduplicated=deduplicated,
        report_id=row.created_report_id, failure_category=row.failure_category,
    )


def _summary_from_row(row: VisualizationEvidenceAggregationRun | None) -> RunSummary | None:
    if row is None:
        return None
    return RunSummary(
        tenant_id=row.tenant_id, started_at=row.started_at, completed_at=row.completed_at, status=row.status,
        trigger_source=row.trigger_source, monitoring_period=row.monitoring_period, evidence_version=row.evidence_version,
        valid_event_count=row.valid_event_count, draft_created=row.draft_created, alert_created=row.alert_created,
        report_id=row.created_report_id, failure_category=row.failure_category,
    )


async def run_evidence_monitoring(
    db: AsyncSession, tenant_id: str, *, trigger_source: TriggerSource = "manual", triggered_by: str = MONITORING_ACTOR,
) -> MonitoringRunResult:
    """The scheduled-or-explicitly-invokable service itself (requirement 1).
    No in-process scheduler loop exists or is started by this function —
    every invocation is a single, self-contained, retry-safe unit of work
    triggered externally (scripts/run_evidence_monitoring_job.py under
    Railway Cron, or an admin's manual "Run evidence monitoring" click).

    Idempotent at two levels:
      * RUN level — (tenant_id, monitoring_period): a second call for a
        tenant that already succeeded today returns that prior outcome
        without re-aggregating; a call that finds one still "running"
        raises MonitoringRunAlreadyActiveError rather than racing it.
      * CONTENT level — (tenant_id, evidence_version), via
        VisualizationEvidenceAlert — preserved unchanged from V8.4.
    """
    started_at = datetime.now(timezone.utc)
    monitoring_period = started_at.date().isoformat()

    existing_run = await db.scalar(
        select(VisualizationEvidenceAggregationRun)
        .where(
            VisualizationEvidenceAggregationRun.tenant_id == tenant_id,
            VisualizationEvidenceAggregationRun.monitoring_period == monitoring_period,
        )
        .order_by(VisualizationEvidenceAggregationRun.started_at.desc())
        .limit(1)
    )
    if existing_run is not None and existing_run.status == "running":
        raise MonitoringRunAlreadyActiveError(tenant_id)
    if existing_run is not None and existing_run.status == "succeeded":
        return _result_from_row(existing_run, deduplicated=True)
    # No run yet today, or today's prior attempt failed — proceed with a
    # fresh attempt (this IS the retry path for a failed run).

    run_row = VisualizationEvidenceAggregationRun(
        tenant_id=tenant_id, started_at=started_at, monitoring_period=monitoring_period,
        trigger_source=trigger_source, status="running", evidence_version="", valid_event_count=0,
        distinct_conversation_count=0, distinct_actor_count=0, eligible_finding_count=0,
        created_report_id=None, draft_created=False, alert_created=False, failure_category=None,
        triggered_by=triggered_by,
    )
    db.add(run_row)
    await db.commit()
    await db.refresh(run_row)

    try:
        snapshot = await aggregate_production_evidence(db, tenant_id)
        eligible = snapshot.eligible_findings
        draft_findings = eligible[:MAX_DRAFT_FINDINGS]

        report_id: str | None = None
        draft_created = False
        alert_created = False
        deduplicated = False

        if eligible:
            existing_alert = await db.scalar(
                select(VisualizationEvidenceAlert).where(
                    VisualizationEvidenceAlert.tenant_id == tenant_id,
                    VisualizationEvidenceAlert.evidence_version == snapshot.evidence_version,
                )
            )
            if existing_alert is not None:
                report_id = existing_alert.report_id
                deduplicated = True
            else:
                report = VisualizationGapReport(
                    tenant_id=tenant_id,
                    period_start=snapshot.evidence_period_start,
                    period_end=snapshot.evidence_period_end,
                    evidence_version=snapshot.evidence_version,
                    approved_findings=[],
                    artifact=_draft_artifact(snapshot, draft_findings),
                    status="draft",
                    created_by=MONITORING_ACTOR,
                )
                db.add(report)
                try:
                    await db.flush()
                    db.add(VisualizationEvidenceAlert(
                        tenant_id=tenant_id, evidence_version=snapshot.evidence_version, report_id=report.id,
                    ))
                    await db.commit()
                    await db.refresh(report)
                    report_id = report.id
                    draft_created = True
                    alert_created = True
                except IntegrityError:
                    # Lost a race against a concurrent run over the same
                    # evidence version — roll back this attempt (report and
                    # alert together, same transaction) and defer to
                    # whichever run actually won.
                    await db.rollback()
                    existing_alert = await db.scalar(
                        select(VisualizationEvidenceAlert).where(
                            VisualizationEvidenceAlert.tenant_id == tenant_id,
                            VisualizationEvidenceAlert.evidence_version == snapshot.evidence_version,
                        )
                    )
                    report_id = existing_alert.report_id if existing_alert else None
                    deduplicated = True

        run_row.status = "succeeded"
        run_row.completed_at = datetime.now(timezone.utc)
        run_row.evidence_version = snapshot.evidence_version
        run_row.valid_event_count = snapshot.valid_event_count
        run_row.distinct_conversation_count = snapshot.distinct_conversation_count
        run_row.distinct_actor_count = snapshot.distinct_actor_count
        run_row.eligible_finding_count = len(eligible)
        run_row.created_report_id = report_id
        run_row.draft_created = draft_created
        run_row.alert_created = alert_created
        await db.commit()
        await db.refresh(run_row)

        return _result_from_row(run_row, deduplicated=deduplicated)
    except Exception as exc:
        await db.rollback()
        category = _classify_failure(exc)
        # Mutate the same still-attached (though now expired) instance
        # rather than re-fetching by id — rollback() expires attributes but
        # does not detach a row that was already committed once (our
        # initial "running" insert above), so a plain attribute set here
        # needs no additional read.
        run_row.status = "failed"
        run_row.completed_at = datetime.now(timezone.utc)
        run_row.failure_category = category
        await db.commit()
        await db.refresh(run_row)
        return _result_from_row(run_row, deduplicated=False)


def _next_scheduled_run_at(now: datetime) -> datetime:
    """Purely a display computation from the configured daily schedule
    (EVIDENCE_MONITORING_SCHEDULE_HOUR_UTC/MINUTE_UTC) — does not itself
    schedule anything; the actual trigger is Railway's Cron Schedule
    setting on the scheduled-monitoring service, kept in sync by hand."""
    settings = get_settings()
    scheduled_time = time(hour=settings.EVIDENCE_MONITORING_SCHEDULE_HOUR_UTC, minute=settings.EVIDENCE_MONITORING_SCHEDULE_MINUTE_UTC)
    candidate = datetime.combine(now.date(), scheduled_time, tzinfo=timezone.utc)
    return candidate if candidate > now else candidate + timedelta(days=1)


async def get_monitoring_status(db: AsyncSession, tenant_id: str) -> MonitoringStatusResponse:
    """Admin status-panel backing function (requirement 14, extended by
    V8.5's requirement 2). Read-only: current counts/progress are computed
    live from evidence; every run-history field reflects persisted
    VisualizationEvidenceAggregationRun rows, never triggering a new run."""
    snapshot = await aggregate_production_evidence(db, tenant_id)

    last_run = await db.scalar(
        select(VisualizationEvidenceAggregationRun)
        .where(VisualizationEvidenceAggregationRun.tenant_id == tenant_id)
        .order_by(VisualizationEvidenceAggregationRun.started_at.desc())
        .limit(1)
    )
    last_scheduled_run = await db.scalar(
        select(VisualizationEvidenceAggregationRun)
        .where(
            VisualizationEvidenceAggregationRun.tenant_id == tenant_id,
            VisualizationEvidenceAggregationRun.trigger_source == "scheduled",
            VisualizationEvidenceAggregationRun.status != "running",
        )
        .order_by(VisualizationEvidenceAggregationRun.started_at.desc())
        .limit(1)
    )
    last_manual_run = await db.scalar(
        select(VisualizationEvidenceAggregationRun)
        .where(
            VisualizationEvidenceAggregationRun.tenant_id == tenant_id,
            VisualizationEvidenceAggregationRun.trigger_source == "manual",
            VisualizationEvidenceAggregationRun.status != "running",
        )
        .order_by(VisualizationEvidenceAggregationRun.started_at.desc())
        .limit(1)
    )
    current_run = await db.scalar(
        select(VisualizationEvidenceAggregationRun)
        .where(
            VisualizationEvidenceAggregationRun.tenant_id == tenant_id,
            VisualizationEvidenceAggregationRun.status == "running",
        )
        .order_by(VisualizationEvidenceAggregationRun.started_at.desc())
        .limit(1)
    )
    last_report = await db.scalar(
        select(VisualizationGapReport)
        .where(VisualizationGapReport.tenant_id == tenant_id, VisualizationGapReport.created_by == MONITORING_ACTOR)
        .order_by(VisualizationGapReport.created_at.desc())
        .limit(1)
    )

    monitoring_status: Literal[
        "collecting_evidence", "directional_signal", "ready_for_review",
        "awaiting_approval", "approved_findings_available",
    ]
    if last_report is not None and last_report.status == "approved":
        monitoring_status = "approved_findings_available"
    elif last_report is not None and last_report.status == "under_review":
        monitoring_status = "awaiting_approval"
    elif last_report is not None and last_report.status == "draft":
        monitoring_status = "ready_for_review"
    elif snapshot.overall_evidence_status == gaps.EvidenceStatus.DIRECTIONAL_SIGNAL:
        monitoring_status = "directional_signal"
    else:
        monitoring_status = "collecting_evidence"

    events_to_next_threshold: int | None = None
    if snapshot.next_eligible_finding is not None and not snapshot.diversity_gate_blocking_next:
        boundary = 30 if snapshot.next_eligible_finding.sample_size < 30 else 100
        events_to_next_threshold = max(0, boundary - snapshot.next_eligible_finding.sample_size)

    return MonitoringStatusResponse(
        tenant_id=tenant_id,
        valid_event_count=snapshot.valid_event_count,
        distinct_conversation_count=snapshot.distinct_conversation_count,
        distinct_actor_count=snapshot.distinct_actor_count,
        overall_evidence_status=snapshot.overall_evidence_status,
        monitoring_status=monitoring_status,
        next_eligible_finding=snapshot.next_eligible_finding,
        events_to_next_threshold=events_to_next_threshold,
        diversity_gate_blocking_next=snapshot.diversity_gate_blocking_next,
        last_aggregation_at=last_run.started_at if last_run else None,
        last_report=gaps.GapReportPublic.model_validate(last_report) if last_report else None,
        last_scheduled_run=_summary_from_row(last_scheduled_run),
        last_manual_run=_summary_from_row(last_manual_run),
        current_run=_summary_from_row(current_run),
        next_scheduled_run_at=_next_scheduled_run_at(datetime.now(timezone.utc)),
    )
