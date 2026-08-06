"""Dynamic Visualization Selection v6 — privacy-safe recommendation-quality
reporting over app.orchestration.models.VisualizationTelemetryEvent.

Privacy boundary: every aggregation here reads ONLY the allow-listed columns
that table already has (see VisualizationTelemetryEvent's own docstring) —
event_name, tenant/actor/conversation/query identifiers, analytical_intent,
original/active chart type, chart_family, renderer, selection_source,
ranking_version, alternative_count, created_at. There is no query text,
answer text, chart value, category label, source-document data, prompt
content, or error message/stack anywhere in that table, so there is nothing
for this module to accidentally aggregate or return that would leak any of
it — the boundary is structural (see test_record_visualization_event_
signature_cannot_carry_sensitive_content in test_visualization_telemetry.py
for the equivalent guarantee on the write side).

Correlation model: telemetry rows are per-CHART events, but the schema has
no chart_id (only query_id) — a query with more than one chart cannot be
perfectly disambiguated. Every metric below is computed by grouping events
under their query_id and treating the EARLIEST "visualization_selected" row
for that query_id as the representative chart instance (its own
analytical_intent/chart_family/original_chart_type/... values become the
group key). This is a deliberate, documented approximation: the overwhelming
majority of Ask Kriton answers carry at most one chart, and query_id-level
correlation is what the current schema supports without a larger, unrequested
schema change. Every rate is computed over DISTINCT query_ids (a set, not a
raw event count), so duplicate telemetry rows for the same query_id (e.g. a
retried client POST) can never inflate a metric — a query_id is either in a
metric's set or it isn't.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration.models import VisualizationTelemetryEvent
from app.orchestration.presentation_dataprofile import WEIGHT_BOUNDS, current_weights
from app.orchestration.visualization_analytics_schemas import (
    ChartTypePerformanceResponse,
    ChartTypePerformanceRow,
    EvidenceStatus,
    RateMetric,
    RecommendationQualityRow,
    RecommendationQualitySummaryResponse,
    ReplacementMatrixCell,
    ReplacementMatrixResponse,
    WeightAdjustmentProposal,
)

ALLOWED_GROUP_BY: tuple[str, ...] = (
    "analytical_intent", "chart_family", "original_chart_type", "active_chart_type",
    "renderer", "selection_source", "ranking_version", "day", "week",
)
_EQUALITY_FILTER_FIELDS: tuple[str, ...] = (
    "analytical_intent", "chart_family", "original_chart_type", "active_chart_type",
    "renderer", "selection_source", "ranking_version",
)

# ── minimum-sample classification ────────────────────────────────────────
# Fixed, documented thresholds — no statistical test, just a floor below
# which a rate is noise and a floor above which it's worth a human's time.
_INSUFFICIENT_EVIDENCE_MAX_SAMPLE = 9     # sample_size 0-9
_DIRECTIONAL_SIGNAL_MAX_SAMPLE = 49       # sample_size 10-49
# sample_size >= 50 -> eligible_for_review

# ── "unusually high" thresholds for chart-type performance flags ────────
_UNUSUALLY_HIGH_SWITCH_RATE = 0.35
_UNUSUALLY_HIGH_FALLBACK_RATE = 0.15
_UNUSUALLY_HIGH_RENDER_FAILURE_RATE = 0.02

# ── recommendation-analysis (weight proposal) tuning ─────────────────────
# review_required is pinned True at the schema level (see
# WeightAdjustmentProposal) — these thresholds only decide whether a
# proposal is drafted at all, never whether one takes effect.
_PROPOSAL_MIN_SWITCH_RATE = _UNUSUALLY_HIGH_SWITCH_RATE
_PROPOSAL_DIMENSION = "analytical_intent_fit"
_PROPOSAL_WEIGHT_DELTA = 0.02


class InvalidDateRangeError(ValueError):
    pass


class InvalidGroupByError(ValueError):
    pass


@dataclass(frozen=True)
class AnalyticsFilters:
    """Every field is a validated, closed-vocabulary equality filter or a
    validated date bound — never free text, never interpolated into SQL.
    tenant_id has no default: every call site must supply one explicitly,
    so tenant isolation can never be silently skipped."""
    tenant_id: str
    date_from: date | None = None
    date_to: date | None = None
    analytical_intent: str | None = None
    chart_family: str | None = None
    original_chart_type: str | None = None
    active_chart_type: str | None = None
    renderer: str | None = None
    selection_source: str | None = None
    ranking_version: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required for every aggregation query")
        if self.date_from is not None and self.date_to is not None and self.date_from > self.date_to:
            raise InvalidDateRangeError("date_from must not be after date_to")


def validate_group_by(group_by: list[str] | None) -> tuple[str, ...]:
    if not group_by:
        return ()
    invalid = [dimension for dimension in group_by if dimension not in ALLOWED_GROUP_BY]
    if invalid:
        raise InvalidGroupByError(f"unsupported group_by dimension(s): {invalid}")
    return tuple(group_by)


def evidence_status(sample_size: int) -> EvidenceStatus:
    if sample_size <= _INSUFFICIENT_EVIDENCE_MAX_SAMPLE:
        return EvidenceStatus.INSUFFICIENT_EVIDENCE
    if sample_size <= _DIRECTIONAL_SIGNAL_MAX_SAMPLE:
        return EvidenceStatus.DIRECTIONAL_SIGNAL
    return EvidenceStatus.ELIGIBLE_FOR_REVIEW


def rate_metric(numerator: int, denominator: int) -> RateMetric:
    rate = min(1.0, numerator / denominator) if denominator else 0.0
    return RateMetric(
        rate=rate, numerator=numerator, sample_size=denominator,
        evidence_status=evidence_status(denominator),
    )


async def fetch_events(db: AsyncSession, filters: AnalyticsFilters) -> list[VisualizationTelemetryEvent]:
    """The one place any of this module talks to the database — every
    caller (summary/matrix/performance/proposal) goes through this, so
    tenant isolation and date-range filtering are enforced exactly once."""
    stmt = select(VisualizationTelemetryEvent).where(VisualizationTelemetryEvent.tenant_id == filters.tenant_id)
    if filters.date_from is not None:
        inclusive_start = datetime.combine(filters.date_from, datetime.min.time(), tzinfo=timezone.utc)
        stmt = stmt.where(VisualizationTelemetryEvent.created_at >= inclusive_start)
    if filters.date_to is not None:
        exclusive_end = datetime.combine(filters.date_to, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
        stmt = stmt.where(VisualizationTelemetryEvent.created_at < exclusive_end)
    for field_name in _EQUALITY_FILTER_FIELDS:
        value = getattr(filters, field_name)
        if value is not None:
            stmt = stmt.where(getattr(VisualizationTelemetryEvent, field_name) == value)
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _group_key_value(event: VisualizationTelemetryEvent, dimension: str) -> str:
    if dimension == "day":
        return event.created_at.date().isoformat()
    if dimension == "week":
        iso_year, iso_week, _ = event.created_at.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    return getattr(event, dimension, None) or "unspecified"


def by_query_id(events: list[VisualizationTelemetryEvent]) -> dict[str, list[VisualizationTelemetryEvent]]:
    grouped: dict[str, list[VisualizationTelemetryEvent]] = {}
    for event in events:
        if event.query_id:
            grouped.setdefault(event.query_id, []).append(event)
    return grouped


def representative_selection(query_events: list[VisualizationTelemetryEvent]) -> VisualizationTelemetryEvent | None:
    """The earliest visualization_selected row for a query_id — see module
    docstring for why this is the chart instance every other event for that
    query_id is attributed to."""
    selected = sorted(
        (e for e in query_events if e.event_name == "visualization_selected"),
        key=lambda e: e.created_at,
    )
    return selected[0] if selected else None


def final_active_type(representative: VisualizationTelemetryEvent, query_events: list[VisualizationTelemetryEvent]) -> str | None:
    switches = sorted(
        (e for e in query_events if e.event_name == "alternative_view_selected"),
        key=lambda e: e.created_at,
    )
    return switches[-1].active_chart_type if switches else representative.active_chart_type


# ── recommendation-quality summary ───────────────────────────────────────

def compute_recommendation_quality_summary(
    events: list[VisualizationTelemetryEvent], group_by: tuple[str, ...] = (),
) -> RecommendationQualitySummaryResponse:
    buckets: dict[tuple[str, ...], dict[str, set[str]]] = {}
    for query_id, query_events in by_query_id(events).items():
        representative = representative_selection(query_events)
        if representative is None:
            continue
        key = tuple(_group_key_value(representative, dimension) for dimension in group_by)
        bucket = buckets.setdefault(key, {
            "selected": set(), "shown": set(), "switched": set(), "png": set(), "csv": set(),
            "saved": set(), "render_failed": set(), "fallback": set(), "retained": set(),
        })
        bucket["selected"].add(query_id)
        names = {e.event_name for e in query_events}
        if "alternative_views_shown" in names:
            bucket["shown"].add(query_id)
        if "alternative_view_selected" in names:
            bucket["switched"].add(query_id)
        if "visualization_exported_png" in names:
            bucket["png"].add(query_id)
        if "visualization_exported_csv" in names:
            bucket["csv"].add(query_id)
        if "visualization_saved" in names:
            bucket["saved"].add(query_id)
        if "visualization_render_failed" in names:
            bucket["render_failed"].add(query_id)
        if "visualization_fallback_used" in names:
            bucket["fallback"].add(query_id)
        if final_active_type(representative, query_events) == representative.original_chart_type:
            bucket["retained"].add(query_id)

    rows = []
    for key, bucket in buckets.items():
        denominator = len(bucket["selected"])
        rows.append(RecommendationQualityRow(
            group_key=dict(zip(group_by, key)),
            total_selections=denominator,
            recommendation_retention_rate=rate_metric(len(bucket["retained"]), denominator),
            alternative_views_shown_rate=rate_metric(len(bucket["shown"]), denominator),
            alternative_switch_rate=rate_metric(len(bucket["switched"]), denominator),
            png_export_rate=rate_metric(len(bucket["png"]), denominator),
            csv_export_rate=rate_metric(len(bucket["csv"]), denominator),
            visualization_save_rate=rate_metric(len(bucket["saved"]), denominator),
            render_failure_rate=rate_metric(len(bucket["render_failed"]), denominator),
            fallback_rate=rate_metric(len(bucket["fallback"]), denominator),
        ))
    return RecommendationQualitySummaryResponse(rows=rows, group_by=list(group_by))


# ── replacement matrix ────────────────────────────────────────────────────

def compute_replacement_matrix(events: list[VisualizationTelemetryEvent]) -> ReplacementMatrixResponse:
    """Counts only successful switches — a query_id that switched and then
    switched BACK to the original recommendation nets to "no replacement"
    and contributes no cell here (see final_active_type: only the LAST
    switch in a query_id counts, and a final state equal to the original is
    excluded below)."""
    pair_counts: Counter[tuple[str, str]] = Counter()
    origin_totals: Counter[str] = Counter()
    for query_events in by_query_id(events).values():
        representative = representative_selection(query_events)
        if representative is None or representative.original_chart_type is None:
            continue
        has_switch = any(e.event_name == "alternative_view_selected" for e in query_events)
        if not has_switch:
            continue
        final_active = final_active_type(representative, query_events)
        original = representative.original_chart_type
        if not final_active or final_active == original:
            continue
        pair_counts[(original, final_active)] += 1
        origin_totals[original] += 1

    cells = [
        ReplacementMatrixCell(
            original_chart_type=original, active_chart_type=active, count=count,
            rate=min(1.0, count / origin_totals[original]) if origin_totals[original] else 0.0,
            sample_size=origin_totals[original],
            evidence_status=evidence_status(origin_totals[original]),
        )
        for (original, active), count in pair_counts.items()
    ]
    return ReplacementMatrixResponse(cells=cells)


# ── chart-type performance ───────────────────────────────────────────────

def compute_chart_type_performance(
    events: list[VisualizationTelemetryEvent], group_by: tuple[str, ...] = (),
) -> ChartTypePerformanceResponse:
    buckets: dict[tuple[str, ...], dict[str, set[str]]] = {}
    for query_id, query_events in by_query_id(events).items():
        representative = representative_selection(query_events)
        if representative is None or not representative.original_chart_type:
            continue
        extra_key = tuple(_group_key_value(representative, dimension) for dimension in group_by)
        key = (representative.original_chart_type, *extra_key)
        bucket = buckets.setdefault(key, {"selected": set(), "switched": set(), "fallback": set(), "render_failed": set()})
        bucket["selected"].add(query_id)
        names = {e.event_name for e in query_events}
        if "alternative_view_selected" in names:
            bucket["switched"].add(query_id)
        if "visualization_fallback_used" in names:
            bucket["fallback"].add(query_id)
        if "visualization_render_failed" in names:
            bucket["render_failed"].add(query_id)

    rows = []
    for key, bucket in buckets.items():
        chart_type, *extra = key
        denominator = len(bucket["selected"])
        switch = rate_metric(len(bucket["switched"]), denominator)
        fallback = rate_metric(len(bucket["fallback"]), denominator)
        render_failure = rate_metric(len(bucket["render_failed"]), denominator)
        rows.append(ChartTypePerformanceRow(
            group_key=dict(zip(group_by, extra)),
            chart_type=chart_type,
            total_selections=denominator,
            switch_rate=switch, fallback_rate=fallback, render_failure_rate=render_failure,
            unusually_high_switch_rate=(
                switch.evidence_status != EvidenceStatus.INSUFFICIENT_EVIDENCE and switch.rate >= _UNUSUALLY_HIGH_SWITCH_RATE
            ),
            unusually_high_fallback_rate=(
                fallback.evidence_status != EvidenceStatus.INSUFFICIENT_EVIDENCE and fallback.rate >= _UNUSUALLY_HIGH_FALLBACK_RATE
            ),
            unusually_high_render_failure_rate=(
                render_failure.evidence_status != EvidenceStatus.INSUFFICIENT_EVIDENCE
                and render_failure.rate >= _UNUSUALLY_HIGH_RENDER_FAILURE_RATE
            ),
        ))
    return ChartTypePerformanceResponse(rows=rows, group_by=list(group_by))


# ── recommendation analysis (weight proposals) ───────────────────────────

def propose_ranking_weight_adjustments(
    events: list[VisualizationTelemetryEvent], group_dimension: str = "analytical_intent",
) -> list[WeightAdjustmentProposal]:
    """Deterministic, narrow, and deliberately inert: flags
    (analytical_intent or chart_family) groups with a high, well-evidenced
    switch rate and proposes a small, bounds-clipped nudge to
    analytical_intent_fit — the one scoring dimension every chart type in
    every intent competes on. Never LLM-scored, never randomized, and never
    applied — see the module docstring on RankingConfiguration/
    ranking_configuration.py for why activation is always a separate,
    manual, reviewed step. group_dimension must be "analytical_intent" or
    "chart_family"."""
    if group_dimension not in ("analytical_intent", "chart_family"):
        raise ValueError('group_dimension must be "analytical_intent" or "chart_family"')

    buckets: dict[str, dict] = {}
    for query_events in by_query_id(events).values():
        representative = representative_selection(query_events)
        if representative is None:
            continue
        group_value = getattr(representative, group_dimension)
        if not group_value or not representative.original_chart_type:
            continue
        bucket = buckets.setdefault(group_value, {"selected": set(), "switched": set(), "pairs": Counter()})
        bucket["selected"].add(representative.query_id)
        final_active = final_active_type(representative, query_events)
        if final_active and final_active != representative.original_chart_type:
            bucket["switched"].add(representative.query_id)
            bucket["pairs"][(representative.original_chart_type, final_active)] += 1

    low, high = WEIGHT_BOUNDS[_PROPOSAL_DIMENSION]
    baseline_weight = current_weights()[_PROPOSAL_DIMENSION]

    proposals: list[WeightAdjustmentProposal] = []
    for group_value, bucket in buckets.items():
        denominator = len(bucket["selected"])
        switch_rate = rate_metric(len(bucket["switched"]), denominator)
        if switch_rate.evidence_status != EvidenceStatus.ELIGIBLE_FOR_REVIEW:
            continue
        if switch_rate.rate < _PROPOSAL_MIN_SWITCH_RATE or not bucket["pairs"]:
            continue
        (current_preference, replacement), _count = bucket["pairs"].most_common(1)[0]
        adjusted_weight = max(low, min(high, baseline_weight + _PROPOSAL_WEIGHT_DELTA))
        proposals.append(WeightAdjustmentProposal(
            affected_analytical_intent=group_value if group_dimension == "analytical_intent" else None,
            affected_chart_family=group_value if group_dimension == "chart_family" else None,
            current_chart_preference=current_preference,
            observed_replacement=replacement,
            sample_size=denominator,
            retention_or_switch_rate=switch_rate.rate,
            proposed_weight_adjustment={_PROPOSAL_DIMENSION: adjusted_weight - baseline_weight},
        ))
    return proposals
