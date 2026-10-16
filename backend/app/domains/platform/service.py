"""Super Admin Command Center: platform metadata across every tenant.

The control plane reads with the owner connection (RLS does not apply), so
this module is the boundary that keeps it to metadata (PRIV-01): counts,
states, references, tenant names and timestamps. It never returns a ticket
or incident body, a break-glass reason, a dispute reason, prompts, answers or
any financial record beyond statement totals and meter-level dispute flags.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import session_is_sqlite
from app.domains.admin_governance.models import ReleaseCandidate
from app.domains.admin_governance.releases import MANUAL
from app.domains.audit_ledger.models import AuditEvent
from app.domains.billing.models import BillingAdjustment, BillingPlan, BillingStatement
from app.domains.evaluation.models import EvaluationRun
from app.domains.identity.models import BreakGlassGrant, Tenant, User
from app.domains.operations import service as operations
from app.domains.operations.models import ProviderRecord, ServiceHealthSample
from app.domains.review_console.models import AuditExportRequest
from app.domains.support_incident.models import SecurityIncident

PLATFORM_ROLES = frozenset({"super_admin"})
RELEASE_DONE = ("deployed", "rolled_back")
PROVIDER_PENDING = ("under_review", "conditional")
PROVIDER_BLOCKED = ("on_hold", "suspended")
PRIORITY = {"Critical": 0, "High": 1, "Medium": 2}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


async def _tenant_isolation(db: AsyncSession) -> dict:
    """The startup RLS check, run live. Fails closed on any error."""
    if session_is_sqlite(db):
        return {"state": "unknown", "detail": "Not assessable on a SQLite database"}
    from app.main import _verify_security_policies
    try:
        await _verify_security_policies()
        return {"state": "pass", "detail": "Row-level security enforced on every tenant table"}
    except Exception as exc:  # noqa: BLE001 — a missing policy and a fault both fail closed
        return {"state": "fail", "detail": str(exc)[:200]}


async def _health(db: AsyncSession, now: datetime) -> dict:
    latest = (select(ServiceHealthSample.service_key, func.max(ServiceHealthSample.checked_at).label("at"))
              .where(ServiceHealthSample.checked_at >= now - timedelta(minutes=15))
              .group_by(ServiceHealthSample.service_key).subquery())
    samples = (await db.execute(select(ServiceHealthSample).join(
        latest, (ServiceHealthSample.service_key == latest.c.service_key)
        & (ServiceHealthSample.checked_at == latest.c.at)))).scalars().all()
    services = [{"key": s.service_key, "name": operations.SERVICE_NAMES.get(s.service_key, s.service_key),
                 "state": s.state, "core": s.service_key in operations.CORE_SERVICES,
                 "latencyMs": round(s.latency_ms) if s.latency_ms is not None else None, "checkedAt": _iso(s.checked_at)}
                for s in samples]
    services.sort(key=lambda s: (s["state"] == "operational", not s["core"], s["name"]))

    up = func.sum(case((ServiceHealthSample.state.in_(("operational", "degraded")), 1), else_=0))
    total, ups = (await db.execute(
        select(func.count(), up).where(ServiceHealthSample.service_key == "api",
                                       ServiceHealthSample.checked_at >= now - timedelta(days=30),
                                       ServiceHealthSample.state != "not_configured"))).one()
    latencies = sorted(v for (v,) in (await db.execute(
        select(ServiceHealthSample.latency_ms).where(ServiceHealthSample.service_key == "api",
                                                     ServiceHealthSample.checked_at >= now - timedelta(hours=24),
                                                     ServiceHealthSample.latency_ms.is_not(None)))).all())
    p95 = latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))] if latencies else None
    measured = [s for s in services if s["state"] != "not_configured"]
    return {
        "services": services,
        "sampled": bool(samples),
        "availabilityPct": round(100 * (ups or 0) / total, 2) if total else None,
        "objectivePct": get_settings().OPS_AVAILABILITY_OBJECTIVE_PCT,
        "p95LatencyMs": round(p95) if p95 is not None else None,
        "degraded": sum(s["state"] != "operational" for s in measured),
        "measured": len(measured),
        "coreDown": [s["name"] for s in measured if s["core"] and s["state"] == "down"],
    }


async def _evaluation(db: AsyncSession) -> dict:
    runs = (await db.execute(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(10))).scalars().all()
    if not runs:
        return {"state": "unknown", "latest": None, "metrics": [], "recent": {"completed": 0, "failed": 0}}
    latest = runs[0]
    metrics = [{"name": k, "value": v} for k, v in (latest.metrics_summary or {}).items() if isinstance(v, (int, float))]
    return {"state": "fail" if latest.status == "FAILED" else "pass" if latest.status == "COMPLETED" else "pending",
            "latest": {"id": latest.id, "status": latest.status, "at": _iso(latest.created_at)},
            "metrics": metrics[:6],
            "recent": {"completed": sum(r.status == "COMPLETED" for r in runs), "failed": sum(r.status == "FAILED" for r in runs)}}


async def command_overview(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    tenants = {t.id: t.name for t in (await db.execute(select(Tenant))).scalars().all()}

    # ── Tenants: counts only ───────────────────────────────────────────────
    users_by_tenant = dict((await db.execute(
        select(User.tenant_id, func.count()).where(User.is_active.is_(True)).group_by(User.tenant_id))).all())
    active_30d = {t for (t,) in (await db.execute(
        select(AuditEvent.tenant_id).where(AuditEvent.ingested_at >= now - timedelta(days=30)).distinct())).all()}
    planned = {t for (t,) in (await db.execute(
        select(BillingPlan.tenant_id).where(BillingPlan.status == "active").distinct())).all()}

    # ── Incidents: severity and state, never the body ──────────────────────
    incidents = (await db.execute(select(SecurityIncident).where(SecurityIncident.containment_status != "RESOLVED"))).scalars().all()
    critical_incidents = [i for i in incidents if (i.severity or "").lower() == "critical"]

    # ── Privileged access: no reasons, no permissions content ──────────────
    grants = (await db.execute(select(BreakGlassGrant).where(
        (BreakGlassGrant.status.in_(("requested", "active")))
        | ((BreakGlassGrant.status.in_(("expired", "revoked"))) & BreakGlassGrant.reviewed_at.is_(None))))).scalars().all()
    requested = [g for g in grants if g.status == "requested"]
    active = [g for g in grants if g.status == "active" and (_aware(g.expires_at) or now) > now]
    unreviewed = [g for g in grants if g.status in ("expired", "revoked")
                  or (g.status == "active" and (_aware(g.expires_at) or now) <= now)]

    # ── Releases: a failed platform check holds every open candidate ──────
    isolation = await _tenant_isolation(db)
    health = await _health(db, now)
    releases = (await db.execute(select(ReleaseCandidate).where(ReleaseCandidate.status.not_in(RELEASE_DONE)))).scalars().all()
    platform_block = isolation["state"] == "fail" or bool(health["coreDown"])
    held = [r for r in releases if platform_block or any((r.gates.get(k) or {}).get("status") == "fail" for k in MANUAL)]

    # ── Providers ─────────────────────────────────────────────────────────
    providers = (await db.execute(select(ProviderRecord))).scalars().all()
    provider_pending = [p for p in providers if p.decision in PROVIDER_PENDING]
    provider_blocked = [p for p in providers if p.decision in PROVIDER_BLOCKED]
    provider_overdue = [p for p in providers if p.next_review_at and _aware(p.next_review_at) < now]

    # ── Commercial: totals and dispute flags only ──────────────────────────
    statements = (await db.execute(select(BillingStatement))).scalars().all()
    unpaid = [s for s in statements if s.status == "issued"]
    invoiced: dict[str, int] = defaultdict(int)
    collected: dict[str, int] = defaultdict(int)
    receivable: dict[str, int] = defaultdict(int)
    for s in statements:
        if (_aware(s.issued_at) or now).strftime("%Y-%m") == month:
            invoiced[s.currency] += s.total_cents
        if s.status == "paid" and s.paid_at and _aware(s.paid_at).strftime("%Y-%m") == month:
            collected[s.currency] += s.total_cents
        if s.status == "issued":
            receivable[s.currency] += s.total_cents
    adjustments = (await db.execute(select(BillingAdjustment).where(
        BillingAdjustment.status.in_(("open", "pending"))))).scalars().all()
    disputes = [a for a in adjustments if a.kind == "dispute"]
    credits = [a for a in adjustments if a.kind == "credit"]

    # ── Audit & evidence ─────────────────────────────────────────────────
    exports_pending = (await db.execute(select(func.count()).select_from(AuditExportRequest)
                                        .where(AuditExportRequest.status == "pending"))).scalar_one()
    events_24h = (await db.execute(select(func.count()).select_from(AuditEvent)
                                   .where(AuditEvent.ingested_at >= now - timedelta(hours=24)))).scalar_one()
    denied_30d = (await db.execute(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.event_name == "access_denied", AuditEvent.ingested_at >= now - timedelta(days=30)))).scalar_one()

    evaluation = await _evaluation(db)

    # ── Executive decision queue ─────────────────────────────────────────
    decisions: list[dict] = []
    for i in critical_incidents:
        decisions.append({"id": i.id, "ref": i.id.upper(), "priority": "Critical", "title": "Critical security incident open",
                          "area": "Security incident", "owner": "Security", "tenant": tenants.get(i.tenant_id, "Unknown tenant"),
                          "since": _iso(i.opened_at), "state": i.containment_status.title()})
    for g in requested:
        decisions.append({"id": g.id, "ref": f"BG-{g.id[:6].upper()}", "priority": "Critical",
                          "title": f"Emergency access request · {g.duration_minutes} min",
                          "area": "Privileged access", "owner": "Security approver", "tenant": tenants.get(g.tenant_id, "Unknown tenant"),
                          "since": _iso(g.requested_at), "state": "Awaiting independent approval"})
    for r in held:
        decisions.append({"id": r.id, "ref": r.ref, "priority": "High", "title": f"{r.name} {r.version} release hold",
                          "area": "Release", "owner": "Release approver", "tenant": tenants.get(r.tenant_id, "Unknown tenant"),
                          "since": _iso(r.created_at), "state": "Mandatory gate failed"})
    for p in provider_blocked + [p for p in provider_pending if p.criticality in ("high", "critical")]:
        decisions.append({"id": p.id, "ref": p.ref, "priority": "High" if p in provider_blocked else "Medium",
                          "title": f"{p.name}: {p.decision.replace('_', ' ')}", "area": "Provider risk", "owner": "Provider risk",
                          "tenant": tenants.get(p.tenant_id, "Unknown tenant"), "since": _iso(p.updated_at), "state": "Decision needed"})
    for g in unreviewed:
        decisions.append({"id": g.id, "ref": f"BG-{g.id[:6].upper()}", "priority": "Medium", "title": "Ended emergency access needs post-access review",
                          "area": "Privileged access", "owner": "Security", "tenant": tenants.get(g.tenant_id, "Unknown tenant"),
                          "since": _iso(g.ended_at or g.expires_at), "state": "Review outstanding"})
    for a in disputes:
        decisions.append({"id": a.id, "ref": f"BIL-{a.id[:6].upper()}", "priority": "Medium",
                          "title": f"Usage charge under dispute · {a.period}", "area": "Billing assurance", "owner": "Billing assurance",
                          "tenant": tenants.get(a.tenant_id, "Unknown tenant"), "since": _iso(a.created_at), "state": "Open dispute"})
    decisions.sort(key=lambda d: (PRIORITY.get(d["priority"], 9), d["since"] or ""))
    by_priority = Counter(d["priority"] for d in decisions)

    # ── Assurance controls: each from its own evidence, never averaged ───
    def control(key: str, label: str, state: str, detail: str) -> dict:
        return {"key": key, "label": label, "state": state, "detail": detail}

    controls = [
        control("isolation", "Tenant isolation", isolation["state"], isolation["detail"]),
        control("privileged", "Privileged access", "review" if requested or unreviewed else "pass",
                f"{len(requested)} awaiting approval · {len(active)} active · {len(unreviewed)} awaiting review"),
        control("releases", "Release gates", "fail" if held else "pass" if releases else "unknown",
                f"{len(held)} held of {len(releases)} open" if releases else "No open release candidates"),
        control("evaluation", "Kriton evaluations", evaluation["state"],
                f"Latest run {evaluation['latest']['status'].lower()}" if evaluation["latest"] else "No evaluation run recorded"),
        control("providers", "Provider risk", "fail" if provider_blocked else "review" if provider_pending or provider_overdue else
                "pass" if providers else "unknown",
                f"{len(provider_blocked)} blocked · {len(provider_pending)} in review · {len(provider_overdue)} overdue review"),
        control("resilience", "Operational resilience", "unknown" if not health["sampled"] else
                "fail" if health["coreDown"] else "review" if health["degraded"] else "pass",
                "No health samples in the last 15 minutes" if not health["sampled"] else
                f"{health['degraded']} of {health['measured']} services not operational"),
        control("billing", "Billing integrity", "review" if disputes else "pass",
                f"{len(disputes)} open dispute(s) · {len(credits)} credit(s) pending"),
    ]
    exceptions = sum(c["state"] in ("fail", "review") for c in controls)

    return {
        "generatedAt": now.isoformat(),
        "summary": {
            "criticalIncidents": len(critical_incidents), "openIncidents": len(incidents),
            "unassignedIncidents": sum(1 for i in incidents if not i.assigned_to),
            "releaseHolds": len(held), "openReleases": len(releases),
            "decisions": len(decisions), "decisionsByPriority": dict(by_priority),
            "isolation": isolation["state"],
            "availabilityPct": health["availabilityPct"], "objectivePct": health["objectivePct"],
            "privilegedRequests": len(requested) + len(unreviewed), "privilegedAwaitingApproval": len(requested),
            "controlExceptions": exceptions,
        },
        "decisions": decisions[:20],
        "controls": controls,
        "health": health,
        "evaluation": evaluation,
        "releases": {"open": len(releases), "held": len(held),
                     "items": [{"ref": r.ref, "name": r.name, "version": r.version, "held": r in held,
                                "tenant": tenants.get(r.tenant_id, "Unknown tenant")} for r in releases[:5]]},
        "tenants": {"total": len(tenants), "withUsers": sum(1 for t in tenants if users_by_tenant.get(t)),
                    "active30d": len(active_30d & set(tenants)), "users": sum(users_by_tenant.values()),
                    "withApprovedPlan": len(planned & set(tenants))},
        "commercial": {"month": month, "invoiced": dict(invoiced), "collected": dict(collected), "receivable": dict(receivable),
                       "unpaidStatements": len(unpaid), "openDisputes": len(disputes), "pendingCredits": len(credits)},
        "privileged": {"awaitingApproval": len(requested), "active": len(active), "awaitingReview": len(unreviewed),
                       "activeGrants": [{"ref": f"BG-{g.id[:6].upper()}", "tenant": tenants.get(g.tenant_id, "Unknown tenant"),
                                         "expiresAt": _iso(g.expires_at)} for g in active]},
        "audit": {"events24h": events_24h, "exportsPending": exports_pending, "deniedAttempts30d": denied_30d},
    }
