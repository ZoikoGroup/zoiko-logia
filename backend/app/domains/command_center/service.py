"""Live view models for the Overview pages: Command Center, Governance
Dashboard and My Workspace.

Every number here is counted from the tenant's own records at request time.
Nothing is a sample value: a panel with no records says so instead of
inventing a healthy figure. Each panel is gated on the permission that the
underlying page (review queue, escalations, incidents, sources) already
requires, so the overview never shows more than those pages would.

Some older tables store naive UTC timestamps (escalation_cases,
safety_events, evaluation_runs); those are compared against a naive "now".
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, literal, or_, select, text, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import get_settings
from app.core.database import RequestSessionLocal, request_engine

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.audit_ledger.models import AuditEvent
from app.domains.evaluation.models import EvaluationDataset, EvaluationRun, ThresholdSet
from app.domains.identity.models import Engagement, Tenant, User
from app.domains.identity.permissions import (
    EVALUATION_READ,
    REVIEW_READ,
    REVIEW_RESOLVE,
    SAFETY_MANAGE,
    SAFETY_READ,
    SOURCE_MANAGE,
    SOURCE_READ,
    SUPPORT_READ,
    user_has_permission,
)
from app.domains.kriton_workspace.models import Document, Draft, GeneratedArtifact, SavedAnswer
from app.domains.risk_safety.models import EscalationCase, EscalationStatus, RiskLevel, RiskPolicy, SafetyEvent
from app.domains.source_library.models import Source, SourceRight, SourceVersion
from app.domains.support_incident.models import SecurityIncident
from app.orchestration.models import ReviewCase

settings = get_settings()
logger = logging.getLogger(__name__)

OPEN_ESCALATION = (EscalationStatus.PENDING, EscalationStatus.UNDER_REVIEW, EscalationStatus.ESCALATED)
CLOSED_INCIDENT = ("RESOLVED", "CLOSED")
HIGH_REVIEW_RISKS = ("HIGH", "REPORTED", "RESTRICTED")
# Metrics where a smaller value is better; every other metric must reach its threshold.
LOWER_IS_BETTER = {"latency_p95", "over_refusal_rate", "pii_leak", "secrets_leak", "cross_tenant_leak"}
# An open review case older than this is reported as overdue.
REVIEW_OVERDUE_DAYS = 7
DEADLINE_HORIZON_DAYS = 14
LICENCE_HORIZON_DAYS = 30


# ── small helpers ─────────────────────────────────────────────────────────────

def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    dt = _utc(dt)
    return dt.isoformat() if dt else None


def ago(dt: datetime | None, now: datetime) -> str:
    """Plain-language age: "just now", "5 min ago", "3 hr ago", "12 days ago"."""
    dt = _utc(dt)
    if dt is None:
        return "never"
    seconds = (now - dt).total_seconds()
    if seconds < 0:
        return until(dt, now)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hr ago"
    days = int(seconds // 86400)
    return "1 day ago" if days == 1 else f"{days} days ago"


def until(dt: datetime, now: datetime) -> str:
    seconds = (_utc(dt) - now).total_seconds()
    if seconds < 3600:
        return "within the hour"
    if seconds < 86400:
        return f"in {int(seconds // 3600)} hr"
    days = int(seconds // 86400)
    return "tomorrow" if days == 1 else f"in {days} days"


def _short(text: str | None, limit: int = 96) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def display_name(user: User) -> str:
    for candidate in (user.first_name, (user.full_name or "").split(" ")[0]):
        if candidate and candidate.strip():
            return candidate.strip()
    return (user.email or "there").split("@")[0]


def permissions(user: User) -> dict[str, bool]:
    return {
        "review": user_has_permission(user, REVIEW_READ),
        "reviewResolve": user_has_permission(user, REVIEW_RESOLVE),
        "safety": user_has_permission(user, SAFETY_READ),
        "safetyManage": user_has_permission(user, SAFETY_MANAGE),
        "support": user_has_permission(user, SUPPORT_READ),
        "source": user_has_permission(user, SOURCE_READ),
        "sourceManage": user_has_permission(user, SOURCE_MANAGE),
        "evaluation": user_has_permission(user, EVALUATION_READ),
    }


def _count(*conditions):
    """count(*) FILTER (WHERE …): many counts over one table in one query."""
    return func.count().filter(and_(*conditions))


def _visible_sources(tenant_id: str):
    # Same boundary as source_library.service.list_sources: shared sources are
    # visible to everyone, private ones only to their owning tenant.
    return or_(Source.is_tenant_private.is_(False), Source.tenant_id == tenant_id)


@asynccontextmanager
async def scoped_session(user: User) -> AsyncIterator[AsyncSession]:
    """A session on its own connection carrying the caller's identity for
    Postgres RLS, exactly as core.database.get_db sets it for a request. Lets
    the independent parts of a dashboard run at the same time: the database
    is a ~200 ms round trip away, so running ~40 queries one after another
    is what made these pages take 10–25 seconds."""
    connection = await request_engine.connect()
    try:
        async with RequestSessionLocal(bind=connection) as session:
            if not settings.is_sqlite:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, false), set_config('app.user_id', :user_id, false)"),
                    {"tenant_id": user.tenant_id, "user_id": user.id},
                )
                # Not committed: these sessions only read, and the rollback
                # when the connection goes back to the pool clears the
                # identity again, so it can never leak into another request.
            yield session
    finally:
        await connection.close()


# The hosted database's session pooler allows 15 clients in total, shared by
# every engine in every backend process. Five parallel connections per
# Overview page, with the other two pages prefetched at the same time, hit
# "EMAXCONNSESSION max clients reached" and the page failed. At most this many
# extra connections are open for the Overview at once in this process; further
# groups wait for a free one.
OVERVIEW_DB_CONNECTIONS = 2
_overview_slots: asyncio.Semaphore | None = None


def _slots() -> asyncio.Semaphore:
    global _overview_slots
    if _overview_slots is None:
        _overview_slots = asyncio.Semaphore(OVERVIEW_DB_CONNECTIONS)
    return _overview_slots


async def run_parallel(user: User, *groups: Callable[[AsyncSession], Awaitable]) -> list:
    """Run each group on its own identity-scoped connection, at most
    OVERVIEW_DB_CONNECTIONS at a time."""
    async def run(group):
        async with _slots():
            async with scoped_session(user) as session:
                return await group(session)
    return list(await asyncio.gather(*(run(group) for group in groups)))


async def workspace_meta(db: AsyncSession, tenant_id: str) -> dict:
    """Tenant name, current risk-policy version and the latest audit event in
    one round trip. The audit lookup walks the ingested_at index backwards;
    max(event_time) had no index to use and took ~3 s."""
    row = (await db.execute(select(
        select(Tenant.name).where(Tenant.id == tenant_id).scalar_subquery(),
        select(RiskPolicy.version).order_by(RiskPolicy.created_at.desc()).limit(1).scalar_subquery(),
        select(AuditEvent.ingested_at).where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.ingested_at.desc()).limit(1).scalar_subquery(),
    ))).one()
    return {"tenantName": row[0] or "Current workspace", "policyVersion": row[1] or "not-assessed", "lastAuditAt": row[2]}


# Overview results are kept briefly per user and options, so moving between
# the three Overview pages (or coming back to one) is instant. The Refresh
# button asks for fresh=1, which skips the cache.
CACHE_SECONDS = 30
_CACHE_LIMIT = 512
_cache: dict[tuple, tuple[float, dict]] = {}


async def cached(key: tuple, build: Callable[[], Awaitable[dict]], *, fresh: bool = False) -> dict:
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and not fresh and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = await build()
    if len(_cache) >= _CACHE_LIMIT:
        for stale_key, (stamp, _) in list(_cache.items()):
            if now - stamp >= CACHE_SECONDS:
                del _cache[stale_key]
        if len(_cache) >= _CACHE_LIMIT:
            _cache.clear()
    _cache[key] = (now, value)
    return value


async def record_opened(user: User, **event) -> None:
    """Write the "page opened" audit event after the response has been sent:
    the ledger write (chain-hash lookup, insert, commit) is several round
    trips the user should not wait for. Failures are logged, never raised."""
    try:
        async with scoped_session(user) as session:
            await record_event_async(session, tenant_id=user.tenant_id, actor_id=user.id,
                                     subject_id=user.tenant_id, **event)
    except Exception:  # noqa: BLE001 — a background audit write must not crash the worker
        logger.exception("Could not record %s for %s", event.get("event_name"), user.id)


# ── shared building blocks ────────────────────────────────────────────────────

async def review_snapshot(db: AsyncSession, tenant_id: str, now: datetime, limit: int = 3) -> dict:
    is_open = ReviewCase.status.in_(("open", "triaged", "needs_evidence"))
    counts = (await db.execute(select(
        _count(is_open),
        _count(is_open, ReviewCase.risk_level.in_(HIGH_REVIEW_RISKS)),
        _count(is_open, ReviewCase.risk_level == "REPORTED"),
        _count(is_open, ReviewCase.created_at < now - timedelta(days=REVIEW_OVERDUE_DAYS)),
        _count(ReviewCase.resolved_at.is_not(None)),
        func.count(),
        func.min(ReviewCase.created_at).filter(is_open),
        func.max(ReviewCase.created_at),
    ).where(ReviewCase.tenant_id == tenant_id))).one()
    rank = case({risk: index for index, risk in enumerate(("REPORTED", "RESTRICTED", "HIGH", "MEDIUM", "LOW", "ZERO"))}, value=ReviewCase.risk_level, else_=99)
    rows = (await db.execute(
        select(ReviewCase.id, ReviewCase.query_text, ReviewCase.risk_level, ReviewCase.reason, ReviewCase.created_at)
        .where(ReviewCase.tenant_id == tenant_id, is_open)
        .order_by(rank, ReviewCase.created_at.desc()).limit(limit)
    )).all()
    items = [{
        "id": case.id,
        "title": _short(case.query_text) or "Untitled question",
        "risk": case.risk_level,
        "reason": _short(case.reason, 120),
        "createdAt": _iso(case.created_at),
        "age": ago(case.created_at, now),
        "href": "/review-tasks",
    } for case in rows]
    return {
        "open": counts[0], "highOpen": counts[1], "reported": counts[2], "overdue": counts[3],
        "resolved": counts[4], "total": counts[5], "oldestOpenAt": _iso(counts[6]), "latestAt": _iso(counts[7]),
        "items": items,
    }


async def escalation_snapshot(db: AsyncSession, tenant_id: str, now: datetime) -> dict:
    naive_now = now.replace(tzinfo=None)
    is_open = EscalationCase.status.in_(OPEN_ESCALATION)
    is_overdue = and_(is_open, EscalationCase.sla_deadline.is_not(None), EscalationCase.sla_deadline < naive_now)
    counts = (await db.execute(select(
        func.count(),
        _count(is_open),
        _count(is_overdue),
        _count(EscalationCase.status.in_((EscalationStatus.RESOLVED, EscalationStatus.REFUSED))),
        _count(or_(EscalationCase.risk_level == RiskLevel.RESTRICTED, EscalationCase.restricted_sub_class.is_not(None))),
        _count(EscalationCase.status == EscalationStatus.REFUSED),
        func.max(EscalationCase.created_at),
        _count(is_open, EscalationCase.sla_deadline >= naive_now,
               EscalationCase.sla_deadline <= naive_now + timedelta(days=DEADLINE_HORIZON_DAYS)),
    ).where(EscalationCase.tenant_id == tenant_id))).one()
    # Overdue (oldest first) and upcoming (soonest first) in one round trip.
    overdue_q = (select(EscalationCase).where(EscalationCase.tenant_id == tenant_id, is_overdue)
                 .order_by(EscalationCase.sla_deadline).limit(3))
    upcoming_q = (select(EscalationCase).where(
        EscalationCase.tenant_id == tenant_id, is_open, EscalationCase.sla_deadline >= naive_now,
        EscalationCase.sla_deadline <= naive_now + timedelta(days=DEADLINE_HORIZON_DAYS),
    ).order_by(EscalationCase.sla_deadline).limit(5))
    both = union_all(select(overdue_q.subquery()), select(upcoming_q.subquery())).subquery()
    rows = (await db.execute(select(aliased(EscalationCase, both)))).scalars().all()
    overdue_rows = [r for r in rows if r.sla_deadline is not None and r.sla_deadline < naive_now]
    upcoming_rows = [r for r in rows if r.sla_deadline is not None and r.sla_deadline >= naive_now]
    overdue_rows.sort(key=lambda r: r.sla_deadline)
    upcoming_rows.sort(key=lambda r: r.sla_deadline)
    return {
        "total": counts[0], "open": counts[1], "overdue": counts[2], "closed": counts[3], "upcoming": counts[7],
        "restricted": counts[4], "refused": counts[5],
        "oldestOverdueAt": _iso(overdue_rows[0].sla_deadline) if overdue_rows else None,
        "latestAt": _iso(counts[6]),
        "overdueItems": overdue_rows,
        "upcomingItems": upcoming_rows,
    }


async def incident_snapshot(db: AsyncSession, tenant_id: str) -> dict:
    is_open = SecurityIncident.containment_status.not_in(CLOSED_INCIDENT)
    severity = func.lower(SecurityIncident.severity)
    grouped = (await db.execute(
        select(severity, _count(is_open), func.count(), func.min(SecurityIncident.opened_at).filter(is_open))
        .where(SecurityIncident.tenant_id == tenant_id).group_by(severity)
    )).all()
    by_severity = {sev: open_n for sev, open_n, _, _ in grouped}
    oldest = min((o for *_, o in grouped if o is not None), default=None)
    latest = (await db.execute(
        select(SecurityIncident).where(SecurityIncident.tenant_id == tenant_id, is_open)
        .order_by(SecurityIncident.opened_at.desc()).limit(3)
    )).scalars().all()
    return {
        "total": sum(total for _, _, total, _ in grouped),
        "open": sum(by_severity.values()),
        "openBySeverity": {s: int(by_severity.get(s, 0)) for s in ("critical", "high", "medium", "low")},
        "oldestOpenAt": _iso(oldest),
        "latest": latest,
    }


async def source_snapshot(db: AsyncSession, tenant_id: str, now: datetime) -> dict:
    visible = _visible_sources(tenant_id)
    in_use = SourceVersion.status.not_in(("WITHDRAWN", "REVOKED"))
    counts = (await db.execute(
        select(
            func.count(),
            _count(SourceVersion.status == "PROPOSED"),
            _count(SourceVersion.status.in_(("WITHDRAWN", "REVOKED"))),
            _count(in_use, SourceVersion.quality_state == "REVIEWED"),
            _count(in_use, SourceVersion.quality_state != "REVIEWED"),
            func.max(SourceVersion.created_at),
            select(func.count()).select_from(Source).where(visible, Source.licence_state != "permitted").scalar_subquery(),
        ).select_from(SourceVersion).join(Source, Source.id == SourceVersion.source_id).where(visible)
    )).one()
    expiring_rights = (await db.execute(
        select(SourceRight, Source.title).join(SourceVersion, SourceVersion.id == SourceRight.source_version_id)
        .join(Source, Source.id == SourceVersion.source_id)
        .where(visible, SourceRight.tenant_id.in_((tenant_id, "GLOBAL_CONTROL")), SourceRight.decision == "allow", SourceRight.valid_to.is_not(None),
               SourceRight.valid_to <= now + timedelta(days=LICENCE_HORIZON_DAYS))
        .order_by(SourceRight.valid_to)
    )).all()
    expired = [(r, t) for r, t in expiring_rights if _utc(r.valid_to) < now]
    expiring = [(r, t) for r, t in expiring_rights if _utc(r.valid_to) >= now]
    proposed_rows = (await db.execute(
        select(SourceVersion, Source.title).join(Source, Source.id == SourceVersion.source_id)
        .where(visible, SourceVersion.status == "PROPOSED").order_by(SourceVersion.created_at).limit(3)
    )).all()
    jurisdictions = (await db.execute(
        select(Source.jurisdiction_scope).join(SourceVersion, SourceVersion.source_id == Source.id)
        .where(visible, SourceVersion.status.in_(("APPROVED", "ACTIVE"))).distinct()
    )).scalars().all()
    covered: set[str] = set()
    for scope in jurisdictions:
        for part in (scope or "").split(","):
            part = part.strip()
            if part:
                covered.add({"United Kingdom": "UK", "GB": "UK", "India": "IN"}.get(part, part))
    total, proposed, withdrawn, reviewed, unreviewed, latest, restricted = counts
    return {
        "total": total, "proposed": proposed, "withdrawn": withdrawn, "reviewed": reviewed,
        "unreviewed": unreviewed, "inUse": total - withdrawn, "restrictedLicence": restricted,
        "expiringLicences": expiring, "expiredLicences": expired,
        "proposedItems": proposed_rows, "jurisdictions": sorted(covered), "latestAt": _iso(latest),
    }


def gate_results(metrics: dict, limits: dict, zero_tolerance: list | set) -> list[dict]:
    """Compare an evaluation run's metrics with its threshold set. Leak, latency
    and over-refusal metrics must stay at or below the threshold; the rest
    must reach it. Metrics the run did not measure are left out."""
    results = []
    for name, limit in limits.items():
        if name not in metrics:
            continue
        value = metrics[name]
        passed = value <= limit if name in LOWER_IS_BETTER else value >= limit
        results.append({"metric": name, "value": value, "threshold": limit, "passed": passed,
                        "zeroTolerance": name in set(zero_tolerance)})
    return results


async def evaluation_snapshot(db: AsyncSession, tenant_id: str) -> dict | None:
    row = (await db.execute(
        select(EvaluationRun, ThresholdSet)
        .join(EvaluationDataset, EvaluationDataset.id == EvaluationRun.dataset_id)
        .outerjoin(ThresholdSet, ThresholdSet.id == EvaluationRun.threshold_set_id)
        .where(or_(EvaluationDataset.tenant_id == tenant_id, EvaluationDataset.tenant_id.is_(None)))
        .order_by(EvaluationRun.created_at.desc()).limit(1)
    )).first()
    if row is None:
        return None
    run, thresholds = row
    results = gate_results(
        run.metrics_summary or {},
        (thresholds.metrics if thresholds else {}) or {},
        (thresholds.zero_tolerance_metrics if thresholds else None) or [],
    )
    return {
        "runId": run.id, "status": run.status, "createdAt": _iso(run.created_at),
        "results": results, "failing": [r for r in results if not r["passed"]],
    }


_WORK_KINDS = {
    "saved_answer": ("Saved", "/saved-answers"),
    "draft": ("Edited", "/drafts-reports"),
    "document": ("Uploaded", "/ask-kriton"),
    "artifact": ("Generated", "/ask-kriton"),
}


async def recent_work(db: AsyncSession, user: User, now: datetime, limit: int = 10) -> list[dict]:
    """The user's saved answers, drafts, uploads and generated files, newest
    first, in one UNION query."""
    tid, uid = user.tenant_id, user.id

    def part(kind, model, title, extra, at):
        return select((select(literal(kind).label("kind"), model.id.label("id"), title.label("title"),
                       extra.label("extra"), at.label("at"))
                .where(model.tenant_id == tid, model.user_id == uid).order_by(at.desc()).limit(limit).subquery()))

    query = union_all(
        part("saved_answer", SavedAnswer, SavedAnswer.query_text, SavedAnswer.risk_level, SavedAnswer.created_at),
        part("draft", Draft, Draft.title, Draft.status, Draft.updated_at),
        part("document", Document, Document.filename, literal(""), Document.created_at),
        part("artifact", GeneratedArtifact, GeneratedArtifact.filename, literal(""), GeneratedArtifact.created_at),
    ).subquery()
    rows = (await db.execute(select(query).order_by(query.c.at.desc()).limit(limit))).all()
    items = []
    for row in rows:
        verb, href = _WORK_KINDS[row.kind]
        context = {
            "saved_answer": f"Saved Kriton answer · {(row.extra or '').title()} risk",
            "draft": f"Draft report · {row.extra}",
            "document": "Uploaded document",
            "artifact": "File generated by Kriton",
        }[row.kind]
        items.append({"id": row.id, "kind": row.kind, "title": _short(row.title, 70), "context": context,
                      "verb": verb, "href": href, "at": _iso(row.at), "age": ago(row.at, now)})
    return items


# ── Command Center ────────────────────────────────────────────────────────────

async def active_matters(db: AsyncSession, tenant_id: str, limit: int = 6) -> tuple[list, int]:
    rows = (await db.execute(
        select(Engagement, func.count().over()).where(Engagement.tenant_id == tenant_id, Engagement.status == "active")
        .order_by(Engagement.created_at.desc()).limit(limit)
    )).all()
    return [m for m, _ in rows], (rows[0][1] if rows else 0)


async def build_command_center(user: User, now: datetime) -> dict:
    perms = permissions(user)
    tid = user.tenant_id
    attention: list[dict] = []
    deadlines: list[dict] = []

    async def reviews(db):
        return await review_snapshot(db, tid, now) if perms["review"] else None

    async def safety(db):
        return (await escalation_snapshot(db, tid, now) if perms["safety"] else None,
                await incident_snapshot(db, tid) if perms["support"] else None)

    async def mine(db):
        return await recent_work(db, user, now, limit=5), await workspace_meta(db, tid)

    async def matters_group(db):
        return await active_matters(db, tid)

    async def evidence(db):
        return await source_snapshot(db, tid, now) if perms["source"] else None

    review, (escalations, incidents), (recent, meta), (matters, matters_total), sources = await run_parallel(
        user, reviews, safety, mine, matters_group, evidence)

    if incidents and incidents["open"]:
        latest = incidents["latest"][0]
        attention.append({
            "id": "incidents-open", "level": "high",
            "title": f"{_plural(incidents['open'], 'security incident')} {'is' if incidents['open'] == 1 else 'are'} open",
            "context": f"Latest: {_short(latest.title, 80)}",
            "due": f"Oldest opened {ago(_utc(datetime.fromisoformat(incidents['oldestOpenAt'])), now)}",
            "action": "Open incidents", "href": "/incident-response",
        })
    if escalations and escalations["overdue"]:
        attention.append({
            "id": "escalations-overdue", "level": "high",
            "title": f"{_plural(escalations['overdue'], 'escalation')} past {'its' if escalations['overdue'] == 1 else 'their'} SLA",
            "context": f"Oldest: {_short(escalations['overdueItems'][0].topic or escalations['overdueItems'][0].query_text, 80)}",
            "due": f"Oldest due {ago(_utc(datetime.fromisoformat(escalations['oldestOverdueAt'])), now)}",
            "action": "Open escalations", "href": "/escalation-queue",
        })
    if review and review["highOpen"]:
        attention.append({
            "id": "reviews-high", "level": "high" if review["reported"] else "attention",
            "title": f"{_plural(review['highOpen'], 'high-risk answer')} awaiting human review",
            "context": (f"{_plural(review['reported'], 'answer')} reported by users" if review["reported"]
                        else f"{review['open']} answers in the review queue"),
            "due": f"Oldest waiting {ago(_utc(datetime.fromisoformat(review['oldestOpenAt'])), now)}" if review["oldestOpenAt"] else "",
            "action": "Open review", "href": "/review-tasks",
        })
    if sources and sources["proposed"]:
        attention.append({
            "id": "sources-proposed", "level": "attention",
            "title": f"{_plural(sources['proposed'], 'source version')} awaiting approval",
            "context": f"Next: {_short(sources['proposedItems'][0][1], 80)}" if sources["proposedItems"] else "Source library",
            "due": f"Submitted {ago(sources['proposedItems'][0][0].created_at, now)}" if sources["proposedItems"] else "",
            "action": "Review sources", "href": "/source-library",
        })
    if sources and (sources["expiredLicences"] or sources["expiringLicences"]):
        n = len(sources["expiredLicences"]) + len(sources["expiringLicences"])
        attention.append({
            "id": "licences", "level": "high" if sources["expiredLicences"] else "attention",
            "title": f"{_plural(n, 'source licence')} expired or expiring within {LICENCE_HORIZON_DAYS} days",
            "context": "Source licensing", "due": "", "action": "Review licences", "href": "/source-licensing",
        })

    if escalations:
        if escalations["overdue"]:
            deadlines.append({"id": "esc-overdue", "title": f"{_plural(escalations['overdue'], 'escalation')} overdue",
                              "context": "Escalation SLA", "date": "Overdue", "state": "critical", "href": "/escalation-queue"})
        for case in escalations["upcomingItems"]:
            due = _utc(case.sla_deadline)
            deadlines.append({"id": case.id, "title": _short(case.topic or case.query_text, 60),
                              "context": f"Escalation SLA · {case.risk_level.value.title()} risk",
                              "date": due.strftime("%d %b"), "dueAt": _iso(due),
                              "state": "critical" if due - now < timedelta(days=1) else "approaching" if due - now < timedelta(days=3) else "scheduled",
                              "href": "/escalation-queue"})
    if sources:
        for right, title in sources["expiredLicences"] + sources["expiringLicences"]:
            due = _utc(right.valid_to)
            if due > now + timedelta(days=DEADLINE_HORIZON_DAYS):
                continue
            deadlines.append({"id": right.id, "title": f"Licence {'expired' if due < now else 'expires'}: {_short(title, 50)}",
                              "context": f"Source rights · {right.operation}", "date": "Expired" if due < now else due.strftime("%d %b"),
                              "dueAt": _iso(due), "state": "critical" if due < now + timedelta(days=7) else "approaching",
                              "href": "/source-licensing"})

    upcoming = (escalations["upcoming"] if escalations else 0) + (
        sum(1 for right, _ in sources["expiringLicences"] if _utc(right.valid_to) <= now + timedelta(days=DEADLINE_HORIZON_DAYS))
        if sources else 0
    )
    overdue = (escalations["overdue"] if escalations else 0) + (len(sources["expiredLicences"]) if sources else 0)

    last_audit = meta["lastAuditAt"]
    controls = {
        "boundary_enforcement": "ok",
        "audit_recording": "ok" if last_audit and now - _utc(last_audit) < timedelta(days=1) else "stale",
    }
    if sources is not None:
        controls["source_licensing"] = "attention" if (sources["expiredLicences"] or sources["restrictedLicence"]) else "ok"
        controls["source_authority"] = "attention" if sources["proposed"] else "ok"
    if review is not None:
        controls["human_review"] = "attention" if review["overdue"] else "ok"
    if escalations is not None:
        controls["escalation_sla"] = "attention" if escalations["overdue"] else "ok"

    return {
        "user": {"displayName": display_name(user), "role": user.role},
        "workspaceName": meta["tenantName"],
        "permissions": perms,
        "summary": {
            "attentionCount": len(attention),
            "reviewCount": review["open"] if review else 0,
            "upcomingDeadlineCount": upcoming,
            "overdueCount": overdue,
            "deadlineHorizonDays": DEADLINE_HORIZON_DAYS,
        },
        "attentionItems": attention,
        "activeMatters": [{"id": m.id, "name": m.name, "status": m.status, "createdAt": _iso(m.created_at),
                           "age": ago(m.created_at, now)} for m in matters],
        "activeMatterCount": matters_total,
        "deadlines": deadlines[:6],
        "reviewQueue": {"open": review["open"], "items": review["items"]} if review else None,
        "evidence": {
            "proposed": sources["proposed"], "unreviewed": sources["unreviewed"],
            "withdrawn": sources["withdrawn"], "restrictedLicence": sources["restrictedLicence"],
            "inUse": sources["inUse"],
        } if sources else None,
        "recentWork": recent,
        "assurance": {
            "overallState": "attention" if any(v != "ok" for v in controls.values()) else "ok",
            "controls": controls,
            "policyVersion": meta["policyVersion"],
            "lastAuditEventAt": _iso(last_audit),
            "lastAuditEventAge": ago(last_audit, now),
        },
        "generatedAt": now.isoformat(),
    }


# ── My Workspace ──────────────────────────────────────────────────────────────

async def build_my_workspace(user: User, now: datetime) -> dict:
    perms = permissions(user)
    tid, uid = user.tenant_id, user.id

    async def mine(db):
        def mine_count(model):
            return (select(func.count()).select_from(model)
                    .where(model.tenant_id == tid, model.user_id == uid).scalar_subquery())
        counts_row = (await db.execute(select(
            mine_count(SavedAnswer), mine_count(Draft), mine_count(Document), mine_count(GeneratedArtifact),
            select(func.count()).select_from(ReviewCase)
            .where(ReviewCase.tenant_id == tid, ReviewCase.reviewer_id == uid, ReviewCase.resolved_at.is_not(None)).scalar_subquery(),
            select(Tenant.name).where(Tenant.id == tid).scalar_subquery(),
        ))).one()
        activity = await recent_work(db, user, now, limit=12)
        resolved = (await db.execute(
            select(ReviewCase.id, ReviewCase.query_text, ReviewCase.reviewer_decision, ReviewCase.resolved_at)
            .where(ReviewCase.tenant_id == tid, ReviewCase.reviewer_id == uid, ReviewCase.resolved_at.is_not(None))
            .order_by(ReviewCase.resolved_at.desc()).limit(5)
        )).all()
        drafts = (await db.execute(
            select(Draft.id, Draft.title, Draft.status, Draft.updated_at)
            .where(Draft.tenant_id == tid, Draft.user_id == uid, Draft.status != "Final")
            .order_by(Draft.updated_at.desc()).limit(5)
        )).all()
        return counts_row, activity, resolved, drafts

    async def reviews(db):
        return await review_snapshot(db, tid, now, limit=4) if perms["review"] and perms["reviewResolve"] else None

    async def approvals(db):
        esc = await escalation_snapshot(db, tid, now) if perms["safety"] and perms["safetyManage"] else None
        proposed = (await db.execute(
            select(SourceVersion.id, SourceVersion.created_at, Source.title).join(Source, Source.id == SourceVersion.source_id)
            .where(_visible_sources(tid), SourceVersion.status == "PROPOSED").order_by(SourceVersion.created_at).limit(3)
        )).all() if perms["sourceManage"] else []
        return esc, proposed

    (counts_row, activity, resolved, drafts), review, (esc, proposed) = await run_parallel(user, mine, reviews, approvals)

    for case in resolved:
        activity.append({"id": case.id, "kind": "review", "title": _short(case.query_text, 70),
                         "context": f"Review decision · {(case.reviewer_decision or 'resolved').replace('_', ' ')}",
                         "verb": "Resolved", "href": "/review-tasks", "at": _iso(case.resolved_at), "age": ago(case.resolved_at, now)})
    activity.sort(key=lambda a: a["at"] or "", reverse=True)

    tasks: list[dict] = []
    for draft in drafts:
        tasks.append({"id": draft.id, "title": f"Finish draft: {_short(draft.title, 70)}", "status": draft.status,
                      "tone": "info", "href": "/drafts-reports", "age": ago(draft.updated_at, now)})
    if review:
        for item in review["items"]:
            tasks.append({"id": item["id"], "title": f"Review answer: {item['title']}",
                          "status": "User reported" if item["risk"] == "REPORTED" else f"{item['risk'].title()} risk",
                          "tone": "bad" if item["risk"] in HIGH_REVIEW_RISKS else "warn", "href": "/review-tasks", "age": item["age"]})
    if esc:
        for case in esc["overdueItems"][:2]:
            tasks.append({"id": case.id, "title": f"Escalation: {_short(case.topic or case.query_text, 70)}",
                          "status": "Overdue", "tone": "bad", "href": "/escalation-queue", "age": ago(case.created_at, now)})
    for version in proposed:
        tasks.append({"id": version.id, "title": f"Approve source: {_short(version.title, 70)}", "status": "Awaiting approval",
                      "tone": "warn", "href": "/source-library", "age": ago(version.created_at, now)})

    saved, drafts_n, documents, generated, reviewed, name = counts_row
    return {
        "user": {"displayName": display_name(user), "fullName": user.full_name, "email": user.email, "role": user.role},
        "workspaceName": name or "Current workspace",
        "counts": {"savedAnswers": saved, "drafts": drafts_n, "documents": documents,
                   "generatedFiles": generated, "reviewsResolved": reviewed},
        "queues": {"reviews": review["open"] if review else 0, "escalations": esc["open"] if esc else 0},
        "recentActivity": activity[:12],
        "pendingTasks": tasks,
        "generatedAt": now.isoformat(),
    }


# ── Governance Dashboard ──────────────────────────────────────────────────────

def _freshness(at_iso: str | None, now: datetime, window_days: int) -> dict:
    if not at_iso:
        return {"state": "unknown", "label": "No evidence yet"}
    at = _utc(datetime.fromisoformat(at_iso))
    state = "current" if now - at <= timedelta(days=window_days) else "stale"
    return {"state": state, "label": f"{'Current' if state == 'current' else 'Stale'} · {ago(at, now)}", "at": at_iso}


def _exceptions_label(critical: int, high: int, other: int = 0) -> str:
    parts = [f"{critical} critical" if critical else "", f"{high} high" if high else "", f"{other} other" if other else ""]
    return " · ".join(p for p in parts if p) or "None"


async def build_governance(user: User, now: datetime, window_days: int, environment: str) -> dict:
    perms = permissions(user)
    tid = user.tenant_id
    window_start = now - timedelta(days=window_days)
    naive_start = window_start.replace(tzinfo=None)

    async def reviews(db):
        return await review_snapshot(db, tid, now, limit=3)

    async def escalations(db):
        return await escalation_snapshot(db, tid, now), await evaluation_snapshot(db, tid) if perms["evaluation"] else None

    async def operations(db):
        in_window = SafetyEvent.timestamp >= naive_start
        safety = (await db.execute(select(
            _count(in_window, SafetyEvent.event_type == "risk_classification_applied"),
            _count(in_window, SafetyEvent.event_type == "risk_classification_uncertain"),
            _count(in_window, SafetyEvent.event_type == "safety_refusal_returned"),
            func.max(SafetyEvent.timestamp),
        ).where(SafetyEvent.tenant_id == tid))).one()
        return await incident_snapshot(db, tid), safety

    async def audit(db):
        audit_in_window = int((await db.execute(select(func.count()).where(
            AuditEvent.tenant_id == tid, AuditEvent.ingested_at >= window_start))).scalar() or 0)
        return audit_in_window, await workspace_meta(db, tid)

    async def knowledge(db):
        return await source_snapshot(db, tid, now)

    review, (esc, ev), (inc, safety), (audit_in_window, meta), src = await run_parallel(
        user, reviews, escalations, operations, audit, knowledge)
    classified, uncertain, refusals, latest_safety = safety
    last_audit = meta["lastAuditAt"]

    exceptions: list[dict] = []
    latest_incident = inc["latest"][0] if inc["latest"] else None
    for severity, count in inc["openBySeverity"].items():
        if not count:
            continue
        exceptions.append({
            "id": f"incidents-{severity}", "severity": severity.title(), "domain": "Audit & Incident Readiness",
            "title": f"{_plural(count, f'{severity}-severity incident')} open",
            "detail": (f"Latest: {_short(latest_incident.title, 70)} · Owner: {latest_incident.assigned_to or 'Unassigned'}"
                       f" · Oldest open {ago(_utc(datetime.fromisoformat(inc['oldestOpenAt'])), now).replace(' ago', '')}") if perms["support"] else "Open incident totals for this workspace; record details require incident access.",
            "href": "/incident-response",
        })
    if esc["overdue"]:
        exceptions.append({
            "id": "esc-overdue", "severity": "High", "domain": "AI Safety & Risk Controls",
            "title": f"{_plural(esc['overdue'], 'escalation')} past SLA",
            "detail": f"Oldest due {ago(_utc(datetime.fromisoformat(esc['oldestOverdueAt'])), now)} · {esc['open']} open in total",
            "href": "/escalation-queue",
        })
    if ev:
        for failure in ev["failing"]:
            exceptions.append({
                "id": f"eval-{failure['metric']}", "severity": "Critical" if failure["zeroTolerance"] else "High",
                "domain": "Evaluation & Release Readiness",
                "title": f"Evaluation gate failed: {failure['metric'].replace('_', ' ')} {failure['value']} vs threshold {failure['threshold']}",
                "detail": f"Run {ev['runId']} · {ago(_utc(datetime.fromisoformat(ev['createdAt'])), now)}",
                "href": "/evaluation-gates",
            })
    if review["overdue"]:
        exceptions.append({
            "id": "review-overdue", "severity": "High", "domain": "Human Accountability",
            "title": f"{_plural(review['overdue'], 'review case')} open longer than {REVIEW_OVERDUE_DAYS} days",
            "detail": f"{review['open']} open · {review['highOpen']} high risk", "href": "/review-tasks",
        })
    for right, title in src["expiredLicences"]:
        exceptions.append({"id": right.id, "severity": "High", "domain": "Source & Knowledge Governance",
                           "title": f"Licence expired for {_short(title, 80)}", "detail": f"Operation: {right.operation}",
                           "href": "/source-licensing"})
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    exceptions.sort(key=lambda e: order.get(e["severity"], 4))
    critical = sum(1 for e in exceptions if e["severity"] == "Critical")
    high = sum(1 for e in exceptions if e["severity"] == "High")

    decisions: list[dict] = []
    if perms["sourceManage"]:
        for version, title in src["proposedItems"]:
            decisions.append({"id": version.id, "severity": "MEDIUM", "kind": "SOURCE APPROVAL",
                              "title": f"Approve {version.version_label} of {_short(title, 80)}",
                              "due": f"Submitted {ago(version.created_at, now)}", "href": "/source-library"})
    if perms["safetyManage"]:
        for case in esc["overdueItems"][:2]:
            decisions.append({"id": case.id, "severity": case.risk_level.value, "kind": "ESCALATION",
                              "title": _short(case.topic or case.query_text, 90),
                              "due": f"SLA passed {ago(case.sla_deadline, now)}", "href": "/escalation-queue"})
    if perms["review"] and perms["reviewResolve"]:
        for item in review["items"][:3]:
            decisions.append({"id": item["id"], "severity": item["risk"], "kind": "ANSWER REVIEW",
                              "title": item["title"], "due": f"Waiting {item['age'].replace(' ago', '')}", "href": "/review-tasks"})
    pending_total = ((src["proposed"] if perms["sourceManage"] else 0)
                     + (esc["open"] if perms["safetyManage"] else 0)
                     + (review["open"] if perms["review"] and perms["reviewResolve"] else 0))
    blocked_gates = 1 if ev and ev["failing"] else 0

    domains: list[dict] = []
    domains.append({
        "key": "ai_safety", "name": "AI Safety & Risk Controls", "href": "/escalation-queue",
        "state": "Attention required" if esc["overdue"] else ("Effective" if esc["total"] or classified else "Not assessed"),
        "metric": f"Escalations closed {esc['closed']}/{esc['total']}",
        "exceptions": _exceptions_label(0, 1 if esc["overdue"] else 0),
        "freshness": _freshness(_iso(latest_safety) or esc["latestAt"], now, window_days),
        "next": f"Resolve {_plural(esc['overdue'], 'overdue escalation')}" if esc["overdue"] else "None scheduled",
    })
    src_exc = (1 if src["proposed"] else 0) + len(src["expiredLicences"]) + (1 if src["restrictedLicence"] else 0)
    domains.append({
        "key": "sources", "name": "Source & Knowledge Governance", "href": "/source-library",
        "state": ("Attention required" if src["expiredLicences"] else
                  "Effective with observations" if (src["proposed"] or src["unreviewed"] or src["expiringLicences"]) else
                  "Effective" if src["total"] else "Not assessed"),
        "metric": f"Versions reviewed {src['reviewed']}/{src['inUse']}",
        "exceptions": _exceptions_label(0, len(src["expiredLicences"]), src_exc - len(src["expiredLicences"])),
        "freshness": _freshness(src["latestAt"], now, window_days),
        "next": (f"Approve {_plural(src['proposed'], 'proposed version')}" if src["proposed"]
                 else f"Quality-review {_plural(src['unreviewed'], 'version')}" if src["unreviewed"] else "None scheduled"),
    })
    if ev:
        zero_fail = any(f["zeroTolerance"] for f in ev["failing"])
        passed = sum(1 for r in ev["results"] if r["passed"])
        domains.append({
            "key": "evaluation", "name": "Evaluation & Release Readiness", "href": "/evaluation-gates",
            "state": "Control failure" if zero_fail else ("Attention required" if ev["failing"] or ev["status"] == "FAILED" else "Effective" if ev["status"] == "COMPLETED" and ev["results"] else "Not assessed"),
            "metric": f"Metrics passing {passed}/{len(ev['results'])}",
            "exceptions": _exceptions_label(sum(1 for f in ev["failing"] if f["zeroTolerance"]),
                                            sum(1 for f in ev["failing"] if not f["zeroTolerance"])),
            "freshness": _freshness(ev["createdAt"], now, window_days),
            "next": ("Re-run evaluation after fixing " + ", ".join(f["metric"].replace("_", " ") for f in ev["failing"][:2])
                     if ev["failing"] else "None scheduled"),
        })
    else:
        domains.append({"key": "evaluation", "name": "Evaluation & Release Readiness", "href": "/evaluation-gates",
                        "state": "Not assessed", "metric": "No evaluation runs", "exceptions": "None",
                        "freshness": _freshness(None, now, window_days), "next": "Run the first evaluation"})
    sev = inc["openBySeverity"]
    domains.append({
        "key": "audit", "name": "Audit & Incident Readiness", "href": "/incident-response",
        "state": "Control failure" if sev["critical"] else ("Attention required" if inc["open"] else "Effective" if inc["total"] or audit_in_window else "Not assessed"),
        "metric": f"Incidents resolved {inc['total'] - inc['open']}/{inc['total']}",
        "exceptions": _exceptions_label(sev["critical"], sev["high"], sev["medium"] + sev["low"]),
        "freshness": _freshness(_iso(last_audit), now, window_days),
        "next": f"Contain {_plural(inc['open'], 'open incident')}" if inc["open"] else "None scheduled",
    })
    domains.append({
        "key": "boundaries", "name": "Professional Boundaries", "href": "/professional-boundaries",
        "state": ("Effective with observations" if uncertain else "Effective") if classified else "Not assessed",
        "metric": f"{refusals} boundary refusals · {classified} questions classified",
        "exceptions": f"{uncertain} uncertain classifications" if uncertain else "None",
        "freshness": _freshness(_iso(latest_safety), now, window_days),
        "next": "Review uncertain classifications" if uncertain else "None scheduled",
    })
    domains.append({
        "key": "accountability", "name": "Human Accountability", "href": "/review-tasks",
        "state": "Attention required" if review["overdue"] else ("Effective" if review["total"] else "Not assessed"),
        "metric": f"Reviews resolved {review['resolved']}/{review['total']}",
        "exceptions": _exceptions_label(0, 1 if review["overdue"] else 0),
        "freshness": _freshness(review["latestAt"], now, window_days),
        "next": f"Clear {_plural(review['overdue'], 'overdue review')}" if review["overdue"] else "None scheduled",
    })
    domains.append({
        "key": "jurisdiction", "name": "Jurisdiction & Provider Coverage", "href": "/jurisdiction-rollout",
        "state": "Effective" if src["jurisdictions"] else "Not assessed",
        "metric": f"{_plural(len(src['jurisdictions']), 'jurisdiction')} covered",
        "exceptions": "None",
        "freshness": _freshness(src["latestAt"], now, window_days),
        "next": ", ".join(src["jurisdictions"]) if src["jurisdictions"] else "Load approved sources",
    })

    stale = [d["name"] for d in domains if d["freshness"]["state"] != "current"]
    return {
        "scope": {
            "workspaceName": meta["tenantName"], "environment": environment,
            "jurisdictions": src["jurisdictions"], "windowDays": window_days,
            "windowStart": window_start.isoformat(), "windowEnd": now.isoformat(),
            "policyVersion": meta["policyVersion"],
            "evidenceFreshness": "degraded" if stale else "current",
            "auditLedger": {"lastEventAt": _iso(last_audit), "lastEventAge": ago(last_audit, now),
                            "eventsInWindow": audit_in_window},
        },
        "summary": {"criticalExceptionCount": critical, "highExceptionCount": high,
                    "pendingDecisionCount": pending_total, "blockedGateCount": blocked_gates},
        "staleDomains": stale,
        "domains": domains,
        "exceptions": exceptions,
        "decisions": decisions,
        "panels": {
            "sources": {
                "state": domains[1]["state"],
                "lines": [
                    f"{src['inUse']} source versions in use · {src['reviewed']} quality-reviewed",
                    f"{_plural(src['proposed'], 'version')} awaiting approval",
                    f"{_plural(len(src['expiringLicences']), 'licence')} expiring within {LICENCE_HORIZON_DAYS} days"
                    + (f" · {len(src['expiredLicences'])} expired" if src["expiredLicences"] else ""),
                    f"{_plural(src['restrictedLicence'], 'source')} with a restricted licence",
                    f"{_plural(src['withdrawn'], 'version')} withdrawn",
                ],
            },
            "audit": {
                "state": domains[3]["state"],
                "lines": [
                    f"{audit_in_window:,} audit events recorded in the last {window_days} days",
                    f"Latest audit event {ago(last_audit, now)}",
                    f"{sev['critical']} critical / {sev['high']} high open incidents",
                    f"{_plural(esc['open'], 'escalation')} in progress · {esc['overdue']} past SLA",
                ],
            },
        },
        "generatedAt": now.isoformat(),
    }
