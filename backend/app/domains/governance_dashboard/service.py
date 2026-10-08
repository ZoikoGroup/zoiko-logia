"""Governance Dashboard view model, built from records Kriton already holds.

Every exception, decision and domain state is derived from a real record,
and each part is read only for a role that may read that service on its own
endpoint. Two rules keep the view honest:

- No open exception is reported as "no_open_exceptions", never "effective":
  an empty table does not prove a control works.
- A domain the role cannot read is "restricted"; a domain with no
  authoritative service yet (jurisdiction & provider coverage) is
  "not_assessed".

  Domain                          Evidence read
  AI Safety & Risk Controls       open HIGH/RESTRICTED escalations       (safety.read)
  Source & Knowledge Governance   licence expiry, licence states          (source.read)
  Evaluation & Release Readiness  latest evaluation result packs          (evaluation.read)
  Audit & Incident Readiness      open security incidents                 (support.read)
  Professional Boundaries         escalations with a restricted sub-class (safety.read)
  Human Accountability            escalation SLA breaches, review cases   (safety.read / review.read)
  Jurisdiction & Provider Coverage  not assessed yet
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.chain_integrity import verify_event_self_consistency
from app.domains.audit_ledger.models import AuditEvent
from app.domains.evaluation.models import EvaluationRun, PromotionAuthorization, ResultPack
from app.domains.identity.models import User
from app.domains.identity.permissions import (
    EVALUATION_MANAGE, EVALUATION_READ, MODEL_MANAGE, REVIEW_READ, REVIEW_RESOLVE,
    SAFETY_MANAGE, SAFETY_READ, SOURCE_MANAGE, SOURCE_READ, SUPPORT_READ, user_has_permission,
)
from app.domains.model_gateway.models import PromptTemplate
from app.domains.risk_safety.models import EscalationCase, EscalationStatus
from app.domains.source_library.models import Source, SourceVersion
from app.domains.support_incident.models import SecurityIncident
from app.orchestration.models import ReviewCase

AI_SAFETY = "AI Safety & Risk Controls"
SOURCE_GOV = "Source & Knowledge Governance"
EVALUATION = "Evaluation & Release Readiness"
AUDIT_INCIDENT = "Audit & Incident Readiness"
BOUNDARIES = "Professional Boundaries"
ACCOUNTABILITY = "Human Accountability"
JURISDICTION = "Jurisdiction & Provider Coverage"

_DOMAINS = [
    (AI_SAFETY, (SAFETY_READ,), "/ai-safety-dashboard"),
    (SOURCE_GOV, (SOURCE_READ,), "/source-licensing"),
    (EVALUATION, (EVALUATION_READ,), "/evaluation-gates"),
    (AUDIT_INCIDENT, (SUPPORT_READ,), "/incident-response"),
    (BOUNDARIES, (SAFETY_READ,), "/professional-boundaries"),
    (ACCOUNTABILITY, (SAFETY_READ, REVIEW_READ), "/escalation-queue"),
    (JURISDICTION, (), "/jurisdiction-rollout"),
]

LICENCE_WARNING_DAYS = 30
# The dashboard checks the most recent part of the audit chain on every load.
# A full-chain read (GET /audit/chain-verify) is O(all events) and timed out
# against a hosted database at ~126k events, so it stays an on-demand check.
LEDGER_WINDOW = 500
LEDGER_MARGIN = 50
EXCEPTION_LIMIT = 8
DECISION_LIMIT = 6
RELEASE_RUNS = 3

_OPEN_ESCALATION = (EscalationStatus.PENDING, EscalationStatus.UNDER_REVIEW, EscalationStatus.ESCALATED)
_OPEN_INCIDENT = ("OPEN", "CONTAINED")
_OPEN_REVIEW = ("open", "needs_evidence")
_ELIGIBLE_SOURCE = ("ACTIVE", "APPROVED")
_SEVERITY_ORDER = {"Critical": 0, "High": 1}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


def _short(text: str | None, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _risk(value) -> str:
    return str(getattr(value, "value", value) or "").upper()


def _can(user: User, *permissions: str) -> bool:
    return any(user_has_permission(user, p) for p in permissions)


def _exception(eid, severity, domain, title, detail, opened_at, href) -> dict:
    return {"id": eid, "severity": severity, "domain": domain, "title": title,
            "detail": detail, "openedAt": _iso(opened_at), "href": href}


async def _escalation_exceptions(db: AsyncSession, user: User, now: datetime) -> tuple[list[dict], dict]:
    rows = (await db.execute(
        select(EscalationCase).where(
            EscalationCase.tenant_id == user.tenant_id, EscalationCase.status.in_(_OPEN_ESCALATION),
        )
    )).scalars().all()
    found: list[dict] = []
    stats = {"open": len(rows), "overdue": 0, "boundary": 0, "highRisk": 0, "byStatus": {}}
    for case in rows:
        status = str(getattr(case.status, "value", case.status))
        stats["byStatus"][status] = stats["byStatus"].get(status, 0) + 1
        high_risk = _risk(case.risk_level) in {"HIGH", "RESTRICTED"}
        due = _aware(case.sla_deadline)
        topic = _short(case.topic, 60) or "review"
        # One exception per case, the most serious reading first.
        if due and due < now:
            stats["overdue"] += 1
            found.append(_exception(case.id, "Critical" if high_risk else "High", ACCOUNTABILITY,
                                    f"Escalation SLA breached: {topic}",
                                    f"{_risk(case.risk_level)} risk · due {due.date().isoformat()}",
                                    case.created_at, "/escalation-queue"))
        elif case.restricted_sub_class is not None:
            stats["boundary"] += 1
            found.append(_exception(case.id, "High", BOUNDARIES, f"Boundary escalation open: {topic}",
                                    f"Restricted: {_risk(case.restricted_sub_class)}", case.created_at,
                                    "/escalation-queue"))
        elif high_risk:
            stats["highRisk"] += 1
            found.append(_exception(case.id, "High", AI_SAFETY, f"High-risk escalation awaiting review: {topic}",
                                    _short(case.query_text, 90), case.created_at, "/escalation-queue"))
    return found, stats


async def _incident_exceptions(db: AsyncSession, user: User) -> tuple[list[dict], dict]:
    rows = (await db.execute(
        select(SecurityIncident).where(
            SecurityIncident.tenant_id == user.tenant_id,
            SecurityIncident.containment_status.in_(_OPEN_INCIDENT),
        )
    )).scalars().all()
    counts = {s: 0 for s in ["critical", "high", "medium", "low", "informational"]}
    found = []
    for incident in rows:
        severity = (incident.severity or "").lower()
        counts[severity if severity in counts else "informational"] += 1
        if severity in {"critical", "high"}:
            found.append(_exception(incident.id, severity.capitalize(), AUDIT_INCIDENT,
                                    f"Open incident: {_short(incident.title, 70)}",
                                    f"{incident.source} · {incident.containment_status}",
                                    incident.opened_at, "/incident-response"))
    return found, counts


async def _recent_ledger(db: AsyncSession, user: User) -> dict:
    """Verify the tenant's latest LEDGER_WINDOW audit events: each event's own
    chain hash, and that each links to an event that exists. Reads only the
    hash columns. Fails soft: a slow or failed read reports "unavailable".

    Links are matched by hash, not by position: events written in the same
    instant share an ingested_at, so time order alone can put a pair the
    wrong way round and report a break that is not there. LEDGER_MARGIN older
    events are read as well, so the oldest checked events can find theirs."""
    tenant_id = user.tenant_id
    try:
        # A savepoint, so a failed read rolls back only itself: a full
        # rollback would also expire the request's loaded user row.
        async with db.begin_nested():
            rows = (await db.execute(
                select(AuditEvent.id, AuditEvent.event_name, AuditEvent.payload_hash,
                       AuditEvent.previous_chain_hash, AuditEvent.chain_hash)
                .where(AuditEvent.tenant_id == tenant_id)
                .order_by(AuditEvent.ingested_at.desc()).limit(LEDGER_WINDOW + LEDGER_MARGIN)
            )).all()
    except Exception:  # noqa: BLE001 - a ledger read must not take the dashboard down
        return {"state": "unavailable", "eventsChecked": 0, "firstBrokenEventId": None}
    checked = rows[:LEDGER_WINDOW]
    passed, broken = verify_event_self_consistency(checked)
    if passed:
        known = {row.chain_hash for row in rows}
        # Every checked event must link to a read event, or be the start of
        # the chain (no previous hash). The margin keeps the oldest checked
        # events' predecessors inside the read.
        dangling = [e for e in checked if e.previous_chain_hash is not None and e.previous_chain_hash not in known]
        if dangling:
            passed, broken = False, dangling[0].id
    return {"state": "verified" if passed else "broken", "eventsChecked": len(checked), "firstBrokenEventId": broken}


def _visible_sources(tenant_id: str):
    return or_(Source.is_tenant_private.is_(False), Source.tenant_id == tenant_id)


async def _source_exceptions(db: AsyncSession, user: User, today: date) -> tuple[list[dict], dict]:
    rows = (await db.execute(
        select(SourceVersion, Source).join(Source, Source.id == SourceVersion.source_id).where(
            _visible_sources(user.tenant_id),
            SourceVersion.status.in_(_ELIGIBLE_SOURCE),
            SourceVersion.effective_to.is_not(None),
            SourceVersion.effective_to <= today + timedelta(days=LICENCE_WARNING_DAYS),
        ).order_by(SourceVersion.effective_to.asc())
    )).all()
    found = []
    for version, source in rows:
        days = (version.effective_to - today).days
        expired = days < 0
        found.append(_exception(version.id, "Critical" if expired else "High", SOURCE_GOV,
                                f"Source licence {'expired' if expired else 'expiring'}: {_short(source.title, 60)}",
                                f"{-days} days ago" if expired else f"{days} days left",
                                None, "/source-licensing"))
    licence_rows = (await db.execute(
        select(Source.licence_state, func.count()).where(_visible_sources(user.tenant_id)).group_by(Source.licence_state)
    )).all()
    summary = {
        "expiringWithin30Days": sum(1 for v, _ in rows if v.effective_to >= today),
        "expired": sum(1 for v, _ in rows if v.effective_to < today),
        "licenseStates": {state: count for state, count in licence_rows},
    }
    return found, summary


async def _release_readiness(db: AsyncSession) -> tuple[list[dict], list[dict], list[ResultPack]]:
    runs = (await db.execute(
        select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(RELEASE_RUNS)
    )).scalars().all()
    readiness, found, eligible_unapproved = [], [], []
    for run in runs:
        pack = (await db.execute(select(ResultPack).where(ResultPack.run_id == run.id))).scalars().first()
        decision = None
        if pack is not None:
            decision = (await db.execute(
                select(PromotionAuthorization.decision).where(PromotionAuthorization.result_pack_id == pack.id)
                .order_by(PromotionAuthorization.created_at.desc())
            )).scalars().first()
        blocked = run.status == "FAILED" or (pack is not None and (
            not pack.zero_tolerance_passed or pack.contamination_scan_status != "PASSED"))
        readiness.append({
            "runId": run.id, "status": run.status, "createdAt": _iso(run.created_at),
            "promotionEligible": bool(pack and pack.promotion_eligible),
            "zeroTolerancePassed": None if pack is None else bool(pack.zero_tolerance_passed),
            "contaminationScan": None if pack is None else pack.contamination_scan_status,
            "decision": decision, "blocked": blocked,
        })
        if blocked:
            reason = "run failed" if run.status == "FAILED" else (
                "zero-tolerance cases failed" if not pack.zero_tolerance_passed else "contamination scan failed")
            found.append(_exception(run.id, "High", EVALUATION, f"Release gate blocked: {reason}",
                                    f"Evaluation run {run.id}", run.created_at, "/evaluation-gates"))
        elif pack is not None and pack.promotion_eligible and decision is None:
            eligible_unapproved.append(pack)
    return readiness, found, eligible_unapproved


async def _decisions(db: AsyncSession, user: User, eligible_packs: list[ResultPack]) -> tuple[list[dict], int]:
    items: list[dict] = []
    total = 0
    if _can(user, REVIEW_RESOLVE):
        where = (ReviewCase.tenant_id == user.tenant_id, ReviewCase.status.in_(_OPEN_REVIEW))
        total += (await db.execute(select(func.count()).select_from(ReviewCase).where(*where))).scalar_one()
        for case in (await db.execute(select(ReviewCase).where(*where).order_by(ReviewCase.created_at).limit(3))).scalars():
            items.append({"id": case.id, "kind": "ANSWER REVIEW", "severity": _risk(case.risk_level) or "MEDIUM",
                          "title": _short(case.query_text, 90) or "Review case", "createdAt": _iso(case.created_at),
                          "href": "/review-tasks"})
    if _can(user, SAFETY_MANAGE):
        where = (EscalationCase.tenant_id == user.tenant_id, EscalationCase.status == EscalationStatus.PENDING)
        total += (await db.execute(select(func.count()).select_from(EscalationCase).where(*where))).scalar_one()
        for case in (await db.execute(select(EscalationCase).where(*where).order_by(EscalationCase.created_at).limit(3))).scalars():
            items.append({"id": case.id, "kind": "ESCALATION", "severity": _risk(case.risk_level),
                          "title": _short(case.topic, 90), "createdAt": _iso(case.created_at), "href": "/escalation-queue"})
    if _can(user, SOURCE_MANAGE):
        where = (SourceVersion.tenant_id == user.tenant_id, SourceVersion.status == "PROPOSED")
        total += (await db.execute(select(func.count()).select_from(SourceVersion).where(*where))).scalar_one()
        rows = (await db.execute(
            select(SourceVersion, Source).join(Source, Source.id == SourceVersion.source_id).where(*where).limit(3)
        )).all()
        for version, source in rows:
            items.append({"id": version.id, "kind": "SOURCE APPROVAL", "severity": "MEDIUM",
                          "title": f"Approve {_short(source.title, 60)} {version.version_label}", "createdAt": None,
                          "href": "/source-library"})
    if _can(user, MODEL_MANAGE):
        where = (PromptTemplate.status == "PendingReview",)
        total += (await db.execute(select(func.count()).select_from(PromptTemplate).where(*where))).scalar_one()
        for prompt in (await db.execute(select(PromptTemplate).where(*where).limit(3))).scalars():
            items.append({"id": prompt.id, "kind": "PROMPT APPROVAL", "severity": "MEDIUM",
                          "title": f"Approve prompt {prompt.name} {prompt.version}", "createdAt": None,
                          "href": "/model-prompt-registry"})
    if _can(user, EVALUATION_MANAGE):
        total += len(eligible_packs)
        for pack in eligible_packs[:3]:
            items.append({"id": pack.id, "kind": "RELEASE", "severity": "HIGH",
                          "title": f"Release sign-off for evaluation run {pack.run_id}", "createdAt": _iso(pack.created_at),
                          "href": "/release-gates"})
    return items[:DECISION_LIMIT], total


async def build_governance_dashboard(db: AsyncSession, user: User, now: datetime | None = None) -> dict:
    """Exceptions, decisions, domain states and summaries for the dashboard."""
    now = now or datetime.now(timezone.utc)
    exceptions: list[dict] = []
    escalation_stats = {"open": 0, "overdue": 0, "boundary": 0, "highRisk": 0, "byStatus": {}}
    incident_counts = {s: 0 for s in ["critical", "high", "medium", "low", "informational"]}
    source_summary = {"expiringWithin30Days": 0, "expired": 0, "licenseStates": {}}
    readiness: list[dict] = []
    eligible_packs: list[ResultPack] = []
    open_reviews = 0

    if _can(user, SAFETY_READ):
        found, escalation_stats = await _escalation_exceptions(db, user, now)
        exceptions += found
    if _can(user, SUPPORT_READ):
        found, incident_counts = await _incident_exceptions(db, user)
        exceptions += found
    if _can(user, SOURCE_READ):
        found, source_summary = await _source_exceptions(db, user, now.date())
        exceptions += found
    if _can(user, EVALUATION_READ):
        readiness, found, eligible_packs = await _release_readiness(db)
        exceptions += found
    if _can(user, REVIEW_READ):
        open_reviews = (await db.execute(
            select(func.count()).select_from(ReviewCase)
            .where(ReviewCase.tenant_id == user.tenant_id, ReviewCase.status.in_(_OPEN_REVIEW))
        )).scalar_one()

    ledger = {**await _recent_ledger(db, user), "window": LEDGER_WINDOW, "verifiedAt": now.isoformat()}
    if ledger["state"] == "broken":
        exceptions.append(_exception(ledger["firstBrokenEventId"] or "audit-chain", "Critical", AUDIT_INCIDENT,
                                     "Audit ledger chain verification failed",
                                     f"First broken event: {ledger['firstBrokenEventId']}", None, "/audit-logs"))

    exceptions.sort(key=lambda e: (_SEVERITY_ORDER.get(e["severity"], 9), e["openedAt"] or ""))
    decisions, decision_total = await _decisions(db, user, eligible_packs)

    domain_states = []
    for name, permissions, href in _DOMAINS:
        if not permissions:
            state = "not_assessed"
        elif not _can(user, *permissions):
            state = "restricted"
        else:
            state = "attention_required" if any(e["domain"] == name for e in exceptions) else "no_open_exceptions"
        domain_states.append({
            "name": name, "state": state, "href": href,
            "openExceptions": sum(1 for e in exceptions if e["domain"] == name),
        })

    critical = sum(1 for e in exceptions if e["severity"] == "Critical")
    high = sum(1 for e in exceptions if e["severity"] == "High")
    partial = [d["name"] for d in domain_states if d["state"] in {"restricted", "not_assessed"}]
    current = {"state": "CURRENT", "evaluatedAt": now.isoformat()}
    return {
        "governanceSummary": {
            "overallState": "attention_required" if exceptions else "no_open_exceptions",
            "criticalExceptionCount": critical, "highExceptionCount": high,
            "pendingDecisionCount": decision_total,
            "blockedGateCount": sum(1 for r in readiness if r["blocked"]),
            "partialDataDomains": partial, "lastEvaluatedAt": now.isoformat(), "freshnessState": "CURRENT",
        },
        "domainStates": domain_states,
        "exceptions": exceptions[:EXCEPTION_LIMIT],
        "decisions": decisions,
        "releaseReadiness": readiness,
        "accountability": {
            "mandatoryReviews": open_reviews, "overdueEscalations": escalation_stats["overdue"],
            "boundaryEscalations": escalation_stats["boundary"], "openEscalations": escalation_stats["open"],
        },
        "sourceGovernance": source_summary,
        "incidents": {"openIncidentCounts": incident_counts, "escalationCounts": escalation_stats["byStatus"]},
        "ledger": ledger,
        "moduleFreshness": {
            "exceptions": dict(current), "decisions": dict(current), "domainStates": dict(current),
            "releaseReadiness": dict(current) if _can(user, EVALUATION_READ) else {"state": "RESTRICTED"},
        },
    }
