"""Governance Dashboard assessment (Admin Governance Console spec §4).

Builds the dashboard from the tenant's real governance records:
  * health cards  — source approval, licence status, risk-policy deployment,
                    escalation SLA, incidents, audit-ledger integrity, plus
                    jurisdiction readiness and localisation backlog;
  * alerts        — derived from live conditions, each with an owner role, a
                    due time where one exists, and a drill-down;
  * work queues   — pending approvals the viewer is actually permitted to act on;
  * release readiness — the conditions currently blocking a release.

The rule this module exists to keep: never show a number the platform did not
measure. Anything without a data source yet is returned as "not_assessed"
with the reason, instead of a sample value or an inferred healthy state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger import service as audit_service
from app.domains.evaluation.models import EvaluationRun, ResultPack
from app.domains.identity.models import BreakGlassGrant, User
from app.domains.identity.permissions import (
    REVIEW_RESOLVE,
    SAFETY_MANAGE,
    SOURCE_MANAGE,
    user_has_permission,
)
from app.domains.risk_safety.models import EscalationCase, EscalationStatus, RiskPolicy
from app.domains.source_library.models import Source, SourceVersion
from app.domains.support_incident.models import SecurityIncident
from app.orchestration.models import ReviewCase

# Worst first: the overall state is the worst domain state.
STATE_ORDER = ["critical", "attention", "effective", "not_assessed"]
SEVERITY_ORDER = ["critical", "high", "medium", "low"]
EXPIRY_WARNING_DAYS = 30
OPEN_ESCALATION = (EscalationStatus.PENDING, EscalationStatus.UNDER_REVIEW, EscalationStatus.ESCALATED)
OPEN_REVIEW = ("open", "needs_evidence")
APPROVED_VERSION = ("ACTIVE", "APPROVED")
SEED_APPROVERS = {"system-init", "system", "seed"}
MAX_ALERTS_PER_KIND = 10
MAX_QUEUE_ITEMS = 25


@dataclass
class Assessment:
    domains: list[dict] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)
    queue: list[dict] = field(default_factory=list)
    release: list[dict] = field(default_factory=list)
    incident_counts: dict[str, int] = field(default_factory=dict)


def _aware(value: datetime | None) -> datetime | None:
    # risk_safety and evaluation store naive UTC; normalise for comparisons.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _domain(key, label, state, headline, metrics, href, reason=None) -> dict:
    return {
        "key": key, "label": label, "state": state, "headline": headline,
        "metrics": [{"label": k, "value": v} for k, v in metrics], "drilldownTarget": href, "reason": reason,
    }


def _alert(kind, severity, domain, title, owner, href, *, ref, due=None, opened=None) -> dict:
    return {
        "id": f"{kind}:{ref}", "severity": severity, "domain": domain, "title": title,
        "ownerRole": owner, "dueAt": _iso(due), "openedAt": _iso(opened), "drilldownTarget": href,
        # Alerts are derived from live records: one clears when its underlying
        # record is resolved there, which is where the resolution note lives.
        "resolvedBy": "Resolving the underlying record",
    }


def _visible_sources(tenant_id: str):
    """Shared sources plus this tenant's private ones (the RLS rule, applied
    explicitly so SQLite/tests and superuser sessions behave the same)."""
    return (Source.is_tenant_private.is_(False)) | (Source.tenant_id == tenant_id)


def _count(model, *conditions):
    return select(func.count()).select_from(model).where(*conditions).scalar_subquery()


def _version_count(tenant_id: str, *conditions):
    return (select(func.count()).select_from(SourceVersion).join(Source, Source.id == SourceVersion.source_id)
            .where(_visible_sources(tenant_id), *conditions).scalar_subquery())


async def _snapshot(db: AsyncSession, tenant_id: str, today: date, now: datetime) -> dict[str, int]:
    """Every count the assessment needs, in ONE round trip. Detail rows are
    then fetched only for sections that have something to list, so a quiet
    tenant costs a handful of queries instead of ~28 — which matters when the
    database is a network hop away (each round trip is 100–250 ms remotely)."""
    now_naive = now.astimezone(timezone.utc).replace(tzinfo=None)  # risk_safety stores naive UTC
    open_incident = (SecurityIncident.tenant_id == tenant_id, SecurityIncident.containment_status != "RESOLVED")
    counts = {
        "versions_total": _version_count(tenant_id),
        "versions_approved": _version_count(tenant_id, SourceVersion.status.in_(APPROVED_VERSION)),
        "versions_expired": _version_count(tenant_id, SourceVersion.status == "EXPIRED"),
        "versions_withdrawn": _version_count(tenant_id, SourceVersion.status == "WITHDRAWN"),
        "versions_expiring": _version_count(
            tenant_id, SourceVersion.status.in_(APPROVED_VERSION), SourceVersion.effective_to.is_not(None),
            SourceVersion.effective_to <= today + timedelta(days=EXPIRY_WARNING_DAYS)),
        # Only this tenant's own submissions await its approval: a shared source
        # proposed by another tenant is not this tenant's decision.
        "pending_own": _count(SourceVersion, SourceVersion.tenant_id == tenant_id, SourceVersion.status == "PROPOSED"),
        "licences_total": _count(Source, _visible_sources(tenant_id)),
        "licences_permitted": _count(Source, _visible_sources(tenant_id), Source.licence_state == "permitted"),
        "licences_restricted": _count(Source, _visible_sources(tenant_id), Source.licence_state == "restricted"),
        "licences_unknown": _count(Source, _visible_sources(tenant_id),
                                   (Source.licence_state == "unknown") | (Source.licence_state.is_(None))),
        "escalations_open": _count(EscalationCase, EscalationCase.tenant_id == tenant_id,
                                   EscalationCase.status.in_(OPEN_ESCALATION)),
        "escalations_actionable": _count(EscalationCase, EscalationCase.tenant_id == tenant_id,
                                         EscalationCase.status.in_((EscalationStatus.PENDING, EscalationStatus.UNDER_REVIEW))),
        "escalations_past_sla": _count(EscalationCase, EscalationCase.tenant_id == tenant_id,
                                       EscalationCase.status.in_(OPEN_ESCALATION),
                                       EscalationCase.sla_deadline < now_naive),
        "reviews_open": _count(ReviewCase, ReviewCase.tenant_id == tenant_id, ReviewCase.status.in_(OPEN_REVIEW)),
        "incidents_open": _count(SecurityIncident, *open_incident),
        **{f"incidents_{level}": _count(SecurityIncident, *open_incident, func.lower(SecurityIncident.severity) == level)
           for level in ("critical", "high", "medium", "low", "informational")},
        "break_glass_unreviewed": _count(BreakGlassGrant, BreakGlassGrant.tenant_id == tenant_id,
                                         BreakGlassGrant.status.in_(("expired", "revoked")),
                                         BreakGlassGrant.reviewed_at.is_(None)),
        "break_glass_requested": _count(BreakGlassGrant, BreakGlassGrant.tenant_id == tenant_id,
                                        BreakGlassGrant.status == "requested"),
    }
    row = (await db.execute(select(*(query.label(name) for name, query in counts.items())))).one()
    return dict(row._mapping)


async def _sources(db: AsyncSession, a: Assessment, snap: dict, tenant_id: str, today: date) -> None:
    pending = snap["pending_own"]
    approved = snap["versions_approved"]
    if snap["versions_total"] == 0:
        a.domains.append(_domain("source_approval", "Source approval health", "not_assessed",
                                 "No sources registered yet", [], "/source-library",
                                 "Register and approve sources in the Source Library to assess this."))
    else:
        a.domains.append(_domain(
            "source_approval", "Source approval health", "attention" if pending else "effective",
            f"{pending} version(s) awaiting approval" if pending else "No versions awaiting approval",
            [("Approved / active", approved), ("Awaiting approval", pending),
             ("Expired", snap["versions_expired"]), ("Withdrawn", snap["versions_withdrawn"])],
            "/source-library",
        ))

    expiring = []
    if snap["versions_expiring"]:
        expiring = list((await db.execute(
            select(SourceVersion, Source.title)
            .join(Source, Source.id == SourceVersion.source_id)
            .where(
                _visible_sources(tenant_id),
                SourceVersion.status.in_(APPROVED_VERSION),
                SourceVersion.effective_to.is_not(None),
                SourceVersion.effective_to <= today + timedelta(days=EXPIRY_WARNING_DAYS),
            )
            .order_by(SourceVersion.effective_to)
        )).all())
    lapsed = [(v, t) for v, t in expiring if v.effective_to < today]
    unknown = snap["licences_unknown"]
    licences = {"permitted": snap["licences_permitted"], "restricted": snap["licences_restricted"]}
    if not snap["licences_total"]:
        a.domains.append(_domain("licence_status", "Licence status", "not_assessed", "No sources registered yet",
                                 [], "/source-licensing", "No licensed sources to assess."))
    else:
        state = "critical" if lapsed else ("attention" if expiring or unknown else "effective")
        a.domains.append(_domain(
            "licence_status", "Licence status", state,
            f"{len(lapsed)} approved version(s) past their end date" if lapsed
            else f"{len(expiring)} expiring within {EXPIRY_WARNING_DAYS} days" if expiring
            else f"{unknown} source(s) with unknown licence" if unknown else "All licences in date",
            [("Permitted", licences.get("permitted", 0)), ("Restricted", licences.get("restricted", 0)),
             ("Unknown", unknown), (f"Expiring ≤{EXPIRY_WARNING_DAYS}d", len(expiring))],
            "/source-licensing",
        ))
    for version, title in expiring[:MAX_ALERTS_PER_KIND]:
        past = version.effective_to < today
        a.alerts.append(_alert(
            "licence", "high" if past else "medium", "Licence status",
            f"“{title}” {version.version_label} {'passed its end date' if past else 'expires soon'} "
            f"({version.effective_to.isoformat()})",
            "Source Admin", "/source-licensing", ref=version.id,
            due=datetime.combine(version.effective_to, datetime.min.time(), tzinfo=timezone.utc),
        ))
    if unknown:
        a.alerts.append(_alert("licence-unknown", "medium", "Licence status",
                               f"{unknown} source(s) have an unknown licence state", "Source Admin",
                               "/source-licensing", ref="unknown"))


async def _risk_policy(db: AsyncSession, a: Assessment) -> None:
    policy = (await db.execute(select(RiskPolicy).order_by(RiskPolicy.created_at.desc()).limit(1))).scalars().first()
    if policy is None:
        a.domains.append(_domain("risk_policy", "Risk-policy deployment", "not_assessed", "No risk policy deployed",
                                 [], "/risk-policy", "No risk policy version is recorded."))
        return
    # Spec: no production risk-policy version without a named AI Risk Committee
    # approver. The startup seed records "system-init", which is a placeholder,
    # not a person, so it does not count as approval.
    approved = bool(policy.approver) and policy.approver not in SEED_APPROVERS
    a.domains.append(_domain(
        "risk_policy", "Risk-policy deployment", "effective" if approved else "attention",
        f"Version {policy.version} in force" + ("" if approved else " — no named approver"),
        [("Version", policy.version), ("Approver", policy.approver if approved else "No named approver"),
         ("Effective from", _iso(_aware(policy.effective_from))), ("Rules", len(policy.rules or []))],
        "/risk-policy",
    ))
    if not approved:
        a.alerts.append(_alert("risk-policy", "high", "Risk-policy deployment",
                               f"Risk policy {policy.version} is in force without a named approver",
                               "Risk Admin", "/risk-policy", ref=policy.id, opened=_aware(policy.created_at)))


async def _escalations(db: AsyncSession, a: Assessment, snap: dict, tenant_id: str, now: datetime) -> None:
    open_count, past_count, open_reviews = snap["escalations_open"], snap["escalations_past_sla"], snap["reviews_open"]
    over = []
    if past_count:
        over = list((await db.execute(
            select(EscalationCase).where(
                EscalationCase.tenant_id == tenant_id, EscalationCase.status.in_(OPEN_ESCALATION),
                EscalationCase.sla_deadline < now.astimezone(timezone.utc).replace(tzinfo=None),
            ).order_by(EscalationCase.sla_deadline).limit(MAX_ALERTS_PER_KIND)
        )).scalars().all())
    state = "critical" if past_count else ("attention" if open_count or open_reviews else "effective")
    a.domains.append(_domain(
        "escalation_sla", "Escalation SLA", state,
        f"{past_count} escalation(s) past SLA" if past_count
        else f"{open_count} open, none past SLA" if open_count else "No open escalations",
        [("Open escalations", open_count), ("Past SLA", past_count), ("Open review cases", open_reviews)],
        "/escalation-queue",
    ))
    for case in over:
        a.alerts.append(_alert("escalation", "high", "Escalation SLA",
                               f"Escalation {case.id} ({case.topic}, {case.risk_level.value}) is past its SLA",
                               case.reviewer_role or "Risk Admin", "/escalation-queue", ref=case.id,
                               due=_aware(case.sla_deadline), opened=_aware(case.created_at)))


async def _incidents(db: AsyncSession, a: Assessment, snap: dict, tenant_id: str) -> dict[str, int]:
    levels = ["critical", "high", "medium", "low", "informational"]
    counts = {level: snap[f"incidents_{level}"] for level in levels}
    # An unrecognised severity label is counted as high, never dropped.
    counts["high"] += snap["incidents_open"] - sum(counts.values())
    open_incidents = []
    if snap["incidents_open"]:
        open_incidents = list((await db.execute(
            select(SecurityIncident).where(SecurityIncident.tenant_id == tenant_id,
                                           SecurityIncident.containment_status != "RESOLVED")
            .order_by(SecurityIncident.opened_at.desc()).limit(MAX_ALERTS_PER_KIND)
        )).scalars().all())
    severe = counts["critical"] + counts["high"]
    a.domains.append(_domain(
        "incidents", "Security incidents",
        "critical" if severe else ("attention" if snap["incidents_open"] else "effective"),
        f"{snap['incidents_open']} open incident(s)" if snap["incidents_open"] else "No open incidents",
        [("Critical", counts["critical"]), ("High", counts["high"]), ("Medium", counts["medium"]), ("Low", counts["low"])],
        "/incident-response",
    ))
    for incident in open_incidents:
        severity = incident.severity.lower()
        a.alerts.append(_alert("incident", "critical" if severity == "critical" else "high" if severity == "high" else "medium",
                               "Security incidents", f"{incident.title} ({incident.containment_status.lower()})",
                               incident.assigned_to or "Security lead", "/incident-response", ref=incident.id,
                               opened=_aware(incident.opened_at)))
    return counts


async def _ledger(db: AsyncSession, a: Assessment, tenant_id: str) -> bool:
    chain = await audit_service.verify_tenant_chain(db, tenant_id)
    passed = chain["passed"]
    a.domains.append(_domain(
        "audit_ledger", "Audit-ledger integrity", "effective" if passed else "critical",
        f"Hash chain verified across {chain['events_checked']} event(s)" if passed else "Hash chain verification FAILED",
        [("Events verified", chain["events_checked"]), ("Chain", "Intact" if passed else "Broken")],
        "/audit-logs",
    ))
    if not passed:
        a.alerts.append(_alert("ledger", "critical", "Audit-ledger integrity",
                               f"Audit hash chain broken at event {chain['first_broken_event_id']}",
                               "System Auditor", "/audit-logs", ref=chain["first_broken_event_id"] or "chain"))
    return passed


async def _break_glass(db: AsyncSession, a: Assessment, snap: dict, tenant_id: str) -> None:
    if not snap["break_glass_unreviewed"]:
        return
    grants = list((await db.execute(
        select(BreakGlassGrant).where(BreakGlassGrant.tenant_id == tenant_id,
                                      BreakGlassGrant.status.in_(("expired", "revoked")),
                                      BreakGlassGrant.reviewed_at.is_(None))
        .limit(MAX_ALERTS_PER_KIND)
    )).scalars().all())
    for grant in grants:
        a.alerts.append(_alert("break-glass", "medium", "Elevated access",
                               "Ended break-glass grant awaiting post-use review", "Admin", "/break-glass",
                               ref=grant.id, opened=_aware(grant.ended_at)))


def _not_built(a: Assessment) -> None:
    a.domains.append(_domain("jurisdiction_readiness", "Jurisdiction pack readiness", "not_assessed",
                             "Not assessed", [], "/jurisdiction-rollout",
                             "Jurisdiction packs and their launch gate are not built yet."))
    a.domains.append(_domain("localization_backlog", "Localisation backlog", "not_assessed", "Not assessed", [],
                             "/tenant-settings", "Localisation administration is not built yet."))


async def _work_queue(db: AsyncSession, a: Assessment, snap: dict, viewer: User) -> None:
    """Pending decisions the viewer may act on — role-filtered, as the spec
    requires — with their own submissions flagged (maker-checker). Each list
    is only queried when the snapshot shows it has entries."""
    tenant_id = viewer.tenant_id
    if snap["pending_own"] and user_has_permission(viewer, SOURCE_MANAGE):
        rows = (await db.execute(
            select(SourceVersion, Source.title)
            .join(Source, Source.id == SourceVersion.source_id)
            .where(SourceVersion.tenant_id == tenant_id, SourceVersion.status == "PROPOSED")
            .order_by(SourceVersion.created_at).limit(MAX_QUEUE_ITEMS)
        )).all()
        for version, title in rows:
            own = version.submitted_by == viewer.id
            a.queue.append({"id": f"source:{version.id}", "type": "Source approval",
                            "title": f"Approve “{title}” {version.version_label}",
                            "submittedAt": _iso(_aware(version.created_at)), "drilldownTarget": "/source-library",
                            "blockedReason": "You submitted this — a second approver is required" if own else None})
    if snap["reviews_open"] and user_has_permission(viewer, REVIEW_RESOLVE):
        rows = (await db.execute(
            select(ReviewCase).where(ReviewCase.tenant_id == tenant_id, ReviewCase.status.in_(OPEN_REVIEW))
            .order_by(ReviewCase.created_at).limit(MAX_QUEUE_ITEMS)
        )).scalars().all()
        for case in rows:
            a.queue.append({"id": f"review:{case.id}", "type": "Answer review",
                            "title": (case.query_text or "Kriton answer awaiting review")[:120],
                            "submittedAt": _iso(_aware(case.created_at)), "drilldownTarget": "/review-tasks",
                            "blockedReason": None})
    if snap["escalations_actionable"] and user_has_permission(viewer, SAFETY_MANAGE):
        rows = (await db.execute(
            select(EscalationCase).where(EscalationCase.tenant_id == tenant_id,
                                         EscalationCase.status.in_((EscalationStatus.PENDING, EscalationStatus.UNDER_REVIEW)))
            .order_by(EscalationCase.created_at).limit(MAX_QUEUE_ITEMS)
        )).scalars().all()
        for case in rows:
            a.queue.append({"id": f"escalation:{case.id}", "type": "Escalation",
                            "title": f"{case.topic} — {case.risk_level.value} risk",
                            "submittedAt": _iso(_aware(case.created_at)), "drilldownTarget": "/escalation-queue",
                            "blockedReason": None})
    if snap["break_glass_requested"] and viewer.role == "Admin":
        rows = (await db.execute(
            select(BreakGlassGrant).where(BreakGlassGrant.tenant_id == tenant_id, BreakGlassGrant.status == "requested")
            .order_by(BreakGlassGrant.requested_at).limit(MAX_QUEUE_ITEMS)
        )).scalars().all()
        for grant in rows:
            own = grant.user_id == viewer.id
            a.queue.append({"id": f"break-glass:{grant.id}", "type": "Break-glass request",
                            "title": f"Emergency access: {', '.join(grant.permissions)}",
                            "submittedAt": _iso(_aware(grant.requested_at)), "drilldownTarget": "/break-glass",
                            "blockedReason": "Your own request — another Admin must approve" if own else None})


async def release_readiness(db: AsyncSession, a: Assessment, *, ledger_ok: bool) -> None:
    """Release gates from measured evidence (QA Test Plan & Release Gate spec):
    every gate is passed, blocked or explicitly not assessed — never assumed."""
    incident_counts = a.incident_counts
    # Latest run with its newest result pack, in one round trip.
    latest = (await db.execute(
        select(EvaluationRun, ResultPack)
        .outerjoin(ResultPack, ResultPack.run_id == EvaluationRun.id)
        .order_by(EvaluationRun.created_at.desc(), ResultPack.created_at.desc())
        .limit(1)
    )).first()
    if latest is None:
        a.release.append({"gate": "Evaluation", "state": "blocked", "reason": "No evaluation run has been recorded."})
    else:
        run, pack = latest
        if pack is None or not pack.promotion_eligible:
            why = []
            if pack is not None and pack.contamination_scan_status != "PASSED":
                why.append("gold-set contamination found")
            if pack is not None and not pack.zero_tolerance_passed:
                why.append("a zero-tolerance metric failed or was not measured")
            a.release.append({"gate": "Evaluation", "state": "blocked",
                              "reason": f"Latest run {run.id} is not promotion-eligible"
                                        + (f" ({'; '.join(why)})." if why else ".")})
        else:
            # The in-app run measures the safety classifier and output
            # validators against the gold set; end-to-end answer quality is
            # covered by the scripted release gate (scripts/release_gate.py).
            a.release.append({"gate": "Evaluation", "state": "passed",
                              "reason": f"Run {run.id} is promotion-eligible: contamination scan passed and the "
                                        "configuration matches the running code."})
    a.release.append({"gate": "Audit ledger", "state": "passed" if ledger_ok else "blocked",
                      "reason": "Hash chain intact." if ledger_ok else "Audit hash chain is broken."})
    severe = incident_counts["critical"] + incident_counts["high"]
    a.release.append({"gate": "Security incidents", "state": "blocked" if severe else "passed",
                      "reason": f"{severe} critical/high incident(s) open." if severe else "No critical or high incidents open."})
    for domain in a.domains:
        if domain["key"] == "risk_policy":
            ok = domain["state"] == "effective"
            a.release.append({"gate": "Risk policy approval", "state": "passed" if ok else "blocked",
                              "reason": "Named approver recorded." if ok else (domain["reason"] or domain["headline"])})
        if domain["key"] == "licence_status" and domain["state"] != "not_assessed":
            # Only lapsed licences block; expiring-soon is a warning, not a blocker.
            ok = domain["state"] != "critical"
            a.release.append({"gate": "Source licensing", "state": "passed" if ok else "blocked",
                              "reason": "No approved source is past its licence end date." if ok else domain["headline"]})
        if domain["key"] == "escalation_sla":
            ok = domain["state"] != "critical"
            a.release.append({"gate": "Escalation SLA", "state": "passed" if ok else "blocked",
                              "reason": "No escalation is past its SLA." if ok else domain["headline"]})
        if domain["key"] == "jurisdiction_readiness":
            a.release.append({"gate": "Jurisdiction pack", "state": "not_assessed", "reason": domain["reason"]})
    a.release.append({"gate": "Rollback point", "state": "not_assessed",
                      "reason": "Canary and rollback verification are not built yet."})


async def assess(db: AsyncSession, viewer: User, *, now: datetime | None = None) -> Assessment:
    now = now or datetime.now(timezone.utc)
    a = Assessment()
    snap = await _snapshot(db, viewer.tenant_id, now.date(), now)
    await _sources(db, a, snap, viewer.tenant_id, now.date())
    await _risk_policy(db, a)
    await _escalations(db, a, snap, viewer.tenant_id, now)
    a.incident_counts = await _incidents(db, a, snap, viewer.tenant_id)
    ledger_ok = await _ledger(db, a, viewer.tenant_id)
    await _break_glass(db, a, snap, viewer.tenant_id)
    _not_built(a)
    await _work_queue(db, a, snap, viewer)
    await release_readiness(db, a, ledger_ok=ledger_ok)
    a.alerts.sort(key=lambda x: (SEVERITY_ORDER.index(x["severity"]), x["dueAt"] or "9999"))
    return a


def overall_state(domains: list[dict]) -> str:
    assessed = [d["state"] for d in domains if d["state"] != "not_assessed"]
    if not assessed:
        return "not_assessed"
    return min(assessed, key=STATE_ORDER.index)
