"""
Orchestration domain models — ZL-ENG-02 §11.

Persisted objects for HUMAN_REVIEW and SECURITY_INCIDENT routes.
These must be written to the database before the response is returned.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, String, DateTime, UniqueConstraint, Boolean, Date
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VisualizationPreference(Base):
    __tablename__ = "visualization_preferences"
    __table_args__ = (UniqueConstraint("tenant_id", "actor_id", name="uq_visualization_preferences_scope"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String, nullable=False, default="1.0")
    preferences: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class VisualizationGapEvent(Base):
    """Privacy-safe product evidence, deliberately outside AuditEvent."""
    __tablename__ = "visualization_gap_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    dedup_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    analytical_intent: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_chart_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    requested_visualization_family: Mapped[str] = mapped_column(String, nullable=False)
    gap_type: Mapped[str] = mapped_column(String, nullable=False)
    data_shape_class: Mapped[str] = mapped_column(String, nullable=False)
    fallback_chart_type: Mapped[str | None] = mapped_column(String, nullable=True)
    fallback_output_type: Mapped[str] = mapped_column(String, nullable=False)
    registry_candidate_count: Mapped[int] = mapped_column(nullable=False)
    ranking_version: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[str] = mapped_column(String, nullable=False, index=True)
    valid_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class VisualizationGapReport(Base):
    __tablename__ = "visualization_gap_reports"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    evidence_version: Mapped[str] = mapped_column(String, nullable=False)
    approved_findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    artifact: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class VisualizationTelemetryEvent(Base):
    """Dynamic Visualization Selection v4 — privacy-safe product telemetry
    for chart selection/interaction. Deliberately separate from AuditEvent
    (audit_ledger/models.py): that ledger is a chain-hashed compliance/
    replay artifact governed by its own retention and correction rules
    (CompensatingEvent) and is not the right home for UX analytics. This
    table is also the sole source of "recent chart types in this
    conversation" for the repetition-penalty scoring dimension — only
    PresentationChart selections ever write a row here (no
    CalculationWidget/PresentationGuide/PresentationGraph), so querying it
    for recent history is structurally correct by construction, not by a
    filter.

    Columns are an intentional allow-list — see
    app/orchestration/visualization_telemetry.py's record_visualization_event
    for the enforced privacy boundary (its signature has no parameter for
    query text, answer text, chart values, or any other content field, so
    there is no way to accidentally pass one in)."""

    __tablename__ = "visualization_telemetry_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    event_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    query_id: Mapped[str | None] = mapped_column(String, nullable=True)
    analytical_intent: Mapped[str | None] = mapped_column(String, nullable=True)
    original_chart_type: Mapped[str | None] = mapped_column(String, nullable=True)
    active_chart_type: Mapped[str | None] = mapped_column(String, nullable=True)
    alternative_count: Mapped[int | None] = mapped_column(nullable=True)
    selection_source: Mapped[str | None] = mapped_column(String, nullable=True)
    renderer: Mapped[str | None] = mapped_column(String, nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # v5 — which chart family the active/original type belongs to (e.g.
    # "temporal_series", "single_total_composition") — see
    # presentation_dataprofile._CHART_FAMILY. Nullable so v4 rows/callers
    # that never set it stay valid.
    chart_family: Mapped[str | None] = mapped_column(String, nullable=True)
    # v6 — presentation_dataprofile.RANKING_VERSION at selection time, so
    # recommendation-quality reporting can compare outcomes across weight
    # revisions once one actually ships (see ranking_configuration.py).
    # Nullable for the same reason as chart_family: older rows never set it.
    ranking_version: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # v7 — which RankingExperiment (if any) this selection was subject to,
    # and which arm ("control"/"variant") the deterministic assignment
    # placed this conversation in. Both nullable: most selections never
    # participate in an experiment at all. See ranking_experiments.py.
    experiment_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    experiment_group: Mapped[str | None] = mapped_column(String, nullable=True)
    # v8 privacy-safe boolean only; the preference record itself is never telemetry.
    preference_affected_selection: Mapped[bool | None] = mapped_column(nullable=True)
    # V8.2 source marker. Nullable only for pre-V8.2 historical rows, which
    # production gap reports deliberately exclude.
    environment: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # v10 — same posture as preference_affected_selection above: booleans/
    # enum-valued strings only, never the personalization profile itself.
    # See visualization_personalization.py for what feeds these.
    personalization_enabled: Mapped[bool | None] = mapped_column(nullable=True)
    personalization_affected_selection: Mapped[bool | None] = mapped_column(nullable=True)
    personalization_model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    personalization_confidence_band: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class RankingConfiguration(Base):
    """Dynamic Visualization Selection v6 — a versioned, governed PROPOSAL
    for presentation_dataprofile._WEIGHTS. Deliberately inert: nothing in
    the live scoring path (_score_candidate) reads this table. Approving a
    row here is a recorded governance decision, not a deployment — actually
    changing production weights still requires editing _WEIGHTS and bumping
    RANKING_VERSION in code, same as any other reviewed code change. See
    ranking_configuration.py's module docstring for the full reasoning.

    Maker-checker, same pattern as CompensatingEvent (audit_ledger/models.py):
    created_by and approved_by must differ — enforced in
    ranking_configuration.py's service layer, not here."""

    __tablename__ = "ranking_configurations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ranking_version: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    weights: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft", index=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class RankingExperiment(Base):
    """Dynamic Visualization Selection v7 — a controlled A/B comparison of
    one approved RankingConfiguration ("variant") against the current
    production baseline ("control"), scoped to conversations matched by
    targeting_rules and split by deterministic hashing (see
    ranking_experiments.py's assignment_bucket). At most one experiment may
    be "active" at a time (enforced in ranking_experiments.py, not here) —
    overlapping experiments would make guardrail attribution ambiguous.

    Like RankingConfiguration, this table is inert with respect to the live
    scorer by default: applying variant weights only ever happens through
    the explicit, narrow path in presentation.py that reads THIS row's own
    status/targeting/assignment — there is no separate "activation" that
    silently changes _WEIGHTS. Rolling back or pausing is a single status
    write here; no code deploy is required for either direction."""

    __tablename__ = "ranking_experiments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft", index=True)
    control_ranking_version: Mapped[str] = mapped_column(String, nullable=False)
    variant_ranking_version: Mapped[str] = mapped_column(String, nullable=False)
    control_allocation_percent: Mapped[float] = mapped_column(nullable=False)
    variant_allocation_percent: Mapped[float] = mapped_column(nullable=False)
    # {"analytical_intent": ["comparison", ...], "chart_family": [...]} —
    # closed key set, validated against _APPROVED_TARGETING_FIELDS.
    targeting_rules: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    primary_metrics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    secondary_metrics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    guardrail_metrics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    minimum_sample_size: Mapped[int | None] = mapped_column(nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    # Not in the v7 spec's own field list verbatim, but required to satisfy
    # its own frontend requirement ("Display: ... pause or rollback
    # reason") — there is no other column this could be stored in.
    status_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class ReviewCase(Base):
    """
    Persisted human review object — §11.1.
    Created whenever route == HUMAN_REVIEW; returning the label without
    a persisted object is non-compliant per §8.1.
    """
    __tablename__ = "review_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    query_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    confidence_state: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    assigned_queue: Mapped[str] = mapped_column(String, nullable=False, default="accounting_review")
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    policy_version: Mapped[str] = mapped_column(String, nullable=False, default="pm_1.0")
    classifier_version: Mapped[str] = mapped_column(String, nullable=False, default="rc_1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class VisualizationEvidenceAggregationRun(Base):
    """V8.4/V8.5 — one row per evidence_monitoring.run_evidence_monitoring()
    execution (scheduled or explicitly invoked). Purely a record of when
    aggregation ran and what it found; never itself a governance decision —
    see VisualizationGapReport/VisualizationEvidenceAlert for the
    draft-report and reviewer-notification side effects a run may
    (idempotently) trigger.

    V8.5 adds full run-lifecycle bookkeeping: a row is written with
    status="running" BEFORE any aggregation work starts (so a concurrent
    request/retry can see "a run is already active" without racing), then
    updated to "succeeded" or "failed" in place. (tenant_id,
    monitoring_period) is the run-level idempotency key a scheduled/manual
    retry checks against — deliberately separate from
    VisualizationEvidenceAlert's (tenant_id, evidence_version) key, which
    is the content-level dedup that decides whether a NEW draft/alert gets
    created. failure_category is a closed, safe classification
    (see evidence_monitoring.FailureCategory) — this column can never hold
    a raw exception message, query, or chart value."""

    __tablename__ = "visualization_evidence_aggregation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running", index=True)
    monitoring_period: Mapped[str] = mapped_column(String, nullable=False, index=True)
    trigger_source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    evidence_version: Mapped[str] = mapped_column(String, nullable=False, default="")
    valid_event_count: Mapped[int] = mapped_column(nullable=False, default=0)
    distinct_conversation_count: Mapped[int] = mapped_column(nullable=False, default=0)
    distinct_actor_count: Mapped[int] = mapped_column(nullable=False, default=0)
    eligible_finding_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_report_id: Mapped[str | None] = mapped_column(String, nullable=True)
    draft_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_category: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, nullable=False)


class VisualizationEvidenceAlert(Base):
    """V8.4 — reviewer-notification dedup record. One row per
    (tenant_id, evidence_version): its unique constraint IS the dedup
    mechanism (a second attempt to notify for the same evidence version
    fails the insert rather than sending a second alert or drafting a
    second report). Deliberately holds no content beyond a pointer to the
    report — the notification itself is "a draft report for this tenant is
    ready for review", read by authorized reviewers off the admin endpoint,
    not pushed through email/Slack/etc. in this codebase."""

    __tablename__ = "visualization_evidence_alerts"
    __table_args__ = (UniqueConstraint("tenant_id", "evidence_version", name="uq_visualization_evidence_alerts_scope"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    evidence_version: Mapped[str] = mapped_column(String, nullable=False)
    report_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class VisualizationPersonalizationConsent(Base):
    """V10 — explicit, per-(tenant_id, actor_id) consent for personalized
    visualization ranking. Disabled by default (personalization_enabled
    defaults False on a row that hasn't been created yet — see
    visualization_personalization_consent.py's get_consent, which returns
    an all-defaults/disabled object for a missing row rather than creating
    one). Never inferred from product usage — only ever written by an
    explicit PUT from the owning user."""

    __tablename__ = "visualization_personalization_consents"
    __table_args__ = (UniqueConstraint("tenant_id", "actor_id", name="uq_visualization_personalization_consents_scope"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    personalization_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    personalization_scope: Mapped[str] = mapped_column(String, nullable=False, default="visualization_only")
    personalization_history_window: Mapped[str] = mapped_column(String, nullable=False, default="90_days")
    allow_view_switch_learning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_export_learning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_save_learning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    consent_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class VisualizationPersonalizationProfile(Base):
    """V10 — the LEARNED, aggregated-only output of profile recomputation.
    Never holds individual query-level behavior (no query_id, no per-event
    log) — only summary preference dicts and confidence scores derived from
    the underlying VisualizationTelemetryEvent rows, which remain subject to
    their own existing retention rules. One row per (tenant_id, actor_id);
    recomputation overwrites it in place rather than accumulating history."""

    __tablename__ = "visualization_personalization_profiles"
    __table_args__ = (UniqueConstraint("tenant_id", "actor_id", name="uq_visualization_personalization_profiles_scope"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String, nullable=False)
    consent_status: Mapped[str] = mapped_column(String, nullable=False)
    consent_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    interaction_count: Mapped[int] = mapped_column(nullable=False, default=0)
    conversation_count: Mapped[int] = mapped_column(nullable=False, default=0)
    chart_family_preferences: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    intent_chart_preferences: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    table_preference_signal: Mapped[float | None] = mapped_column(nullable=True)
    density_preference_signal: Mapped[float | None] = mapped_column(nullable=True)
    confidence_by_signal: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_recomputed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class VisualizationPersonalizationRecomputationRun(Base):
    """V10 — run-lifecycle bookkeeping for profile recomputation, same
    shape/purpose as VisualizationEvidenceAggregationRun (V8.5): a row is
    written with status="running" before any work starts, then updated to
    "succeeded"/"failed" in place. failure_category is a closed, safe
    classification (see visualization_personalization.FailureCategory) —
    never a raw exception message, and event_count is a count only, never
    the events themselves."""

    __tablename__ = "visualization_personalization_recomputation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running", index=True)
    processing_date: Mapped[str] = mapped_column(String, nullable=False, index=True)
    profile_version: Mapped[str] = mapped_column(String, nullable=False, default="")
    profiles_recomputed_count: Mapped[int] = mapped_column(nullable=False, default=0)
    event_count: Mapped[int] = mapped_column(nullable=False, default=0)
    failure_category: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, nullable=False)
