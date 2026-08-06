"""Dynamic Visualization Selection v7 — controlled ranking experiments.

A RankingExperiment safely compares one approved RankingConfiguration
("variant") against the current production baseline ("control") on a
deterministic slice of live conversations, with predefined metrics, a
minimum-sample gate before any decision, automatic guardrail pausing, and
rollback that never requires a code deploy.

Three ideas carry the whole design:

1. **Inert by default, like RankingConfiguration.** Nothing here changes
   presentation_dataprofile._WEIGHTS. An active experiment's variant arm
   only ever reaches _score_candidate through the `weights` parameter v7
   added to select_chart_with_alternatives/select_family_alternatives (see
   presentation_dataprofile.py) — for ONE specific request, matched by
   targeting, assigned to "variant" by the deterministic hash below. The
   moment an experiment is paused or rolled back, the very next request
   simply stops resolving an ExperimentContext at all and falls back to
   control — a single DB row write, no deploy.

2. **Assignment is conversation-level and independent of chart content.**
   assignment_bucket hashes (tenant_id, actor_id, conversation_id,
   experiment_id) — never anything about the chart being built — so the
   same conversation always lands in the same arm for as long as the
   experiment exists, and different tenants/actors are governed by
   completely different hash inputs (no cross-tenant correlation is even
   representable). TARGETING (which intents/families this experiment
   applies to) is a separate, per-chart check layered on top — see
   matches_targeting — evaluated against the profile's OWN default
   chart_type/intent, which is computed identically whether or not an
   experiment exists (the v1-v6 protected-default guarantee extends
   unchanged into v7).

3. **No scheduler exists in this codebase, so nothing here assumes one.**
   "scheduled" experiments become effectively active once start_at passes
   simply by being *read* that way (effective_status) — not through a cron
   job flipping the stored status. Guardrail pausing is triggered
   opportunistically, right when new render-failure/fallback evidence
   arrives for an experiment-tagged event (see service.py/router.py), not
   on a timer either.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.orchestration import ranking_configuration as ranking_configuration_service
from app.orchestration import visualization_analytics as analytics
from app.orchestration.models import RankingExperiment, VisualizationTelemetryEvent
from app.orchestration.ranking_experiments_schemas import (
    ExperimentGroupMetrics,
    ExperimentResultsResponse,
    ExperimentResultStatus,
    ExperimentStatus,
    RateMetricWithConfidenceInterval,
    validate_metric_list,
    validate_targeting_rules,
)
from app.orchestration.visualization_analytics_schemas import EvidenceStatus


class RankingExperimentError(Exception):
    """Base class — callers (the router) catch this and translate to an
    appropriate HTTP status rather than leaking internals."""


class BothConfigurationsMustExistError(RankingExperimentError):
    pass


class VariantMustBeApprovedError(RankingExperimentError):
    pass


class AnotherExperimentAlreadyActiveError(RankingExperimentError):
    pass


class MinimumSampleSizeRequiredError(RankingExperimentError):
    pass


class InvalidExperimentTransitionError(RankingExperimentError):
    pass


class RankingExperimentNotFoundError(RankingExperimentError):
    pass


class SelfApprovalError(RankingExperimentError):
    """Maker-checker, same rule as RankingConfiguration approval."""


# ── deterministic conversation-level assignment ──────────────────────────

def assignment_bucket(tenant_id: str, actor_id: str | None, conversation_id: str | None, experiment_id: str) -> float:
    """Pure and deterministic — the same four inputs always produce the
    same [0, 100) bucket, with no randomness and no DB read. This is the
    entire guarantee behind "the same conversation always receives the
    same assignment" (v7 requirement 5): the bucket is a hash, not a
    stored decision, so there is nothing to look up or drift."""
    key = f"{tenant_id}:{actor_id or 'none'}:{conversation_id or 'none'}:{experiment_id}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    bucket_int = int(digest[:8], 16)
    return (bucket_int / 0xFFFFFFFF) * 100.0


def resolve_group(experiment: RankingExperiment, tenant_id: str, actor_id: str | None, conversation_id: str | None) -> str:
    bucket = assignment_bucket(tenant_id, actor_id, conversation_id, experiment.id)
    return "control" if bucket < experiment.control_allocation_percent else "variant"


def matches_targeting(targeting_rules: dict[str, list[str]], analytical_intent: str | None, chart_family: str | None) -> bool:
    """Empty targeting_rules matches everything. Each present key is an
    AND'd allow-list; a profile whose own value isn't in the list never
    matches, so unrelated intents/families are excluded by construction —
    there is no "exclude" list to get backwards."""
    intent_filter = targeting_rules.get("analytical_intent")
    if intent_filter and analytical_intent not in intent_filter:
        return False
    family_filter = targeting_rules.get("chart_family")
    if family_filter and chart_family not in family_filter:
        return False
    return True


# A/B testing convention, not derived from anything in this codebase —
# fixed and documented like every other threshold in this module family
# (v6's evidence/unusually-high thresholds). One full week avoids weekday/
# weekend traffic-mix skew dominating a same-day read.
MINIMUM_EXPERIMENT_DURATION = timedelta(days=7)


def _as_aware_utc(value: datetime | None) -> datetime | None:
    """SQLite (used in tests, see tests/conftest.py) doesn't actually store
    timezone info despite the DateTime(timezone=True) column type — a row
    read back has a naive datetime even though it was written aware, which
    raises TypeError the moment it's compared against datetime.now(utc).
    Postgres doesn't have this problem, but this module has to work
    correctly under both, so every stored datetime is normalized through
    this before comparison."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def effective_status(experiment: RankingExperiment, now: datetime | None = None) -> str:
    """Lazily-computed status used ONLY to decide whether the variant
    should be applied / whether an experiment counts as "active" for
    listing — never written back to the row by this function itself. See
    module docstring point 3."""
    now = now or datetime.now(timezone.utc)
    start_at = _as_aware_utc(experiment.start_at)
    end_at = _as_aware_utc(experiment.end_at)
    if experiment.status == ExperimentStatus.SCHEDULED.value and start_at and now >= start_at:
        return ExperimentStatus.ACTIVE.value
    if experiment.status == ExperimentStatus.ACTIVE.value and end_at and now > end_at:
        return ExperimentStatus.COMPLETED.value
    return experiment.status


# ── request-time experiment context ──────────────────────────────────────

@dataclass(frozen=True)
class ExperimentContext:
    experiment_id: str
    group: str  # "control" | "variant"
    control_ranking_version: str
    variant_ranking_version: str
    variant_weights: dict[str, float]
    targeting_rules: dict[str, list[str]]


async def resolve_experiment_context(
    db: AsyncSession, *, tenant_id: str, actor_id: str | None, conversation_id: str | None,
) -> ExperimentContext | None:
    """Called once per request — assignment is conversation-level, not
    chart-level. Fails safe on every path: no active experiment, an
    invalid/unapproved variant configuration (itself a guardrail — see
    module docstring — and auto-pauses the experiment), or any DB error all
    return None, which callers treat exactly like "no experiment
    running": falling back to control is always safe; letting an
    experiment-plumbing problem affect the answer itself is not."""
    try:
        result = await db.execute(select(RankingExperiment).where(RankingExperiment.status == ExperimentStatus.ACTIVE.value))
        experiments = list(result.scalars().all())
        if not experiments:
            result = await db.execute(select(RankingExperiment).where(RankingExperiment.status == ExperimentStatus.SCHEDULED.value))
            experiments = [e for e in result.scalars().all() if effective_status(e) == ExperimentStatus.ACTIVE.value]
        if not experiments:
            return None
        experiment = experiments[0]

        variant_config = await ranking_configuration_service.get_configuration_by_version(db, experiment.variant_ranking_version)
        if variant_config is None or variant_config.status != "approved":
            await _auto_pause(db, experiment, reason="guardrail: variant ranking configuration is missing or not approved")
            return None

        group = resolve_group(experiment, tenant_id, actor_id, conversation_id)
        return ExperimentContext(
            experiment_id=experiment.id, group=group,
            control_ranking_version=experiment.control_ranking_version,
            variant_ranking_version=experiment.variant_ranking_version,
            variant_weights=dict(variant_config.weights),
            targeting_rules=dict(experiment.targeting_rules),
        )
    except Exception:
        return None


# ── audit logging (administrative change log, never product telemetry) ──

async def _audit_log(db: AsyncSession, *, event_name: str, experiment: RankingExperiment, actor_id: str, extra: dict | None = None) -> None:
    await record_event_async(
        db, event_name=event_name, emitting_service="orchestration",
        subject_type="ranking_experiment", subject_id=experiment.id, actor_id=actor_id,
        tenant_id="GLOBAL_CONTROL", classification="INTERNAL", replay_relevance="SUPPORTING",
        payload={"experiment_id": experiment.id, "name": experiment.name, "status": experiment.status, **(extra or {})},
    )


async def _auto_pause(db: AsyncSession, experiment: RankingExperiment, *, reason: str) -> None:
    experiment.status = ExperimentStatus.PAUSED.value
    experiment.status_reason = reason
    await db.commit()
    try:
        await _audit_log(db, event_name="ranking_experiment_auto_paused", experiment=experiment, actor_id="system", extra={"reason": reason})
    except Exception:
        pass  # an audit-write failure must never block the fallback-to-control this pause exists to guarantee.


# ── lifecycle ──────────────────────────────────────────────────────────────

async def get_experiment(db: AsyncSession, experiment_id: str) -> RankingExperiment | None:
    return await db.get(RankingExperiment, experiment_id)


async def list_experiments(db: AsyncSession, *, status: str | None = None) -> list[RankingExperiment]:
    stmt = select(RankingExperiment).order_by(RankingExperiment.created_at.desc())
    if status is not None:
        stmt = stmt.where(RankingExperiment.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_active_experiments(db: AsyncSession) -> list[RankingExperiment]:
    return [e for e in await list_experiments(db) if effective_status(e) == ExperimentStatus.ACTIVE.value]


async def create_draft(
    db: AsyncSession, *, name: str, description: str, control_ranking_version: str, variant_ranking_version: str,
    control_allocation_percent: float, variant_allocation_percent: float, targeting_rules: dict[str, list[str]],
    primary_metrics: list[str], secondary_metrics: list[str], guardrail_metrics: list[str],
    minimum_sample_size: int | None, start_at: datetime | None, end_at: datetime | None, created_by: str,
) -> RankingExperiment:
    validate_targeting_rules(targeting_rules)  # defense in depth — the request schema already validated this.
    validate_metric_list(primary_metrics)
    validate_metric_list(secondary_metrics)
    validate_metric_list(guardrail_metrics)

    control_config = await ranking_configuration_service.get_configuration_by_version(db, control_ranking_version)
    variant_config = await ranking_configuration_service.get_configuration_by_version(db, variant_ranking_version)
    if control_config is None or variant_config is None:
        raise BothConfigurationsMustExistError("both control_ranking_version and variant_ranking_version must reference existing ranking configurations")

    row = RankingExperiment(
        name=name, description=description, status=ExperimentStatus.DRAFT.value,
        control_ranking_version=control_ranking_version, variant_ranking_version=variant_ranking_version,
        control_allocation_percent=control_allocation_percent, variant_allocation_percent=variant_allocation_percent,
        targeting_rules=targeting_rules, primary_metrics=primary_metrics, secondary_metrics=secondary_metrics,
        guardrail_metrics=guardrail_metrics, minimum_sample_size=minimum_sample_size,
        start_at=start_at, end_at=end_at, created_by=created_by,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def approve_experiment(db: AsyncSession, *, experiment_id: str, approver_id: str) -> RankingExperiment:
    experiment = await get_experiment(db, experiment_id)
    if experiment is None:
        raise RankingExperimentNotFoundError(experiment_id)
    if experiment.status != ExperimentStatus.DRAFT.value:
        raise InvalidExperimentTransitionError(f"experiment {experiment_id} is {experiment.status}, not draft")
    if experiment.created_by == approver_id:
        raise SelfApprovalError("the actor who drafted an experiment cannot also approve it")
    variant_config = await ranking_configuration_service.get_configuration_by_version(db, experiment.variant_ranking_version)
    if variant_config is None or variant_config.status != "approved":
        raise VariantMustBeApprovedError("variant_ranking_version must reference an approved ranking configuration")

    experiment.status = ExperimentStatus.APPROVED.value
    experiment.approved_by = approver_id
    await db.commit()
    await db.refresh(experiment)
    await _audit_log(db, event_name="ranking_experiment_approved", experiment=experiment, actor_id=approver_id)
    return experiment


async def activate_experiment(db: AsyncSession, *, experiment_id: str, actor_id: str) -> RankingExperiment:
    experiment = await get_experiment(db, experiment_id)
    if experiment is None:
        raise RankingExperimentNotFoundError(experiment_id)
    if experiment.status not in (ExperimentStatus.APPROVED.value, ExperimentStatus.SCHEDULED.value):
        raise InvalidExperimentTransitionError(f"experiment {experiment_id} is {experiment.status}, not approved or scheduled")
    if not experiment.minimum_sample_size or experiment.minimum_sample_size <= 0:
        raise MinimumSampleSizeRequiredError("minimum_sample_size must be defined before activation")

    result = await db.execute(
        select(RankingExperiment).where(RankingExperiment.status == ExperimentStatus.ACTIVE.value, RankingExperiment.id != experiment.id)
    )
    # .first(), not .scalar_one_or_none() — this only needs to know whether
    # ANY other active row exists, not assert there's at most one; failing
    # the activation request is strictly more correct than crashing if the
    # invariant were ever violated by something outside this function.
    if result.scalars().first() is not None:
        raise AnotherExperimentAlreadyActiveError("another experiment is already active — at most one may run at a time")

    variant_config = await ranking_configuration_service.get_configuration_by_version(db, experiment.variant_ranking_version)
    if variant_config is None or variant_config.status != "approved":
        raise VariantMustBeApprovedError("variant_ranking_version must reference an approved ranking configuration")

    now = datetime.now(timezone.utc)
    start_at = _as_aware_utc(experiment.start_at)
    experiment.status = (
        ExperimentStatus.ACTIVE.value if start_at is None or start_at <= now
        else ExperimentStatus.SCHEDULED.value
    )
    experiment.status_reason = None
    await db.commit()
    await db.refresh(experiment)
    await _audit_log(
        db, event_name="ranking_experiment_activated" if experiment.status == ExperimentStatus.ACTIVE.value else "ranking_experiment_scheduled",
        experiment=experiment, actor_id=actor_id,
    )
    return experiment


async def pause_experiment(db: AsyncSession, *, experiment_id: str, actor_id: str, reason: str) -> RankingExperiment:
    experiment = await get_experiment(db, experiment_id)
    if experiment is None:
        raise RankingExperimentNotFoundError(experiment_id)
    if experiment.status not in (ExperimentStatus.ACTIVE.value, ExperimentStatus.SCHEDULED.value):
        raise InvalidExperimentTransitionError(f"experiment {experiment_id} is {experiment.status}, not active or scheduled")
    experiment.status = ExperimentStatus.PAUSED.value
    experiment.status_reason = reason
    await db.commit()
    await db.refresh(experiment)
    await _audit_log(db, event_name="ranking_experiment_paused", experiment=experiment, actor_id=actor_id, extra={"reason": reason})
    return experiment


async def complete_experiment(db: AsyncSession, *, experiment_id: str, actor_id: str, reason: str | None = None) -> RankingExperiment:
    experiment = await get_experiment(db, experiment_id)
    if experiment is None:
        raise RankingExperimentNotFoundError(experiment_id)
    if experiment.status not in (ExperimentStatus.ACTIVE.value, ExperimentStatus.PAUSED.value, ExperimentStatus.SCHEDULED.value):
        raise InvalidExperimentTransitionError(f"experiment {experiment_id} is {experiment.status}, not active, paused, or scheduled")
    experiment.status = ExperimentStatus.COMPLETED.value
    if reason:
        experiment.status_reason = reason
    await db.commit()
    await db.refresh(experiment)
    await _audit_log(db, event_name="ranking_experiment_completed", experiment=experiment, actor_id=actor_id)
    return experiment


async def rollback_experiment(db: AsyncSession, *, experiment_id: str, actor_id: str, reason: str) -> RankingExperiment:
    """Immediate: stops applying the variant (status no longer "active", so
    resolve_experiment_context stops returning this experiment on the very
    next request), routes new requests to control, and — critically —
    never touches VisualizationTelemetryEvent at all, so every historical
    experiment event (and every SavedVisualization payload rendered under
    the variant) is preserved exactly as it was. No code deployment is
    involved; this is a single row update."""
    experiment = await get_experiment(db, experiment_id)
    if experiment is None:
        raise RankingExperimentNotFoundError(experiment_id)
    if experiment.status in (ExperimentStatus.ROLLED_BACK.value, ExperimentStatus.CANCELLED.value, ExperimentStatus.COMPLETED.value):
        raise InvalidExperimentTransitionError(f"experiment {experiment_id} is already {experiment.status}")
    experiment.status = ExperimentStatus.ROLLED_BACK.value
    experiment.status_reason = reason
    await db.commit()
    await db.refresh(experiment)
    await _audit_log(db, event_name="ranking_experiment_rolled_back", experiment=experiment, actor_id=actor_id, extra={"reason": reason})
    return experiment


# ── guardrails ─────────────────────────────────────────────────────────────
# Fixed, documented thresholds, same style as v6's. A lower minimum sample
# than the "eligible_for_review" bar used for WINNER decisions on purpose:
# protecting users from a bad variant should trip fast; declaring a winner
# should not.
_GUARDRAIL_MIN_SAMPLE = 10
_GUARDRAIL_RATE_MULTIPLIER = 2.0
_GUARDRAIL_ABSOLUTE_FLOOR = 0.05


def _guardrail_tripped(variant_rate: float, variant_sample: int, control_rate: float) -> bool:
    if variant_sample < _GUARDRAIL_MIN_SAMPLE:
        return False
    threshold = max(control_rate * _GUARDRAIL_RATE_MULTIPLIER, _GUARDRAIL_ABSOLUTE_FLOOR)
    return variant_rate > threshold


async def _fetch_experiment_events(db: AsyncSession, experiment_id: str) -> list[VisualizationTelemetryEvent]:
    """Experiments are a global (not per-tenant) governance entity, exactly
    like RankingConfiguration — this deliberately has no tenant_id filter,
    unlike visualization_analytics.fetch_events. Only admins can reach this
    (see ranking_experiments_router.py), and experiment_id itself is the
    correlation key, so this doesn't relax v6's own tenant-isolation
    requirement for the reporting endpoints — those are a separate,
    intentionally tenant-scoped surface."""
    result = await db.execute(select(VisualizationTelemetryEvent).where(VisualizationTelemetryEvent.experiment_id == experiment_id))
    return list(result.scalars().all())


def _group_buckets(events: list[VisualizationTelemetryEvent], group: str) -> dict[str, set[str]]:
    group_events = [e for e in events if e.experiment_group == group]
    buckets: dict[str, set[str]] = {
        "selected": set(), "shown": set(), "switched": set(), "png": set(), "csv": set(),
        "saved": set(), "render_failed": set(), "fallback": set(), "retained": set(),
    }
    for query_id, query_events in analytics.by_query_id(group_events).items():
        representative = analytics.representative_selection(query_events)
        if representative is None:
            continue
        buckets["selected"].add(query_id)
        names = {e.event_name for e in query_events}
        if "alternative_views_shown" in names:
            buckets["shown"].add(query_id)
        if "alternative_view_selected" in names:
            buckets["switched"].add(query_id)
        if "visualization_exported_png" in names:
            buckets["png"].add(query_id)
        if "visualization_exported_csv" in names:
            buckets["csv"].add(query_id)
        if "visualization_saved" in names:
            buckets["saved"].add(query_id)
        if "visualization_render_failed" in names:
            buckets["render_failed"].add(query_id)
        if "visualization_fallback_used" in names:
            buckets["fallback"].add(query_id)
        if analytics.final_active_type(representative, query_events) == representative.original_chart_type:
            buckets["retained"].add(query_id)
    return buckets


async def evaluate_guardrails(db: AsyncSession, experiment: RankingExperiment) -> list[str]:
    """Human-readable, closed-vocabulary findings only — never raw error
    text. A telemetry-processing failure while evaluating guardrails is
    itself treated as a guardrail finding (fail-safe: if we can't measure
    reliably, that is reason enough to pause) — v7 requirement 14's fourth
    trigger."""
    try:
        events = await _fetch_experiment_events(db, experiment.id)
    except Exception:
        return ["telemetry processing failure — guardrails could not be evaluated reliably"]

    control = _group_buckets(events, "control")
    variant = _group_buckets(events, "variant")
    control_n, variant_n = len(control["selected"]), len(variant["selected"])
    findings: list[str] = []

    control_render_failure = (len(control["render_failed"]) / control_n) if control_n else 0.0
    variant_render_failure = (len(variant["render_failed"]) / variant_n) if variant_n else 0.0
    if _guardrail_tripped(variant_render_failure, variant_n, control_render_failure):
        findings.append("variant render_failure_rate exceeds the guardrail threshold relative to control")

    control_fallback = (len(control["fallback"]) / control_n) if control_n else 0.0
    variant_fallback = (len(variant["fallback"]) / variant_n) if variant_n else 0.0
    if _guardrail_tripped(variant_fallback, variant_n, control_fallback):
        findings.append("variant fallback_rate exceeds the guardrail threshold relative to control")

    return findings


async def check_and_maybe_pause(db: AsyncSession, experiment_id: str) -> RankingExperiment | None:
    """The "automatic pause trigger" (v7 requirement 14) without a
    scheduler: call this right after recording a render-failure or
    fallback telemetry event tagged with an experiment_id (see
    router.py/service.py) — new evidence of exactly the triggering
    condition is what prompts the check, not a timer. Returns the
    (now-paused) experiment if a guardrail tripped, else None; never
    raises — a failure here must not affect the caller's own request."""
    try:
        experiment = await get_experiment(db, experiment_id)
        if experiment is None or effective_status(experiment) != ExperimentStatus.ACTIVE.value:
            return None
        findings = await evaluate_guardrails(db, experiment)
        if not findings:
            return None
        await _auto_pause(db, experiment, reason="guardrail: " + "; ".join(findings))
        return experiment
    except Exception:
        return None


# ── results / uncertainty measure ────────────────────────────────────────

def _wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95%-confidence Wilson score interval for a proportion — chosen over
    the simpler normal approximation because it stays within [0, 1] and
    stays meaningful at small n, both of which matter for an experiment
    still accumulating evidence. No dependency beyond math.sqrt."""
    if n == 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1 + (z ** 2) / n
    center = phat + (z ** 2) / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + (z ** 2) / (4 * n)) / n)
    low = (center - margin) / denom
    high = (center + margin) / denom
    return (max(0.0, low), min(1.0, high))


def _rate_metric_with_ci(numerator: int, denominator: int) -> RateMetricWithConfidenceInterval:
    base = analytics.rate_metric(numerator, denominator)
    low, high = _wilson_interval(numerator, denominator)
    return RateMetricWithConfidenceInterval(
        rate=base.rate, numerator=base.numerator, sample_size=base.sample_size,
        evidence_status=base.evidence_status, confidence_interval_low=low, confidence_interval_high=high,
    )


def _group_metrics(events: list[VisualizationTelemetryEvent], group: str, ranking_version: str) -> ExperimentGroupMetrics:
    buckets = _group_buckets(events, group)
    denominator = len(buckets["selected"])
    return ExperimentGroupMetrics(
        group=group, ranking_version=ranking_version, selections=denominator,
        recommendation_retention_rate=_rate_metric_with_ci(len(buckets["retained"]), denominator),
        alternative_views_shown_rate=_rate_metric_with_ci(len(buckets["shown"]), denominator),
        alternative_switch_rate=_rate_metric_with_ci(len(buckets["switched"]), denominator),
        png_export_rate=_rate_metric_with_ci(len(buckets["png"]), denominator),
        csv_export_rate=_rate_metric_with_ci(len(buckets["csv"]), denominator),
        visualization_save_rate=_rate_metric_with_ci(len(buckets["saved"]), denominator),
        render_failure_rate=_rate_metric_with_ci(len(buckets["render_failed"]), denominator),
        fallback_rate=_rate_metric_with_ci(len(buckets["fallback"]), denominator),
    )


def classify_experiment_result(
    experiment: RankingExperiment, control_selections: int, variant_selections: int,
    guardrail_findings: list[str], now: datetime | None = None,
) -> ExperimentResultStatus:
    """Never declares a winner (ELIGIBLE_FOR_DECISION) before v7 requirement
    13's three gates all pass: minimum sample size reached on BOTH arms,
    the fixed minimum experiment duration has elapsed since start_at, and
    no guardrail has failed. A guardrail failure — live or from a prior
    auto-pause — always wins the classification regardless of sample size,
    since it means the comparison itself may not be trustworthy."""
    now = now or datetime.now(timezone.utc)
    was_guardrail_paused = experiment.status == ExperimentStatus.PAUSED.value and (experiment.status_reason or "").startswith("guardrail:")
    if guardrail_findings or was_guardrail_paused:
        return ExperimentResultStatus.GUARDRAIL_FAILED

    minimum = experiment.minimum_sample_size or 0
    sample_ok = minimum > 0 and control_selections >= minimum and variant_selections >= minimum
    if not sample_ok:
        control_evidence = analytics.evidence_status(control_selections)
        variant_evidence = analytics.evidence_status(variant_selections)
        if control_evidence == EvidenceStatus.INSUFFICIENT_EVIDENCE or variant_evidence == EvidenceStatus.INSUFFICIENT_EVIDENCE:
            return ExperimentResultStatus.INSUFFICIENT_EVIDENCE
        return ExperimentResultStatus.EXPERIMENT_RUNNING

    start_at = _as_aware_utc(experiment.start_at)
    duration_ok = start_at is not None and (now - start_at) >= MINIMUM_EXPERIMENT_DURATION
    return ExperimentResultStatus.ELIGIBLE_FOR_DECISION if duration_ok else ExperimentResultStatus.DIRECTIONAL_RESULT


async def compute_experiment_results(db: AsyncSession, experiment_id: str) -> ExperimentResultsResponse:
    experiment = await get_experiment(db, experiment_id)
    if experiment is None:
        raise RankingExperimentNotFoundError(experiment_id)
    events = await _fetch_experiment_events(db, experiment_id)
    control_metrics = _group_metrics(events, "control", experiment.control_ranking_version)
    variant_metrics = _group_metrics(events, "variant", experiment.variant_ranking_version)
    guardrail_findings = await evaluate_guardrails(db, experiment)
    result_status = classify_experiment_result(experiment, control_metrics.selections, variant_metrics.selections, guardrail_findings)
    return ExperimentResultsResponse(
        experiment_id=experiment.id, status=ExperimentStatus(experiment.status), result_status=result_status,
        minimum_sample_size=experiment.minimum_sample_size, control=control_metrics, variant=variant_metrics,
        guardrail_findings=guardrail_findings,
    )
