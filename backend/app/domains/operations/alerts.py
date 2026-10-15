"""Alerts Center: operational alerts with an owner and a lifecycle.

Alerts are raised automatically from live conditions (the Governance
Dashboard's exceptions and dependencies that are down) or by hand. Each
condition maps to one alert row (source_key), so its detection time, owner
and history survive between views. When a condition clears the alert resolves
itself; if it recurs the same alert reopens. Every action is audited.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import ServiceAccount, User
from app.domains.operations import service as operations
from app.domains.operations.health import ACTIVE_ALERT_STATES
from app.domains.operations.models import OperationsAlert, ServiceHealthSample

SEVERITIES = ("Critical", "High", "Medium", "Low")
_RANK = {s: i for i, s in enumerate(SEVERITIES)}
STATES = ("unacknowledged", "acknowledged", "investigating", "contained", "resolved", "suppressed")
# A dependency sampled down within this window is a live condition.
HEALTH_CONDITION_WINDOW = timedelta(minutes=15)

# Governance Dashboard domain → alert category.
_CATEGORY = {
    "AI Safety & Risk Controls": "AI safety",
    "Source & Knowledge Governance": "Source governance",
    "Evaluation & Release Readiness": "AI governance",
    "Human Accountability": "Review & accountability",
    "Audit & Incident Readiness": "Security & incidents",
}


class AlertActionError(ValueError):
    """An action the alert's state or the actor's role does not allow."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def governance_conditions(exceptions: list[dict]) -> list[dict]:
    return [{
        "source_key": f"gov:{e['id']}", "origin": "governance",
        "category": _CATEGORY.get(e.get("domain", ""), e.get("domain") or "Governance"),
        "severity": e["severity"] if e.get("severity") in _RANK else "Medium",
        "title": e["title"], "detail": e.get("detail", ""), "href": e.get("href", ""), "service_key": None,
    } for e in exceptions]


async def health_conditions(db: AsyncSession, now: datetime) -> list[dict]:
    """Dependencies whose latest sample (within the window) is down."""
    latest = (
        select(ServiceHealthSample.service_key, func.max(ServiceHealthSample.checked_at).label("at"))
        .where(ServiceHealthSample.checked_at >= now - HEALTH_CONDITION_WINDOW)
        .group_by(ServiceHealthSample.service_key).subquery()
    )
    rows = (await db.execute(
        select(ServiceHealthSample).join(
            latest, (ServiceHealthSample.service_key == latest.c.service_key)
            & (ServiceHealthSample.checked_at == latest.c.at))
    )).scalars().all()
    out = []
    for s in rows:
        if s.state != "down":
            continue
        name = operations.SERVICE_NAMES.get(s.service_key, s.service_key)
        out.append({
            "source_key": f"health:{s.service_key}", "origin": "health", "category": "Platform operations",
            "severity": "Critical" if s.service_key in operations.CORE_SERVICES else "High",
            "title": f"{name} is unavailable", "detail": f"Latest health check: {s.detail or s.state}.",
            "href": "/status-health", "service_key": s.service_key,
        })
    return out


def _entry(action: str, actor: User | None, note: str = "", at: datetime | None = None) -> dict:
    return {"at": (at or _now()).isoformat(), "action": action,
            "actorId": actor.id if actor else None,
            "actor": (actor.full_name or actor.email) if actor else "System", "note": note}


async def _next_ref(db: AsyncSession, tenant_id: str, now: datetime) -> str:
    prefix = f"ALT-{now.year}-"
    count = (await db.execute(select(func.count()).select_from(OperationsAlert).where(
        OperationsAlert.tenant_id == tenant_id, OperationsAlert.ref.like(f"{prefix}%")))).scalar_one()
    return f"{prefix}{count + 1:04d}"


async def sync(db: AsyncSession, tenant_id: str, conditions: list[dict], now: datetime | None = None) -> None:
    """Bring stored alerts in line with the live conditions."""
    now = now or _now()
    for attempt in range(2):
        try:
            await _sync_once(db, tenant_id, conditions, now)
            return
        except IntegrityError:
            # Another request raised the same alert (or ref) at the same moment.
            await db.rollback()
            if attempt:
                raise


async def _sync_once(db: AsyncSession, tenant_id: str, conditions: list[dict], now: datetime) -> None:
    existing = {a.source_key: a for a in (await db.execute(
        select(OperationsAlert).where(OperationsAlert.tenant_id == tenant_id, OperationsAlert.origin != "manual")
    )).scalars().all()}
    present = set()
    changed = False
    for c in conditions:
        present.add(c["source_key"])
        alert = existing.get(c["source_key"])
        if alert is None:
            db.add(OperationsAlert(
                tenant_id=tenant_id, ref=await _next_ref(db, tenant_id, now), state="unacknowledged",
                detected_at=now, last_seen_at=now, history=[_entry("detected", None, c["title"], now)],
                **c,
            ))
            await db.flush()
            changed = True
            continue
        alert.last_seen_at = now
        alert.title, alert.detail, alert.href, alert.category = c["title"], c["detail"], c["href"], c["category"]
        # A manual escalation is kept; a condition can only raise severity.
        if _RANK[c["severity"]] < _RANK.get(alert.severity, 3):
            alert.severity = c["severity"]
        if alert.state == "resolved":
            alert.state, alert.resolved_at, alert.resolved_by = "unacknowledged", None, None
            alert.acknowledged_at = alert.acknowledged_by = None
            alert.history = [*alert.history, _entry("recurred", None, "Condition detected again", now)]
        changed = True
    for key, alert in existing.items():
        if key not in present and alert.state in ACTIVE_ALERT_STATES:
            alert.state, alert.resolved_at, alert.resolved_by = "resolved", now, None
            alert.history = [*alert.history, _entry("cleared", None, "Condition no longer detected", now)]
            changed = True
    if changed:
        await db.commit()


async def _names(db: AsyncSession, tenant_id: str, ids: set[str]) -> dict[str, str]:
    ids.discard(None)  # type: ignore[arg-type]
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.tenant_id == tenant_id, User.id.in_(ids)))).scalars().all()
    return {u.id: u.full_name or u.email for u in rows}


def _view(a: OperationsAlert, names: dict[str, str]) -> dict:
    return {
        "id": a.id, "ref": a.ref, "origin": a.origin, "category": a.category, "severity": a.severity,
        "title": a.title, "detail": a.detail, "href": a.href, "serviceKey": a.service_key, "state": a.state,
        "ownerId": a.owner_user_id, "owner": names.get(a.owner_user_id or ""),
        "detectedAt": _aware(a.detected_at).isoformat(), "lastSeenAt": _aware(a.last_seen_at).isoformat(),
        "acknowledgedAt": _aware(a.acknowledged_at).isoformat() if a.acknowledged_at else None,
        "acknowledgedBy": names.get(a.acknowledged_by or ""),
        "resolvedAt": _aware(a.resolved_at).isoformat() if a.resolved_at else None,
        "resolvedBy": names.get(a.resolved_by or "") if a.resolved_by else ("System" if a.resolved_at else None),
        "history": a.history,
    }


async def list_alerts(db: AsyncSession, tenant_id: str, *, safety_blocks: int, now: datetime | None = None) -> dict:
    now = now or _now()
    rows = list((await db.execute(
        select(OperationsAlert).where(OperationsAlert.tenant_id == tenant_id,
                                      OperationsAlert.last_seen_at >= now - timedelta(days=30))
    )).scalars().all())
    ids = {a.owner_user_id for a in rows} | {a.acknowledged_by for a in rows} | {a.resolved_by for a in rows}
    for a in rows:
        ids.update(h.get("actorId") for h in a.history)
    names = await _names(db, tenant_id, {i for i in ids if i})
    active = [a for a in rows if a.state in ACTIVE_ALERT_STATES]
    rows.sort(key=lambda a: (a.state not in ACTIVE_ALERT_STATES, _RANK.get(a.severity, 3),
                             -_aware(a.detected_at).timestamp()))
    categories: dict[str, int] = {}
    for a in active:
        categories[a.category] = categories.get(a.category, 0) + 1
    return {
        "alerts": [_view(a, names) for a in rows],
        "summary": {
            "active": len(active),
            "critical": sum(a.severity == "Critical" for a in active),
            "unacknowledged": sum(a.state == "unacknowledged" for a in active),
            "unowned": sum(a.owner_user_id is None for a in active),
            "safetyBlocks": safety_blocks,
            "bySeverity": {s: sum(a.severity == s for a in active) for s in SEVERITIES},
            "byCategory": sorted(({"category": k, "count": v} for k, v in categories.items()),
                                 key=lambda c: -c["count"]),
        },
        # No notification channel (email, Slack, pager) is connected yet:
        # alerts are delivered in this console only.
        "delivery": {"channelConfigured": False, "channel": "In-app (this console)"},
        "generatedAt": now.isoformat(),
    }


async def assignees(db: AsyncSession, tenant_id: str) -> list[dict]:
    service_ids = select(ServiceAccount.id).where(ServiceAccount.tenant_id == tenant_id)
    users = (await db.execute(select(User).where(
        User.tenant_id == tenant_id, User.is_active.is_(True), User.id.not_in(service_ids)
    ).order_by(User.full_name))).scalars().all()
    return [{"id": u.id, "name": u.full_name or u.email, "role": u.role} for u in users]


async def _audit(db: AsyncSession, actor: User, event: str, alert: OperationsAlert, payload: dict) -> None:
    await record_event_async(db, tenant_id=actor.tenant_id, event_name=event, emitting_service="operations",
                             actor_id=actor.id, subject_type="operations_alert", subject_id=alert.id,
                             payload={"ref": alert.ref, **payload})


async def create_manual(db: AsyncSession, actor: User, *, title: str, severity: str, category: str,
                        detail: str, service_key: str | None) -> OperationsAlert:
    if severity not in _RANK:
        raise AlertActionError("Unknown severity")
    if service_key and service_key not in operations.SERVICE_NAMES and service_key != "audit_ledger":
        raise AlertActionError("Unknown service")
    now = _now()
    alert = OperationsAlert(
        tenant_id=actor.tenant_id, ref=await _next_ref(db, actor.tenant_id, now), origin="manual",
        source_key=f"manual:{now.timestamp()}:{actor.id}", category=category or "Platform operations",
        severity=severity, title=title, detail=detail, href="/status-health" if service_key else "",
        service_key=service_key, state="unacknowledged", created_by=actor.id, detected_at=now, last_seen_at=now,
        history=[_entry("raised", actor, title, now)],
    )
    db.add(alert)
    await db.flush()
    await _audit(db, actor, "operations_alert_raised", alert, {"severity": severity, "title": title})
    return alert


async def act(db: AsyncSession, actor: User, alert_id: str, action: str, *,
              note: str = "", owner_user_id: str | None = None, is_admin: bool = False) -> OperationsAlert:
    alert = (await db.execute(select(OperationsAlert).where(
        OperationsAlert.id == alert_id, OperationsAlert.tenant_id == actor.tenant_id))).scalar_one_or_none()
    if alert is None:
        raise LookupError("Alert not found")
    note = note.strip()
    now = _now()
    active = alert.state in ACTIVE_ALERT_STATES
    payload: dict = {"note": note}

    if action == "acknowledge":
        if alert.state != "unacknowledged":
            raise AlertActionError("Only an unacknowledged alert can be acknowledged")
        alert.state, alert.acknowledged_at, alert.acknowledged_by = "acknowledged", now, actor.id
        if alert.owner_user_id is None:
            alert.owner_user_id = actor.id
    elif action == "investigate":
        if alert.state not in {"unacknowledged", "acknowledged"}:
            raise AlertActionError("This alert is not awaiting investigation")
        if alert.acknowledged_at is None:
            alert.acknowledged_at, alert.acknowledged_by = now, actor.id
        alert.state = "investigating"
        alert.owner_user_id = alert.owner_user_id or actor.id
    elif action == "assign":
        if not owner_user_id:
            raise AlertActionError("Choose an owner")
        owner = (await db.execute(select(User).where(
            User.id == owner_user_id, User.tenant_id == actor.tenant_id, User.is_active.is_(True)))).scalar_one_or_none()
        if owner is None:
            raise AlertActionError("Owner must be an active user in this workspace")
        alert.owner_user_id = owner.id
        payload["owner"] = owner.id
    elif action == "escalate":
        if not active:
            raise AlertActionError("Only an active alert can be escalated")
        if alert.severity == "Critical":
            raise AlertActionError("Alert is already Critical")
        alert.severity = SEVERITIES[_RANK[alert.severity] - 1]
        payload["severity"] = alert.severity
    elif action == "contain":
        if alert.state not in {"acknowledged", "investigating"}:
            raise AlertActionError("Acknowledge or investigate the alert before marking it contained")
        if not note:
            raise AlertActionError("Describe the containment")
        alert.state = "contained"
    elif action == "resolve":
        if not active:
            raise AlertActionError("Only an active alert can be resolved")
        if alert.origin != "manual":
            raise AlertActionError("This alert resolves automatically when its condition clears")
        if not note:
            raise AlertActionError("A resolution note is required")
        # Separation of duties: whoever raised a manual alert cannot also close it.
        if alert.created_by == actor.id:
            raise AlertActionError("Resolution must be approved by someone other than the person who raised it")
        alert.state, alert.resolved_at, alert.resolved_by = "resolved", now, actor.id
    elif action == "suppress":
        if not is_admin:
            raise AlertActionError("Only an Admin can suppress an alert")
        if not active:
            raise AlertActionError("Only an active alert can be suppressed")
        if not note:
            raise AlertActionError("A reason is required to suppress an alert")
        alert.state = "suppressed"
    elif action == "reopen":
        if alert.state not in {"suppressed", "resolved"}:
            raise AlertActionError("Only a suppressed or resolved alert can be reopened")
        alert.state, alert.resolved_at, alert.resolved_by = "unacknowledged", None, None
    else:
        raise AlertActionError("Unknown action")

    alert.history = [*alert.history, _entry(action, actor, note, now)]
    await db.flush()
    await _audit(db, actor, f"operations_alert_{action}", alert, payload)
    return alert


async def view_one(db: AsyncSession, alert: OperationsAlert) -> dict:
    ids = {alert.owner_user_id, alert.acknowledged_by, alert.resolved_by, *(h.get("actorId") for h in alert.history)}
    return _view(alert, await _names(db, alert.tenant_id, {i for i in ids if i}))
