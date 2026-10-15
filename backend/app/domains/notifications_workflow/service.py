"""In-app notifications, built from the audit ledger.

Nothing new is emitted anywhere: every action worth telling someone about is
already an audit event. RULES maps an event to who should hear about it and
what the message says. sync_tenant() turns new events into notification rows
(once per recipient, event and kind) and runs lazily when someone checks the
bell, at most every SYNC_INTERVAL seconds per tenant, so no background worker
is needed.

"Needs your action" counts are not stored: action_items() counts the open
work for the viewer's role live, so an item disappears as soon as it is done.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import User
from app.domains.identity.permissions import (
    MODEL_MANAGE, REVIEW_RESOLVE, SAFETY_READ, SOURCE_MANAGE, SUPPORT_MANAGE,
    permissions_for_role, user_has_permission,
)
from app.domains.notifications_workflow.models import Notification, NotificationCursor, UserSettings

SYNC_INTERVAL = 30           # seconds between ledger sweeps per tenant
FIRST_SYNC_LOOKBACK = timedelta(days=7)
SWEEP_BATCH = 500
OVERLAP = timedelta(seconds=5)  # re-read a little; the unique key drops repeats

Recipients = Callable[[AsyncSession, AuditEvent], Awaitable[list[str]]]


@dataclass(frozen=True)
class Rule:
    event_name: str
    kind: str
    label: str                       # shown in Settings → Notifications
    recipients: Recipients
    render: Callable[[AuditEvent], tuple[str, str, str, str]]  # title, body, link, severity
    when: Callable[[AuditEvent], bool] = field(default=lambda event: True)


# ─── Recipient helpers ──────────────────────────────────────────────────────

def _roles_with(permission: str) -> list[str]:
    from app.domains.identity.permissions import ROLE_PERMISSIONS

    return [role for role in ROLE_PERMISSIONS if permission in permissions_for_role(role)]


def users_with_permission(permission: str) -> Recipients:
    async def resolve(db: AsyncSession, event: AuditEvent) -> list[str]:
        rows = await db.execute(select(User.id).where(
            User.tenant_id == event.tenant_id, User.is_active.is_(True), User.role.in_(_roles_with(permission)),
        ))
        return list(rows.scalars())
    return resolve


def users_in_roles(*roles: str) -> Recipients:
    async def resolve(db: AsyncSession, event: AuditEvent) -> list[str]:
        rows = await db.execute(select(User.id).where(
            User.tenant_id == event.tenant_id, User.is_active.is_(True), User.role.in_(roles),
        ))
        return list(rows.scalars())
    return resolve


def payload_user(key: str) -> Recipients:
    async def resolve(db: AsyncSession, event: AuditEvent) -> list[str]:
        value = (event.payload or {}).get(key)
        return [value] if isinstance(value, str) and value else []
    return resolve


async def query_asker(db: AsyncSession, event: AuditEvent) -> list[str]:
    """Whoever asked the question this event is about."""
    actor = await db.scalar(select(AuditEvent.actor_id).where(
        AuditEvent.tenant_id == event.tenant_id,
        AuditEvent.subject_id == event.subject_id,
        AuditEvent.event_name == "query_received",
    ).limit(1))
    return [actor] if actor else []


def _short(text: str | None, limit: int = 80) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ─── Rules ──────────────────────────────────────────────────────────────────

RULES: tuple[Rule, ...] = (
    Rule("human_review_created", "review_assigned", "A question is sent for human review",
         users_with_permission(REVIEW_RESOLVE),
         lambda e: ("A question needs your review", "Kriton sent an answer to human review.", "/review-tasks", "warn")),
    Rule("answer_feedback_received", "answer_flagged", "Someone flags an answer as wrong",
         users_with_permission(REVIEW_RESOLVE),
         lambda e: ("An answer was flagged", "A user marked an Ask Kriton answer as wrong.", "/review-tasks", "warn"),
         when=lambda e: (e.payload or {}).get("rating") == "down"),
    Rule("human_review_resolved", "question_reviewed", "Your question has been reviewed",
         query_asker,
         lambda e: ("Your question was reviewed",
                    f"A reviewer marked it {str((e.payload or {}).get('decision') or 'reviewed').lower()}.",
                    "/ask-kriton", "info")),
    Rule("source_ingestion_event", "source_submitted", "A source is waiting for approval",
         users_with_permission(SOURCE_MANAGE),
         lambda e: ("Source waiting for approval", _short((e.payload or {}).get("title")),
                    "/source-library?tab=licensing", "info"),
         when=lambda e: (e.payload or {}).get("status") in ("PROPOSED", "UNDER_REVIEW")),
    Rule("source_version_approved", "source_approved", "Your source is approved",
         payload_user("submitted_by"),
         lambda e: ("Your source was approved", "It can now be used by Ask Kriton.", "/source-library", "info")),
    Rule("prompt_template_approved", "prompt_approved", "Your prompt is approved",
         payload_user("submitted_by"),
         lambda e: ("Your prompt was approved",
                    _short(f"{(e.payload or {}).get('prompt_name', '')} {(e.payload or {}).get('version', '')}"),
                    "/model-prompt-registry?tab=prompts", "info")),
    Rule("security_incident_recorded", "incident_opened", "A security incident is opened",
         users_with_permission(SUPPORT_MANAGE),
         lambda e: ("Security incident opened", "Kriton blocked a control-bypass or privacy attempt.",
                    "/incident-response", "bad")),
    Rule("break_glass_access_requested", "break_glass_requested", "Someone requests emergency access",
         users_in_roles("Admin"),
         lambda e: ("Emergency access requested", "A user asked for temporary elevated access.", "/break-glass", "warn")),
    Rule("break_glass_access_granted", "break_glass_decided", "Your emergency access request is decided",
         payload_user("user_id"),
         lambda e: ("Your emergency access was approved", "It ends automatically when the time runs out.",
                    "/break-glass", "info")),
    Rule("break_glass_access_rejected", "break_glass_decided", "Your emergency access request is decided",
         payload_user("user_id"),
         lambda e: ("Your emergency access was declined", "", "/break-glass", "warn")),
)

RULES_BY_EVENT: dict[str, list[Rule]] = {}
for _rule in RULES:
    RULES_BY_EVENT.setdefault(_rule.event_name, []).append(_rule)

# kind → label, for the Settings page (one entry per kind).
NOTIFICATION_KINDS: dict[str, str] = {}
for _rule in RULES:
    NOTIFICATION_KINDS.setdefault(_rule.kind, _rule.label)


# ─── Ledger sweep ───────────────────────────────────────────────────────────

_last_sync: dict[str, float] = {}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _muted_kinds(db: AsyncSession, user_ids: set[str]) -> dict[str, set[str]]:
    if not user_ids:
        return {}
    rows = await db.execute(select(UserSettings.user_id, UserSettings.preferences).where(UserSettings.user_id.in_(user_ids)))
    return {user_id: set((prefs or {}).get("muted_notifications", [])) for user_id, prefs in rows.all()}


async def sync_tenant(db: AsyncSession, tenant_id: str, *, force: bool = False, now: datetime | None = None) -> int:
    """Turn new audit events for one tenant into notifications. Returns how
    many notifications were created. `db` must be able to read every user in
    the tenant (the system session), since recipients are found by role."""
    clock = time.monotonic()
    if not force and clock - _last_sync.get(tenant_id, -SYNC_INTERVAL) < SYNC_INTERVAL:
        return 0
    _last_sync[tenant_id] = clock

    now = now or datetime.now(timezone.utc)
    cursor = await db.get(NotificationCursor, tenant_id)
    since = _aware(cursor.last_ingested_at) - OVERLAP if cursor else now - FIRST_SYNC_LOOKBACK
    events = list((await db.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id, AuditEvent.ingested_at > since,
               AuditEvent.event_name.in_(tuple(RULES_BY_EVENT)))
        .order_by(AuditEvent.ingested_at)
        .limit(SWEEP_BATCH)
    )).scalars())

    planned: list[tuple[Rule, AuditEvent, list[str]]] = []
    for event in events:
        for rule in RULES_BY_EVENT[event.event_name]:
            if not rule.when(event):
                continue
            # Never notify people about their own action.
            recipients = [uid for uid in dict.fromkeys(await rule.recipients(db, event)) if uid != event.actor_id]
            if recipients:
                planned.append((rule, event, recipients))

    existing = set()
    if planned:
        rows = await db.execute(select(Notification.user_id, Notification.source_event_id, Notification.kind).where(
            Notification.source_event_id.in_({event.id for _, event, _ in planned})))
        existing = set(rows.all())
    muted = await _muted_kinds(db, {uid for _, _, recipients in planned for uid in recipients})

    created = 0
    for rule, event, recipients in planned:
        title, body, link, severity = rule.render(event)
        for user_id in recipients:
            if (user_id, event.id, rule.kind) in existing or rule.kind in muted.get(user_id, ()):
                continue
            existing.add((user_id, event.id, rule.kind))
            db.add(Notification(
                tenant_id=tenant_id, user_id=user_id, kind=rule.kind, severity=severity,
                title=title, body=body, link=link, source_event_id=event.id,
                created_at=_aware(event.event_time or event.ingested_at),
            ))
            created += 1

    newest = _aware(events[-1].ingested_at) if events else None
    if cursor is None:
        db.add(NotificationCursor(tenant_id=tenant_id, last_ingested_at=newest or now))
    elif newest and newest > _aware(cursor.last_ingested_at):
        cursor.last_ingested_at = newest
    await db.commit()
    return created


async def sync_tenant_safely(tenant_id: str) -> None:
    """Run the sweep on the system session; a failure here must never break
    the bell, it only delays new notifications to the next check."""
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as system_db:
            await sync_tenant(system_db, tenant_id)
    except Exception as exc:  # noqa: BLE001
        _last_sync.pop(tenant_id, None)
        print(f"WARNING: notification sync skipped for tenant {tenant_id} ({type(exc).__name__}: {exc})")


# ─── Reading ────────────────────────────────────────────────────────────────

def _public(n: Notification) -> dict:
    created = _aware(n.created_at) if n.created_at else None
    return {
        "id": n.id, "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body,
        "link": n.link, "created_at": created.isoformat() if created else None, "read": n.read_at is not None,
    }


async def unread_count(db: AsyncSession, user: User) -> int:
    return await db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None))) or 0


async def list_notifications(db: AsyncSession, user: User, *, unread_only: bool = False,
                             kind: str | None = None, limit: int = 30, before: datetime | None = None) -> list[dict]:
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if kind:
        query = query.where(Notification.kind == kind)
    if before:
        query = query.where(Notification.created_at < before)
    rows = await db.execute(query.order_by(Notification.created_at.desc()).limit(limit))
    return [_public(n) for n in rows.scalars()]


async def mark_read(db: AsyncSession, user: User, notification_id: str | None = None) -> int:
    query = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if notification_id:
        query = query.where(Notification.id == notification_id)
    result = await db.execute(query.values(read_at=datetime.now(timezone.utc)))
    await db.commit()
    return result.rowcount or 0


# ─── Needs your action (live, not stored) ───────────────────────────────────

_ACTION_CACHE_SECONDS = 30
_action_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}


async def action_items(db: AsyncSession, user: User) -> list[dict]:
    """Open work waiting on this person's role right now. All counts run as
    one statement (one round trip, ~0.3s instead of ~3s for six) and the
    result is reused for 30s per person, since the bell asks every minute."""
    key = (user.id, user.role)
    hit = _action_cache.get(key)
    if hit and time.monotonic() - hit[0] < _ACTION_CACHE_SECONDS:
        return hit[1]

    counts: list[tuple[str, str, str, str, str, object]] = []  # key, singular, plural, link, severity, count expr

    if user_has_permission(user, REVIEW_RESOLVE):
        from app.orchestration.models import ReviewCase
        counts.append(("reviews", "1 question waiting for review", "{n} questions waiting for review", "/review-tasks", "warn",
                       select(func.count()).select_from(ReviewCase).where(
                           ReviewCase.tenant_id == user.tenant_id,
                           ReviewCase.status.in_(("open", "triaged", "needs_evidence"))).scalar_subquery()))

    if user_has_permission(user, SAFETY_READ):
        from app.domains.risk_safety.models import EscalationCase, EscalationStatus
        naive_now = datetime.now(timezone.utc).replace(tzinfo=None)
        counts.append(("escalations_overdue", "1 escalation past its SLA", "{n} escalations past their SLA", "/escalation-queue", "bad",
                       select(func.count()).select_from(EscalationCase).where(
                           EscalationCase.tenant_id == user.tenant_id, EscalationCase.sla_deadline < naive_now,
                           EscalationCase.status.notin_((EscalationStatus.RESOLVED, EscalationStatus.REFUSED))).scalar_subquery()))

    if user_has_permission(user, SOURCE_MANAGE):
        from app.domains.source_library.models import Source, SourceVersion
        counts.append(("sources", "1 source waiting for approval", "{n} sources waiting for approval", "/source-library?tab=licensing", "info",
                       select(func.count()).select_from(SourceVersion).join(Source, Source.id == SourceVersion.source_id).where(
                           or_(Source.is_tenant_private.is_(False), Source.tenant_id == user.tenant_id),
                           SourceVersion.status.in_(("PROPOSED", "UNDER_REVIEW")),
                           SourceVersion.submitted_by != user.id).scalar_subquery()))

    if user_has_permission(user, MODEL_MANAGE):
        from app.domains.model_gateway.models import PromptTemplate
        counts.append(("prompts", "1 prompt waiting for approval", "{n} prompts waiting for approval", "/model-prompt-registry?tab=prompts", "info",
                       select(func.count()).select_from(PromptTemplate).where(
                           PromptTemplate.status == "PendingReview", PromptTemplate.submitted_by != user.id).scalar_subquery()))

    if user_has_permission(user, SUPPORT_MANAGE):
        from app.domains.support_incident.models import SecurityIncident
        counts.append(("incidents", "1 open security incident", "{n} open security incidents", "/incident-response", "bad",
                       select(func.count()).select_from(SecurityIncident).where(
                           SecurityIncident.tenant_id == user.tenant_id,
                           SecurityIncident.containment_status == "OPEN").scalar_subquery()))

    if user.role == "Admin":
        from app.domains.identity.models import BreakGlassGrant
        counts.append(("break_glass", "1 emergency access request", "{n} emergency access requests", "/break-glass", "warn",
                       select(func.count()).select_from(BreakGlassGrant).where(
                           BreakGlassGrant.tenant_id == user.tenant_id, BreakGlassGrant.status == "requested",
                           BreakGlassGrant.user_id != user.id).scalar_subquery()))

    items: list[dict] = []
    if counts:
        row = (await db.execute(select(*(expr for *_, expr in counts)))).one()
        for (item_key, singular, plural, link, severity, _), count in zip(counts, row):
            if count:
                items.append({"key": item_key, "count": count, "label": singular if count == 1 else plural.format(n=count),
                              "link": link, "severity": severity})
    _action_cache[key] = (time.monotonic(), items)
    return items
