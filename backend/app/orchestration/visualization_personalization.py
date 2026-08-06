"""V10 — consent-based personalized visualization ranking.

Reads the SAME privacy-safe VisualizationTelemetryEvent rows V4-V9 already
record (no new raw-content event table — the allow-listed columns on that
table already structurally exclude query text, answer text, chart values,
and everything else PERSONALIZATION SIGNALS forbids) and aggregates them,
per (tenant_id, actor_id), into a small learned VisualizationPersonalizationProfile
— never individual query-level behavior, only summary preference
dictionaries and confidence scores (see compute_profile_for_actor).

Two responsibilities, deliberately kept separate:
  1. Profile computation/recomputation (this module, batch, idempotent,
     mirrors evidence_monitoring.py's V8.5 run-lifecycle pattern exactly —
     a "running" row is written before work starts, then updated to
     "succeeded"/"failed" in place; failures record only a closed, safe
     FailureCategory, never a raw exception).
  2. Read-time hint resolution (resolve_personalization_hint), consulted
     once per Ask Kriton request, exactly like V7's resolve_experiment_context
     and V8's get_preferences — fails safe to None on any problem (missing
     consent, insufficient evidence, stale profile, disabled), which makes
     the caller (presentation.py) fall through to the ordinary deterministic
     V9 result with no special-casing required on its part.

Personalization NEVER decides chart_type on its own. It hands
presentation_dataprofile.py a small, bounded nudge — a preferred chart type
per (intent, chart_family) plus small per-chart-type score boosts — that can
only reorder or tie-break among candidates the registry has already deemed
compatible. See presentation_dataprofile.py's own docstring additions for
exactly how that bound is enforced.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import DataError, InterfaceError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration.models import (
    VisualizationPersonalizationConsent,
    VisualizationPersonalizationProfile,
    VisualizationPersonalizationRecomputationRun,
    VisualizationTelemetryEvent,
)
from app.orchestration.visualization_personalization_consent import (
    HISTORY_WINDOW_DAYS,
    PersonalizationConsent,
    get_consent,
)

PERSONALIZATION_MODEL_VERSION = "personalization-1.0"
RECOMPUTATION_ACTOR = "system:visualization-personalization"

# Requirement: "Do not personalize from one or two actions."
MIN_INTERACTIONS = 10
MIN_CONVERSATIONS = 3
MIN_DAYS_OBSERVED = 7
# A family/intent's OWN preference signal must clear this confidence bar
# before it is used at all — separate from (and in addition to) the
# profile-wide minimum-evidence gate above; a profile can meet the overall
# thresholds while still having individual signals too thin/mixed to act on.
MIN_SIGNAL_CONFIDENCE = 0.6
# A profile older than this is treated as stale (falls back to the ordinary
# V9 result) rather than applied — matches the FALLBACK requirement list.
# Generous relative to a daily recompute cadence so a single missed/retried
# scheduled run doesn't flip every eligible user back to "collecting".
PROFILE_STALE_AFTER = timedelta(days=3)

Environment = Literal["production", "staging", "development", "test"]


class FailureCategory(str, Enum):
    """Closed set — mirrors evidence_monitoring.FailureCategory (V8.5).
    Duplicated rather than imported: these are two independently-scheduled
    features and must not develop a coupling neither one asked for."""
    TRANSIENT_INFRA_ERROR = "transient_infra_error"
    VALIDATION_ERROR = "validation_error"
    AUTHORIZATION_ERROR = "authorization_error"
    SCHEMA_ERROR = "schema_error"
    UNKNOWN_ERROR = "unknown_error"


_TRANSIENT_EXCEPTION_TYPES = (OperationalError, InterfaceError, TimeoutError, ConnectionError)
_SCHEMA_EXCEPTION_TYPES = (ProgrammingError, DataError, LookupError)
_TRANSIENT_CATEGORIES = {FailureCategory.TRANSIENT_INFRA_ERROR.value}


def is_transient_failure_category(category: str | None) -> bool:
    return category in _TRANSIENT_CATEGORIES


def _classify_failure(exc: BaseException) -> str:
    """Never returns or is passed str(exc) — this module never stores raw
    exceptions or event content in operational logs (requirement 6)."""
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
    """Raised when recomputation is requested for a tenant that already has
    a status="running" row for the current processing_date."""


# ── pure, deterministic profile computation ─────────────────────────────────

@dataclass(frozen=True)
class _Interaction:
    query_id: str
    conversation_id: str | None
    analytical_intent: str | None
    chart_family: str | None
    final_chart_type: str | None
    created_at: datetime
    table_opened: bool
    exported: bool
    saved: bool


@dataclass(frozen=True)
class ProfileComputation:
    interaction_count: int
    conversation_count: int
    evidence_window_start: date | None
    evidence_window_end: date | None
    days_observed: int
    chart_family_preferences: dict[str, dict[str, float]]
    intent_chart_preferences: dict[str, dict[str, float]]
    table_preference_signal: float | None
    confidence_by_signal: dict[str, float]
    meets_minimum_evidence: bool


def _group_by_query(events: list[VisualizationTelemetryEvent]) -> dict[str, list[VisualizationTelemetryEvent]]:
    groups: dict[str, list[VisualizationTelemetryEvent]] = {}
    for event in events:
        if not event.query_id:
            continue
        groups.setdefault(event.query_id, []).append(event)
    return groups


def _build_interactions(events: list[VisualizationTelemetryEvent], consent: PersonalizationConsent) -> list[_Interaction]:
    """One _Interaction per query_id — the SAME representative-instance
    convention visualization_analytics.py already uses (earliest
    visualization_selected row per query_id). Learning-source gating is
    applied HERE, at aggregation time: a disabled allow_*_learning toggle
    makes that signal type invisible to the computed interaction, even
    though the underlying telemetry event itself is still recorded (for
    other purposes, e.g. V6 recommendation-quality reporting) — this is
    what makes "switching once must not immediately alter the profile" and
    "opt-out stops learning" both true by construction, not by a separate
    live-blocking check."""
    interactions: list[_Interaction] = []
    for query_id, group in _group_by_query(events).items():
        selected = next((e for e in sorted(group, key=lambda e: e.created_at) if e.event_name == "visualization_selected"), None)
        if selected is None:
            continue
        final_type = selected.active_chart_type
        if consent.allow_view_switch_learning:
            switches = [e for e in group if e.event_name == "alternative_view_selected"]
            if switches:
                final_type = max(switches, key=lambda e: e.created_at).active_chart_type
        exported = consent.allow_export_learning and any(
            e.event_name in ("visualization_exported_png", "visualization_exported_csv") for e in group
        )
        saved = consent.allow_save_learning and any(e.event_name == "visualization_saved" for e in group)
        table_opened = any(e.event_name == "table_view_opened" for e in group)
        interactions.append(_Interaction(
            query_id=query_id, conversation_id=selected.conversation_id,
            analytical_intent=selected.analytical_intent, chart_family=selected.chart_family,
            final_chart_type=final_type, created_at=selected.created_at,
            table_opened=table_opened, exported=exported, saved=saved,
        ))
    return interactions


def _preference_distribution(counter: Counter[str], sample_size: int) -> tuple[dict[str, float], float]:
    """Normalized 0-1 share per chart_type, plus a confidence score that
    requires BOTH a real majority AND enough samples — a 2/2 unanimous
    split is not confident, and a 40/100 plurality alone is not either."""
    total = sum(counter.values())
    if total == 0:
        return {}, 0.0
    distribution = {chart_type: count / total for chart_type, count in counter.items()}
    top_share = max(distribution.values())
    sample_factor = min(1.0, sample_size / MIN_INTERACTIONS)
    confidence = top_share * sample_factor
    return distribution, confidence


def compute_profile(events: list[VisualizationTelemetryEvent], consent: PersonalizationConsent) -> ProfileComputation:
    """Pure and deterministic: the SAME event list and consent always
    produce the SAME profile (requirement: "same profile and input produce
    the same result" / "rankings remain deterministic")."""
    interactions = _build_interactions(events, consent)
    interaction_count = len(interactions)
    conversation_count = len({i.conversation_id for i in interactions if i.conversation_id})
    dates = [i.created_at.date() for i in interactions]
    window_start = min(dates) if dates else None
    window_end = max(dates) if dates else None
    days_observed = (window_end - window_start).days if window_start and window_end else 0

    family_counters: dict[str, Counter[str]] = {}
    intent_counters: dict[str, Counter[str]] = {}
    for interaction in interactions:
        if not interaction.final_chart_type:
            continue
        if interaction.chart_family:
            family_counters.setdefault(interaction.chart_family, Counter())[interaction.final_chart_type] += 1
        if interaction.analytical_intent:
            intent_counters.setdefault(interaction.analytical_intent, Counter())[interaction.final_chart_type] += 1

    chart_family_preferences: dict[str, dict[str, float]] = {}
    intent_chart_preferences: dict[str, dict[str, float]] = {}
    confidence_by_signal: dict[str, float] = {}
    for family, counter in family_counters.items():
        distribution, confidence = _preference_distribution(counter, interaction_count)
        chart_family_preferences[family] = distribution
        confidence_by_signal[f"family:{family}"] = confidence
    for intent, counter in intent_counters.items():
        distribution, confidence = _preference_distribution(counter, interaction_count)
        intent_chart_preferences[intent] = distribution
        confidence_by_signal[f"intent:{intent}"] = confidence

    table_eligible = [i for i in interactions]
    table_preference_signal = (
        sum(1 for i in table_eligible if i.table_opened) / len(table_eligible) if table_eligible else None
    )

    meets_minimum_evidence = (
        interaction_count >= MIN_INTERACTIONS
        and conversation_count >= MIN_CONVERSATIONS
        and days_observed >= MIN_DAYS_OBSERVED
    )

    return ProfileComputation(
        interaction_count=interaction_count, conversation_count=conversation_count,
        evidence_window_start=window_start, evidence_window_end=window_end, days_observed=days_observed,
        chart_family_preferences=chart_family_preferences, intent_chart_preferences=intent_chart_preferences,
        table_preference_signal=table_preference_signal, confidence_by_signal=confidence_by_signal,
        meets_minimum_evidence=meets_minimum_evidence,
    )


# ── recomputation (batch, idempotent, run-lifecycle bookkeeping) ───────────

class RecomputationRunResult(BaseModel):
    tenant_id: str
    started_at: datetime
    completed_at: datetime | None
    status: Literal["running", "succeeded", "failed"]
    processing_date: str
    profile_version: str
    profiles_recomputed_count: int
    event_count: int
    failure_category: str | None


async def _fetch_actor_events(
    db: AsyncSession, tenant_id: str, actor_id: str, window_start: datetime, environment: Environment,
) -> list[VisualizationTelemetryEvent]:
    result = await db.execute(
        select(VisualizationTelemetryEvent).where(
            VisualizationTelemetryEvent.tenant_id == tenant_id,
            VisualizationTelemetryEvent.actor_id == actor_id,
            VisualizationTelemetryEvent.environment == environment,
            VisualizationTelemetryEvent.created_at >= window_start,
        )
    )
    return list(result.scalars().all())


async def recompute_tenant_profiles(
    db: AsyncSession, tenant_id: str, *, triggered_by: str = RECOMPUTATION_ACTOR, environment: Environment = "production",
) -> RecomputationRunResult:
    """The external-scheduled-job-or-explicitly-invoked service itself
    (requirement: recompute through an external job, never an in-process
    loop). Idempotent per (tenant_id, processing_date): a retried/duplicate
    call for a tenant that already succeeded today returns that prior
    outcome unchanged; one that finds a "running" row raises
    MonitoringRunAlreadyActiveError instead of racing it — identical
    contract to evidence_monitoring.run_evidence_monitoring (V8.5).

    Recomputes only for actors with active consent (personalization_enabled
    = True) — requirement 3."""
    started_at = datetime.now(timezone.utc)
    processing_date = started_at.date().isoformat()

    existing_run = await db.scalar(
        select(VisualizationPersonalizationRecomputationRun)
        .where(
            VisualizationPersonalizationRecomputationRun.tenant_id == tenant_id,
            VisualizationPersonalizationRecomputationRun.processing_date == processing_date,
        )
        .order_by(VisualizationPersonalizationRecomputationRun.started_at.desc())
        .limit(1)
    )
    if existing_run is not None and existing_run.status == "running":
        raise MonitoringRunAlreadyActiveError(tenant_id)
    if existing_run is not None and existing_run.status == "succeeded":
        return _run_result_from_row(existing_run)

    run_row = VisualizationPersonalizationRecomputationRun(
        tenant_id=tenant_id, started_at=started_at, status="running", processing_date=processing_date,
        profile_version=PERSONALIZATION_MODEL_VERSION, profiles_recomputed_count=0, event_count=0,
        failure_category=None, triggered_by=triggered_by,
    )
    db.add(run_row)
    await db.commit()
    await db.refresh(run_row)

    try:
        consented = (await db.execute(
            select(VisualizationPersonalizationConsent).where(
                VisualizationPersonalizationConsent.tenant_id == tenant_id,
                VisualizationPersonalizationConsent.personalization_enabled.is_(True),
            )
        )).scalars().all()

        profiles_recomputed = 0
        total_events = 0
        for consent_row in consented:
            consent = PersonalizationConsent(
                personalization_enabled=consent_row.personalization_enabled,
                personalization_scope=consent_row.personalization_scope,
                personalization_history_window=consent_row.personalization_history_window,
                allow_view_switch_learning=consent_row.allow_view_switch_learning,
                allow_export_learning=consent_row.allow_export_learning,
                allow_save_learning=consent_row.allow_save_learning,
                consent_updated_at=consent_row.consent_updated_at,
            )
            window_days = HISTORY_WINDOW_DAYS[consent.personalization_history_window]
            window_start = started_at - timedelta(days=window_days)
            events = await _fetch_actor_events(db, tenant_id, consent_row.actor_id, window_start, environment)
            total_events += len(events)
            computation = compute_profile(events, consent)
            await _upsert_profile(db, tenant_id, consent_row.actor_id, consent, computation)
            profiles_recomputed += 1

        run_row.status = "succeeded"
        run_row.completed_at = datetime.now(timezone.utc)
        run_row.profiles_recomputed_count = profiles_recomputed
        run_row.event_count = total_events
        await db.commit()
        await db.refresh(run_row)
        return _run_result_from_row(run_row)
    except Exception as exc:
        await db.rollback()
        category = _classify_failure(exc)
        run_row.status = "failed"
        run_row.completed_at = datetime.now(timezone.utc)
        run_row.failure_category = category
        await db.commit()
        await db.refresh(run_row)
        return _run_result_from_row(run_row)


async def _upsert_profile(
    db: AsyncSession, tenant_id: str, actor_id: str, consent: PersonalizationConsent, computation: ProfileComputation,
) -> None:
    now = datetime.now(timezone.utc)
    row = await db.scalar(select(VisualizationPersonalizationProfile).where(
        VisualizationPersonalizationProfile.tenant_id == tenant_id,
        VisualizationPersonalizationProfile.actor_id == actor_id,
    ))
    fields = dict(
        schema_version=PERSONALIZATION_MODEL_VERSION,
        consent_status="enabled" if consent.personalization_enabled else "disabled",
        consent_updated_at=consent.consent_updated_at or now,
        evidence_window_start=computation.evidence_window_start,
        evidence_window_end=computation.evidence_window_end,
        interaction_count=computation.interaction_count,
        conversation_count=computation.conversation_count,
        chart_family_preferences=computation.chart_family_preferences,
        intent_chart_preferences=computation.intent_chart_preferences,
        table_preference_signal=computation.table_preference_signal,
        density_preference_signal=None,
        confidence_by_signal=computation.confidence_by_signal,
        last_recomputed_at=now,
    )
    if row is not None:
        for key, val in fields.items():
            setattr(row, key, val)
    else:
        db.add(VisualizationPersonalizationProfile(tenant_id=tenant_id, actor_id=actor_id, **fields))
    await db.commit()


def _run_result_from_row(row: VisualizationPersonalizationRecomputationRun) -> RecomputationRunResult:
    return RecomputationRunResult(
        tenant_id=row.tenant_id, started_at=row.started_at, completed_at=row.completed_at, status=row.status,
        processing_date=row.processing_date, profile_version=row.profile_version,
        profiles_recomputed_count=row.profiles_recomputed_count, event_count=row.event_count,
        failure_category=row.failure_category,
    )


async def reset_learned_profile(db: AsyncSession, tenant_id: str, actor_id: str) -> None:
    """DATA RETENTION requirement 3: reset removes the learned profile —
    consent settings are untouched, so the next recomputation starts
    learning fresh from whatever evidence remains in the retention window."""
    row = await db.scalar(select(VisualizationPersonalizationProfile).where(
        VisualizationPersonalizationProfile.tenant_id == tenant_id,
        VisualizationPersonalizationProfile.actor_id == actor_id,
    ))
    if row is not None:
        await db.delete(row)
        await db.commit()


# ── read-time hint resolution ───────────────────────────────────────────────

@dataclass(frozen=True)
class PersonalizationHint:
    chart_family_preferences: dict[str, dict[str, float]]
    intent_chart_preferences: dict[str, dict[str, float]]
    confidence_by_signal: dict[str, float]
    model_version: str
    interaction_count: int = 0


@dataclass(frozen=True)
class PersonalizationSummary:
    """Privacy-safe: counts and chart-type LABELS only (chart type names are
    product vocabulary, not user content) — never query text, values, or
    any other prohibited field. Backs "View personalization summary" and the
    example sentence in USER CONTROLS."""
    eligible: bool
    interaction_count: int
    conversation_count: int
    top_family_preferences: dict[str, str] = field(default_factory=dict)
    top_intent_preferences: dict[str, str] = field(default_factory=dict)


async def resolve_personalization_hint(db: AsyncSession, tenant_id: str, actor_id: str) -> PersonalizationHint | None:
    """Called once per Ask Kriton request (mirrors resolve_experiment_context
    and get_preferences). Fails safe to None — disabled consent, no profile,
    below evidence threshold, or a stale profile all return None, and
    presentation.py's existing ordinary-ranking path handles None exactly
    like "no personalization ever existed"."""
    consent = await get_consent(db, tenant_id, actor_id)
    if not consent.personalization_enabled:
        return None
    row = await db.scalar(select(VisualizationPersonalizationProfile).where(
        VisualizationPersonalizationProfile.tenant_id == tenant_id,
        VisualizationPersonalizationProfile.actor_id == actor_id,
    ))
    if row is None:
        return None
    if row.interaction_count < MIN_INTERACTIONS or row.conversation_count < MIN_CONVERSATIONS:
        return None
    if row.evidence_window_start and row.evidence_window_end:
        if (row.evidence_window_end - row.evidence_window_start).days < MIN_DAYS_OBSERVED:
            return None
    now = datetime.now(timezone.utc)
    last_recomputed = row.last_recomputed_at
    if last_recomputed.tzinfo is None:
        last_recomputed = last_recomputed.replace(tzinfo=timezone.utc)
    if now - last_recomputed > PROFILE_STALE_AFTER:
        return None
    return PersonalizationHint(
        chart_family_preferences=row.chart_family_preferences or {},
        intent_chart_preferences=row.intent_chart_preferences or {},
        confidence_by_signal=row.confidence_by_signal or {},
        model_version=row.schema_version,
        interaction_count=row.interaction_count,
    )


def personalization_hint_for_chart(
    hint: PersonalizationHint | None, intent: str, chart_family: str | None,
) -> tuple[str | None, dict[str, float], str | None]:
    """Pure — extracts the (preferred_chart_type, boosts, confidence_band)
    for THIS specific chart's (intent, family), from the whole-profile
    hint resolved once per request. Only a signal whose OWN confidence
    clears MIN_SIGNAL_CONFIDENCE is used, independent of whether the
    profile as a whole met the aggregate evidence thresholds."""
    if hint is None:
        return None, {}, None
    boosts: dict[str, float] = {}
    best_confidence = 0.0
    preferred: str | None = None

    intent_distribution = hint.intent_chart_preferences.get(intent)
    intent_confidence = hint.confidence_by_signal.get(f"intent:{intent}", 0.0)
    if intent_distribution and intent_confidence >= MIN_SIGNAL_CONFIDENCE:
        for chart_type, share in intent_distribution.items():
            boosts[chart_type] = max(boosts.get(chart_type, 0.0), share)
        top_type = max(intent_distribution, key=intent_distribution.get)
        if intent_confidence > best_confidence:
            preferred, best_confidence = top_type, intent_confidence

    if chart_family:
        family_distribution = hint.chart_family_preferences.get(chart_family)
        family_confidence = hint.confidence_by_signal.get(f"family:{chart_family}", 0.0)
        if family_distribution and family_confidence >= MIN_SIGNAL_CONFIDENCE:
            for chart_type, share in family_distribution.items():
                boosts[chart_type] = max(boosts.get(chart_type, 0.0), share)
            top_type = max(family_distribution, key=family_distribution.get)
            if family_confidence > best_confidence:
                preferred, best_confidence = top_type, family_confidence

    if preferred is None:
        return None, {}, None
    band = "high" if best_confidence >= 0.85 else "medium" if best_confidence >= 0.7 else "low"
    return preferred, boosts, band


async def build_personalization_summary(db: AsyncSession, tenant_id: str, actor_id: str) -> PersonalizationSummary:
    """Backs the "View personalization summary" control — deliberately
    returns chart-type labels and counts only, never event history
    (requirement: "Do not expose detailed event history")."""
    consent = await get_consent(db, tenant_id, actor_id)
    row = await db.scalar(select(VisualizationPersonalizationProfile).where(
        VisualizationPersonalizationProfile.tenant_id == tenant_id,
        VisualizationPersonalizationProfile.actor_id == actor_id,
    ))
    if row is None or not consent.personalization_enabled:
        return PersonalizationSummary(eligible=False, interaction_count=row.interaction_count if row else 0, conversation_count=row.conversation_count if row else 0)
    eligible = row.interaction_count >= MIN_INTERACTIONS and row.conversation_count >= MIN_CONVERSATIONS
    top_family = {
        family: max(dist, key=dist.get) for family, dist in (row.chart_family_preferences or {}).items()
        if dist and row.confidence_by_signal.get(f"family:{family}", 0.0) >= MIN_SIGNAL_CONFIDENCE
    }
    top_intent = {
        intent: max(dist, key=dist.get) for intent, dist in (row.intent_chart_preferences or {}).items()
        if dist and row.confidence_by_signal.get(f"intent:{intent}", 0.0) >= MIN_SIGNAL_CONFIDENCE
    }
    return PersonalizationSummary(
        eligible=eligible, interaction_count=row.interaction_count, conversation_count=row.conversation_count,
        top_family_preferences=top_family, top_intent_preferences=top_intent,
    )
