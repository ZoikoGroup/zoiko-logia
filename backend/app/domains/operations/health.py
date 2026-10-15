"""Status & Health page: live checks plus the measured history behind them.

Every number comes from a check run now or a stored sample
(service_health_samples). With no history yet, the history fields are empty
and the page says so; nothing is extrapolated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_engine
from app.domains.identity.models import User
from app.domains.operations import service as operations
from app.domains.operations import telemetry
from app.domains.operations.models import OperationsAlert, ServiceHealthSample, ServiceOwner

ACTIVE_ALERT_STATES = ("unacknowledged", "acknowledged", "investigating", "contained")
STUCK_UPLOAD_MINUTES = 15

# What depends on what, from how the code calls each service. Drawn as the
# dependency map; a down leaf marks every node above it as impacted.
DEPENDENCIES = {
    "api": ["database", "supabase_auth", "ai_models", "searxng", "kroki", "redis"],
    "ai_models": ["groq", "google", "openai", "anthropic"],
}
DEPENDENCY_LABELS = {"ai_models": "AI model providers"}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _percentile(values: list[float], pct: float) -> float | None:
    return telemetry._percentile([v for v in values if v is not None], pct)


def _is_up(state: str) -> bool:
    return state in {"operational", "degraded"}


async def _live_checks(db: AsyncSession, tenant_id: str, now: datetime) -> list[dict]:
    interval = get_settings().HEALTH_SAMPLE_INTERVAL_SECONDS
    checks = [telemetry.api_summary(interval), *await operations.dependency_checks(db)]
    latest = await telemetry.latest_sample_at(db)
    if latest is None or (now - latest).total_seconds() >= telemetry.PAGE_SAMPLE_MIN_SECONDS:
        await telemetry.record_samples(db, checks, now)
    return [*checks, await operations.audit_chain_check(db, tenant_id)]


async def _document_jobs(tenant_id: str, now: datetime) -> dict:
    """Document processing for the whole workspace. workspace_documents RLS
    shows a user only their own files, so this one aggregate (counts only, no
    content) runs on the setup connection, filtered to this tenant."""
    stuck_before = now - timedelta(minutes=STUCK_UPLOAD_MINUTES)
    try:
        async with async_engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT "
                "count(*) FILTER (WHERE status = 'PROCESSING' AND created_at < :stuck) AS stuck, "
                "count(*) FILTER (WHERE status = 'PROCESSING') AS processing, "
                "count(*) FILTER (WHERE status = 'FAILED' AND created_at >= :day) AS failed "
                "FROM workspace_documents WHERE tenant_id = :tenant"
            ), {"tenant": tenant_id, "stuck": stuck_before, "day": now - timedelta(days=1)})).one()
        return {"available": True, "stuck": row.stuck, "processing": row.processing, "failed24h": row.failed}
    except Exception:  # noqa: BLE001 — SQLite (no FILTER on old versions) or DB fault
        return {"available": False, "stuck": 0, "processing": 0, "failed24h": 0}


def _hourly(samples: list[ServiceHealthSample], now: datetime) -> list[dict]:
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    buckets: dict[int, list[ServiceHealthSample]] = defaultdict(list)
    for s in samples:
        index = int((_aware(s.checked_at) - start).total_seconds() // 3600)
        if 0 <= index < 24:
            buckets[index].append(s)
    hours = []
    for i in range(24):
        rows = buckets.get(i, [])
        checked = [r for r in rows if r.state != "not_configured"]
        api = [r for r in rows if r.service_key == "api" and r.requests]
        hours.append({
            "hour": (start + timedelta(hours=i)).isoformat(),
            "availability": round(100 * sum(_is_up(r.state) for r in checked) / len(checked), 2) if checked else None,
            "p50": round(sum(r.p50_ms for r in api if r.p50_ms is not None) / len(api)) if api else None,
            "p95": round(max(r.latency_ms for r in api if r.latency_ms is not None)) if api else None,
        })
    return hours


def _events(samples: list[ServiceHealthSample]) -> list[dict]:
    """State changes, newest first: a service going down, degrading or recovering."""
    by_service: dict[str, list[ServiceHealthSample]] = defaultdict(list)
    for s in samples:
        by_service[s.service_key].append(s)
    events = []
    for key, rows in by_service.items():
        rows.sort(key=lambda r: _aware(r.checked_at))
        for previous, current in zip(rows, rows[1:]):
            if previous.state != current.state:
                events.append({"at": _aware(current.checked_at).isoformat(), "serviceKey": key,
                               "service": operations.SERVICE_NAMES.get(key, key),
                               "from": previous.state, "to": current.state, "detail": current.detail})
    return sorted(events, key=lambda e: e["at"], reverse=True)[:50]


def _dependency_map(live: dict[str, dict]) -> dict:
    def state_of(key: str) -> str:
        if key in DEPENDENCIES:
            children = [state_of(c) for c in DEPENDENCIES[key]]
            configured = [c for c in children if c != "not_configured"]
            own = live.get(key, {}).get("state", "operational")
            if not configured and key == "ai_models":
                return "down"
            if own == "down" or any(c == "down" for c in configured):
                return "impacted" if own != "down" else "down"
            return "degraded" if own == "degraded" or "degraded" in configured else "operational"
        return live.get(key, {}).get("state", "not_configured")

    def node(key: str) -> dict:
        return {"key": key, "name": DEPENDENCY_LABELS.get(key) or operations.SERVICE_NAMES.get(key, key),
                "state": state_of(key), "children": [node(c) for c in DEPENDENCIES.get(key, [])]}

    return node("api")


async def _slo(db: AsyncSession, now: datetime) -> list[dict]:
    """30-day availability per service against the configured objective."""
    objective = get_settings().OPS_AVAILABILITY_OBJECTIVE_PCT
    up = func.sum(case((ServiceHealthSample.state.in_(("operational", "degraded")), 1), else_=0))
    rows = (await db.execute(
        select(ServiceHealthSample.service_key, func.count(), up)
        .where(ServiceHealthSample.checked_at >= now - timedelta(days=30),
               ServiceHealthSample.state != "not_configured")
        .group_by(ServiceHealthSample.service_key)
    )).all()
    out = []
    for key, total, ups in rows:
        availability = 100 * (ups or 0) / total
        allowed = 100 - objective
        used = 100 - availability
        out.append({"key": key, "name": operations.SERVICE_NAMES.get(key, key), "samples": total,
                    "availability": round(availability, 3), "objective": objective,
                    "budgetRemainingPct": round(max(0.0, 100 * (1 - used / allowed)), 1) if allowed > 0 else None,
                    "met": availability >= objective})
    return sorted(out, key=lambda r: r["availability"])


async def build_status(db: AsyncSession, user: User, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    settings = get_settings()
    checks = await _live_checks(db, user.tenant_id, now)
    live = {c["key"]: c for c in checks}

    samples = list((await db.execute(
        select(ServiceHealthSample).where(ServiceHealthSample.checked_at >= now - timedelta(hours=24))
    )).scalars().all())
    by_service: dict[str, list[ServiceHealthSample]] = defaultdict(list)
    for s in samples:
        by_service[s.service_key].append(s)

    owners = {o.service_key: o.owner_user_id for o in (await db.execute(
        select(ServiceOwner).where(ServiceOwner.tenant_id == user.tenant_id))).scalars().all()}
    owner_names = {u.id: u.full_name or u.email for u in (await db.execute(
        select(User).where(User.tenant_id == user.tenant_id, User.id.in_(list(owners.values()) or [""]))
    )).scalars().all()}
    alerts = (await db.execute(
        select(OperationsAlert.service_key, OperationsAlert.ref, OperationsAlert.state)
        .where(OperationsAlert.tenant_id == user.tenant_id, OperationsAlert.state.in_(ACTIVE_ALERT_STATES))
    )).all()
    alerts_by_service: dict[str, list[dict]] = defaultdict(list)
    for service_key, ref, state in alerts:
        if service_key:
            alerts_by_service[service_key].append({"ref": ref, "state": state})

    services = []
    for key, name, component, category in operations.SERVICES:
        check = live.get(key)
        history = [s for s in by_service.get(key, []) if s.state != "not_configured"]
        if check is None or (check["state"] == "not_configured" and not history):
            continue
        availability = (round(100 * sum(_is_up(s.state) for s in history) / len(history), 2) if history else None)
        services.append({
            "key": key, "name": name, "component": component, "category": category,
            "location": operations.service_location(key), "state": check["state"],
            "latencyMs": check["latencyMs"], "detail": check["detail"],
            "availability24h": availability, "samples24h": len(history),
            "p95LatencyMs24h": (round(_percentile([s.latency_ms for s in history], 95))
                                if any(s.latency_ms is not None for s in history) else None),
            "errorRate24h": (round(100 * sum(s.errors or 0 for s in history) / max(1, sum(s.requests or 0 for s in history)), 2)
                             if key == "api" and history else None),
            "lastSampleAt": max((_aware(s.checked_at) for s in by_service.get(key, [])), default=None),
            "ownerId": owners.get(key), "owner": owner_names.get(owners.get(key, ""), None),
            "openAlerts": alerts_by_service.get(key, []),
            "dependsOn": DEPENDENCIES.get(key, []),
        })
    audit = live["audit_ledger"]
    services.append({"key": "audit_ledger", "name": audit["name"], "component": "Hash-chained audit events",
                     "category": "Evidence", "location": "Database", "state": audit["state"],
                     "latencyMs": None, "detail": audit["detail"], "availability24h": None, "samples24h": 0,
                     "p95LatencyMs24h": None, "errorRate24h": None, "lastSampleAt": None,
                     "ownerId": owners.get("audit_ledger"), "owner": owner_names.get(owners.get("audit_ledger", ""), None),
                     "openAlerts": alerts_by_service.get("audit_ledger", []), "dependsOn": []})
    for s in services:
        if s["lastSampleAt"] is not None:
            s["lastSampleAt"] = s["lastSampleAt"].isoformat()

    configured = [s for s in services if s["state"] != "not_configured"]
    down = [s for s in configured if s["state"] == "down"]
    degraded = [s for s in configured if s["state"] == "degraded"]
    platform_state = ("down" if any(s["key"] in operations.CORE_SERVICES for s in down)
                      else "degraded" if down or degraded else "operational")
    checked = [s for s in samples if s.state != "not_configured"]
    api_history = [s for s in by_service.get("api", []) if s.requests]
    jobs = await _document_jobs(user.tenant_id, now)
    latest = await telemetry.latest_sample_at(db)

    return {
        "checkedAt": now.isoformat(),
        "summary": {
            "platformState": platform_state,
            "impacted": [s["name"] for s in down + degraded],
            "availability24h": round(100 * sum(_is_up(s.state) for s in checked) / len(checked), 2) if checked else None,
            "availabilityObjective": settings.OPS_AVAILABILITY_OBJECTIVE_PCT,
            "apiP95Ms": (round(_percentile([s.latency_ms for s in api_history], 95))
                         if any(s.latency_ms is not None for s in api_history) else None),
            "apiP95ObjectiveMs": settings.OPS_API_P95_OBJECTIVE_MS,
            "activeAlerts": len(alerts),
            "unavailable": len(down),
            "blockedJobs": jobs["stuck"] + jobs["failed24h"],
        },
        "services": services,
        "hourly": _hourly(samples, now),
        "dependencyMap": _dependency_map(live),
        "events": _events(samples),
        "slo": await _slo(db, now),
        "jobs": {
            "sampler": {"enabled": settings.HEALTH_SAMPLER_ENABLED,
                        "intervalSeconds": settings.HEALTH_SAMPLE_INTERVAL_SECONDS,
                        "retentionDays": settings.HEALTH_SAMPLE_RETENTION_DAYS,
                        "lastSampleAt": latest.isoformat() if latest else None},
            "documents": jobs,
            "queue": live.get("redis", {"state": "not_configured", "detail": "Not configured"}),
        },
    }
