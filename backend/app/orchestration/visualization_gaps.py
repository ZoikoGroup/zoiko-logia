"""V8.2 privacy-safe visualization-gap evidence and governed reports."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration.models import VisualizationGapEvent, VisualizationGapReport

GAP_SCHEMA_VERSION = "1.0"
EVIDENCE_VERSION = "gap-evidence-1.0"


class VisualizationGapType(str, Enum):
    UNSUPPORTED_PRODUCT_CAPABILITY = "unsupported_product_capability"
    INCOMPATIBLE_REQUEST_DATA = "incompatible_request_data_combination"
    INSUFFICIENT_EXTRACTED_DATA = "insufficient_extracted_data"
    SELECTION_RULE_FAILURE = "selection_rule_failure"
    RENDERER_FAILURE = "renderer_failure"
    ACCESSIBILITY_EXPORT_LIMITATION = "accessibility_export_limitation"


class RequestedChartType(str, Enum):
    BAR="bar"; LINE="line"; AREA="area"; DONUT="donut"; GROUPED_BAR="grouped_bar"; STACKED_BAR="stacked_bar"
    PERCENTAGE_STACKED_BAR="percentage_stacked_bar"; DIVERGING_BAR="diverging_bar"; RADAR="radar"; DUMBBELL="dumbbell"
    LOLLIPOP="lollipop"; SCATTER="scatter"; BUBBLE="bubble"; HEATMAP="heatmap"; CORRELATION_MATRIX="correlation_matrix"
    HISTOGRAM="histogram"; BOX_PLOT="box_plot"; FUNNEL="funnel"; SLOPE="slope"; BULLET="bullet"; WATERFALL="waterfall"
    COMPOSITION_BAR="composition_bar"; DUAL_AXIS="dual_axis"; TREEMAP="treemap"; SANKEY="sankey"; GAUGE="gauge"; VIOLIN="violin"


class RequestedVisualizationFamily(str, Enum):
    COMPARISON="comparison"; TREND="trend"; COMPOSITION="composition"; DISTRIBUTION="distribution"
    CORRELATION="correlation"; FLOW="flow"; FINANCIAL_MOVEMENT="financial_movement"; TARGET="target"; UNKNOWN="unknown"


class DataShapeClass(str, Enum):
    CATEGORICAL_SINGLE_MEASURE="categorical_single_measure"; CATEGORICAL_MULTI_MEASURE="categorical_multi_measure"
    TEMPORAL_SINGLE_SERIES="temporal_single_series"; TEMPORAL_MULTI_SERIES="temporal_multi_series"
    PART_TO_WHOLE="part_to_whole"; PAIRED_NUMERIC="paired_numeric"; MATRIX="matrix"; DISTRIBUTION="distribution"
    FLOW="flow"; SIGNED_STEPS="signed_steps"; REGISTRY_VALIDATED="registry_validated"; INSUFFICIENT="insufficient"


class FallbackOutputType(str, Enum):
    CHART="chart"; TABLE="table"; TEXT="text"


class EvidenceStatus(str, Enum):
    INSUFFICIENT_EVIDENCE="insufficient_evidence"; DIRECTIONAL_SIGNAL="directional_signal"; ELIGIBLE_FOR_REVIEW="eligible_for_review"


class EnvironmentMarker(str, Enum):
    PRODUCTION="production"; STAGING="staging"; DEVELOPMENT="development"; TEST="test"


def evidence_status(sample_size: int) -> EvidenceStatus:
    return EvidenceStatus.INSUFFICIENT_EVIDENCE if sample_size < 30 else EvidenceStatus.DIRECTIONAL_SIGNAL if sample_size < 100 else EvidenceStatus.ELIGIBLE_FOR_REVIEW


def classify_data_shape(profile) -> DataShapeClass:
    if profile.contains_flow: return DataShapeClass.FLOW
    if profile.contains_matrix_shape: return DataShapeClass.MATRIX
    if profile.contains_distribution: return DataShapeClass.DISTRIBUTION
    if profile.contains_signed_deltas and profile.contains_ordered_steps: return DataShapeClass.SIGNED_STEPS
    if profile.contains_time: return DataShapeClass.TEMPORAL_MULTI_SERIES if profile.measure_count > 1 else DataShapeClass.TEMPORAL_SINGLE_SERIES
    if profile.part_to_whole_valid: return DataShapeClass.PART_TO_WHOLE
    if profile.contains_paired_measures: return DataShapeClass.PAIRED_NUMERIC
    if profile.category_count and profile.measure_count > 1: return DataShapeClass.CATEGORICAL_MULTI_MEASURE
    if profile.category_count and profile.measure_count == 1: return DataShapeClass.CATEGORICAL_SINGLE_MEASURE
    return DataShapeClass.INSUFFICIENT


_FAMILIES = {
    "line":"trend", "area":"trend", "donut":"composition", "composition_bar":"composition", "stacked_bar":"composition",
    "percentage_stacked_bar":"composition", "histogram":"distribution", "box_plot":"distribution", "violin":"distribution",
    "scatter":"correlation", "bubble":"correlation", "heatmap":"correlation", "correlation_matrix":"correlation",
    "funnel":"flow", "sankey":"flow", "waterfall":"financial_movement", "gauge":"target", "bullet":"target", "treemap":"composition",
}


def requested_family(chart_type: str) -> RequestedVisualizationFamily:
    return RequestedVisualizationFamily(_FAMILIES.get(chart_type, "comparison" if chart_type != "unknown" else "unknown"))


def shape_valid_for_requested_chart(chart_type: str, shape: DataShapeClass) -> bool:
    if shape == DataShapeClass.REGISTRY_VALIDATED: return True
    allowed = {
        "treemap": {DataShapeClass.PART_TO_WHOLE}, "sankey": {DataShapeClass.FLOW}, "gauge": {DataShapeClass.CATEGORICAL_SINGLE_MEASURE},
        "violin": {DataShapeClass.DISTRIBUTION}, "line": {DataShapeClass.TEMPORAL_SINGLE_SERIES, DataShapeClass.TEMPORAL_MULTI_SERIES},
        "area": {DataShapeClass.TEMPORAL_SINGLE_SERIES, DataShapeClass.TEMPORAL_MULTI_SERIES}, "donut": {DataShapeClass.PART_TO_WHOLE},
        "scatter": {DataShapeClass.PAIRED_NUMERIC}, "bubble": {DataShapeClass.PAIRED_NUMERIC}, "heatmap": {DataShapeClass.MATRIX},
        "correlation_matrix": {DataShapeClass.MATRIX}, "histogram": {DataShapeClass.DISTRIBUTION}, "box_plot": {DataShapeClass.DISTRIBUTION},
        "waterfall": {DataShapeClass.SIGNED_STEPS}, "funnel": {DataShapeClass.FLOW},
    }
    return shape in allowed.get(chart_type, set(DataShapeClass) - {DataShapeClass.INSUFFICIENT})


class GapFilters(BaseModel):
    tenant_id: str
    date_from: date | None = None; date_to: date | None = None
    environment: EnvironmentMarker = EnvironmentMarker.PRODUCTION
    analytical_intent: str | None = None; requested_chart_type: RequestedChartType | None = None
    requested_visualization_family: RequestedVisualizationFamily | None = None; data_shape_class: DataShapeClass | None = None
    evidence_status_filter: EvidenceStatus | None = None


class GapReportRow(BaseModel):
    analytical_intent: str | None
    requested_capability: str
    requested_visualization_family: str
    validated_data_shape: str
    current_fallback: str
    sample_size: int
    distinct_conversations: int
    distinct_actors: int
    fallback_retention_rate: float | None = None
    fallback_switch_rate: float | None = None
    render_failure_rate: float
    evidence_status: EvidenceStatus
    recommended_issue_classification: Literal["missing_chart_type","selection_rule_problem","data_extraction_problem","renderer_limitation","accessibility_gap","export_gap","invalid_user_request","insufficient_evidence"]
    recommended_action: str


class GapSummary(BaseModel):
    total_visualization_requests: int
    total_fallback_events: int
    gap_rate: float
    rows: list[GapReportRow]
    environment: EnvironmentMarker


async def record_gap_event(db: AsyncSession, *, tenant_id: str, actor_id: str | None, conversation_id: str | None, analytical_intent: str | None,
                           requested_chart_type: str, gap_type: VisualizationGapType, data_shape_class: DataShapeClass,
                           fallback_chart_type: str | None, fallback_output_type: FallbackOutputType, registry_candidate_count: int,
                           ranking_version: str, environment: str) -> None:
    marker = EnvironmentMarker(environment if environment in EnvironmentMarker._value2member_map_ else "development")
    dedup = hashlib.sha256(f"{tenant_id}:{actor_id}:{conversation_id}:{requested_chart_type}:{gap_type.value}:{data_shape_class.value}".encode()).hexdigest()
    row = VisualizationGapEvent(
        dedup_key=dedup, tenant_id=tenant_id, actor_id=actor_id, conversation_id=conversation_id, analytical_intent=analytical_intent,
        requested_chart_type=requested_chart_type, requested_visualization_family=requested_family(requested_chart_type).value,
        gap_type=gap_type.value, data_shape_class=data_shape_class.value, fallback_chart_type=fallback_chart_type,
        fallback_output_type=fallback_output_type.value, registry_candidate_count=registry_candidate_count, ranking_version=ranking_version,
        schema_version=GAP_SCHEMA_VERSION, environment=marker.value, valid_evidence=shape_valid_for_requested_chart(requested_chart_type, data_shape_class),
    )
    try:
        db.add(row); await db.commit()
    except Exception:
        await db.rollback()  # duplicate/idempotent or telemetry outage: never break answers


async def fetch_gap_events(db: AsyncSession, filters: GapFilters) -> list[VisualizationGapEvent]:
    stmt = select(VisualizationGapEvent).where(VisualizationGapEvent.tenant_id == filters.tenant_id, VisualizationGapEvent.environment == filters.environment.value)
    if filters.date_from: stmt = stmt.where(VisualizationGapEvent.created_at >= datetime.combine(filters.date_from, datetime.min.time(), tzinfo=timezone.utc))
    if filters.date_to: stmt = stmt.where(VisualizationGapEvent.created_at < datetime.combine(filters.date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    for field in ("analytical_intent", "requested_chart_type", "requested_visualization_family", "data_shape_class"):
        value = getattr(filters, field); value = value.value if isinstance(value, Enum) else value
        if value is not None: stmt = stmt.where(getattr(VisualizationGapEvent, field) == value)
    return list((await db.execute(stmt)).scalars().all())


def aggregate_gaps(events: list[VisualizationGapEvent], total_visualization_requests: int | None = None) -> GapSummary:
    groups: dict[tuple, list[VisualizationGapEvent]] = {}
    for event in events:
        if event.valid_evidence:
            groups.setdefault((event.analytical_intent, event.requested_chart_type, event.requested_visualization_family, event.data_shape_class, event.fallback_chart_type or event.fallback_output_type, event.gap_type), []).append(event)
    rows = []
    for key, items in groups.items():
        intent, requested, family, shape, fallback, gap_type = key; n = len(items); status = evidence_status(n)
        issue = "insufficient_evidence" if status == EvidenceStatus.INSUFFICIENT_EVIDENCE else {
            "unsupported_product_capability":"missing_chart_type", "selection_rule_failure":"selection_rule_problem", "insufficient_extracted_data":"data_extraction_problem",
            "renderer_failure":"renderer_limitation", "accessibility_export_limitation":"accessibility_gap", "incompatible_request_data_combination":"invalid_user_request",
        }[gap_type]
        action = "collect_more_production_evidence" if status != EvidenceStatus.ELIGIBLE_FOR_REVIEW else {
            "unsupported_product_capability":"human_review_for_v9_candidate", "selection_rule_failure":"review_selection_rules",
            "insufficient_extracted_data":"improve_data_extraction", "renderer_failure":"fix_renderer",
            "accessibility_export_limitation":"remediate_accessibility_or_export", "incompatible_request_data_combination":"clarify_invalid_request",
        }[gap_type]
        rows.append(GapReportRow(analytical_intent=intent, requested_capability=requested, requested_visualization_family=family,
            validated_data_shape=shape, current_fallback=fallback, sample_size=n,
            distinct_conversations=len({x.conversation_id for x in items if x.conversation_id}), distinct_actors=len({x.actor_id for x in items if x.actor_id}),
            render_failure_rate=sum(x.gap_type == "renderer_failure" for x in items)/n, evidence_status=status, recommended_issue_classification=issue,
            recommended_action=action))
    rows.sort(key=lambda x: (-x.sample_size, x.requested_capability))
    fallbacks = len(events); total = total_visualization_requests if total_visualization_requests is not None else len(events)
    environment = EnvironmentMarker(events[0].environment) if events else EnvironmentMarker.PRODUCTION
    return GapSummary(total_visualization_requests=total, total_fallback_events=fallbacks, gap_rate=min(1.0, fallbacks/total) if total else 0.0, rows=rows, environment=environment)


class GapReportCreate(BaseModel):
    period_start: date; period_end: date; approved_findings: list[str] = Field(default_factory=list, max_length=3)


class GapReportPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str; tenant_id: str; period_start: date; period_end: date; evidence_version: str; approved_findings: list[str]; artifact: dict
    status: Literal["draft","under_review","approved","rejected"]; created_by: str; approved_by: str | None; approved_at: datetime | None


async def create_report(db: AsyncSession, tenant_id: str, actor_id: str, payload: GapReportCreate) -> VisualizationGapReport:
    if payload.period_start > payload.period_end: raise ValueError("period_start must not be after period_end")
    row = VisualizationGapReport(tenant_id=tenant_id, period_start=payload.period_start, period_end=payload.period_end,
        evidence_version=EVIDENCE_VERSION, approved_findings=payload.approved_findings, artifact={}, status="draft", created_by=actor_id)
    db.add(row); await db.commit(); await db.refresh(row); return row


async def transition_report(db: AsyncSession, tenant_id: str, report_id: str, actor_id: str, status: str) -> VisualizationGapReport | None:
    row = await db.scalar(select(VisualizationGapReport).where(VisualizationGapReport.id == report_id, VisualizationGapReport.tenant_id == tenant_id))
    if row is None: return None
    allowed = {"draft":{"under_review"}, "under_review":{"approved","rejected"}, "approved":set(), "rejected":set()}
    if status not in allowed[row.status]: raise ValueError(f"cannot transition {row.status} to {status}")
    if status == "approved" and actor_id == row.created_by: raise PermissionError("report creator cannot approve their own report")
    row.status = status
    if status == "approved":
        evidence = await fetch_gap_events(db, GapFilters(tenant_id=tenant_id, date_from=row.period_start, date_to=row.period_end))
        summary = aggregate_gaps(evidence)
        row.artifact = {
            "report_id": row.id, "report_period": {"from": row.period_start.isoformat(), "to": row.period_end.isoformat()},
            "aggregated_evidence_version": row.evidence_version, "environment": "production",
            "approved_findings": row.approved_findings, "findings": [item.model_dump(mode="json") for item in summary.rows],
            "selection_activation": "none",
        }
        row.approved_by = actor_id; row.approved_at = datetime.now(timezone.utc)
    await db.commit(); await db.refresh(row); return row
