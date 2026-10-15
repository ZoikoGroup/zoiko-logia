"""Audit Logs and Audit Replay: the tenant's hash-chained audit ledger.

Audit Logs is the event register (search, families, risk, outcome, chain
integrity, controlled exports); Audit Replay lists recorded traces (one per
correlation, e.g. one Ask Kriton question) and reconstructs one from its
frozen events without re-running anything. Both read the same ledger.

Risk and outcome are derived from the event name by fixed rules
(classify()), not stored. Exports leave the platform only after a different
Admin approves the request, and an approved export expires.
"""
from __future__ import annotations

import csv
import io
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger import service as audit_service
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import User
from app.domains.review_console.models import AuditExportRequest
from app.domains.support_incident.models import SecurityIncident
from app.orchestration.models import QueryAnswerRecord, ReviewCase

FAMILIES = {"ai": "AI & policy", "access": "Access denials", "privileged": "Privileged / admin",
            "source": "Source changes", "user": "User activity"}
EXPORT_TTL = timedelta(days=7)
EXPORT_MAX_ROWS = 10_000
CHAIN_CACHE_SECONDS = 300

_AI_PREFIXES = ("query_", "request_validated", "pre_safety", "response_", "risk_", "route_", "retrieval", "bundle_",
                "composition", "redaction", "validation", "model_", "agent_", "plan_", "coverage", "rerank", "context_",
                "citation", "clarification", "refusal", "human_review", "answer_", "workflow_", "live_", "calculation",
                "tax_", "domain_", "evidence_", "visualization", "release_check", "task_context", "document_retrieval",
                "external_reference", "licence_prefilter", "safety_", "evaluation_")
_PRIVILEGED_PREFIXES = ("break_glass", "admin_", "service_account", "tenant_setting_change", "access_review", "team_",
                        "provider_", "integration_", "release_candidate", "release_gate", "release_approve",
                        "release_deploy", "release_rollback", "service_owner", "compensating", "auth.user_activation",
                        "escalation_", "security_incident_", "operations_alert_")
_DENIED = ("access_denied", "_prohibited", "maker_checker", "self_approval")


def classify(name: str) -> tuple[str, str, str]:
    """(family, risk, outcome) for an event name."""
    n = name.lower()
    if n == "access_denied" or any(k in n for k in _DENIED[1:]):
        family = "access"
    elif n.startswith(_PRIVILEGED_PREFIXES) or n == "admin_permission_changed":
        family = "privileged"
    elif n.startswith(("source_", "licence_")) and not n.startswith("licence_prefilter") or "ingest" in n:
        family = "source"
    elif n.startswith(_AI_PREFIXES):
        family = "ai"
    else:
        family = "user"

    if any(k in n for k in _DENIED) or n.endswith("_rejected"):
        outcome = "denied"
    elif n in {"refusal_returned", "composition_rejected"} or "blocked" in n:
        outcome = "blocked"
    elif n.endswith(("_failed", "_degraded")):
        outcome = "failed"
    elif n.endswith(("_requested", "human_review_created")):
        outcome = "pending"
    else:
        outcome = "recorded"

    if n in {"break_glass_access_granted", "security_incident_recorded", "security_incident_opened"} or "compensat" in n:
        risk = "critical"
    elif family in {"access", "privileged"} and (outcome == "denied" or n.startswith(("break_glass", "admin_", "tenant_setting_change_applied", "release_deploy", "release_rollback"))):
        risk = "high"
    elif family in {"privileged", "source", "access"} or outcome in {"blocked", "failed", "pending"}:
        risk = "medium"
    else:
        risk = "low"
    return family, risk, outcome


def _aware(v: datetime | None) -> datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=timezone.utc))


def _iso(v: datetime | None) -> str | None:
    v = _aware(v)
    return v.isoformat() if v else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _names(db: AsyncSession, tenant_id: str) -> dict[str, str]:
    return {u.id: u.full_name or u.email for u in (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars()}


async def _event_names(db: AsyncSession, tenant_id: str) -> list[str]:
    return list((await db.execute(select(distinct(AuditEvent.event_name)).where(AuditEvent.tenant_id == tenant_id))).scalars())


_CHAIN: dict[str, tuple[float, dict]] = {}


async def chain_status(db: AsyncSession, tenant_id: str, fresh: bool = False) -> dict:
    """Full hash-chain verification is a read of every event, so it is
    cached for a few minutes per tenant."""
    hit = _CHAIN.get(tenant_id)
    if hit and not fresh and time.monotonic() - hit[0] < CHAIN_CACHE_SECONDS:
        return hit[1]
    result = await audit_service.verify_tenant_chain(db, tenant_id)
    result = {**result, "verifiedAt": _now().isoformat()}
    _CHAIN[tenant_id] = (time.monotonic(), result)
    return result


def _event_view(e: AuditEvent, names: dict[str, str]) -> dict:
    family, risk, outcome = classify(e.event_name)
    return {
        "id": e.id, "event": e.event_name, "family": family, "familyLabel": FAMILIES[family], "risk": risk,
        "outcome": outcome, "at": _iso(e.event_time), "ingestedAt": _iso(e.ingested_at),
        "actorId": e.actor_id, "actor": names.get(e.actor_id or "", e.actor_id or e.actor_type or "system"),
        "actorType": e.actor_type, "service": e.emitting_service, "subjectType": e.subject_type, "subjectId": e.subject_id,
        "correlationId": e.correlation_id, "chainHashed": bool(e.chain_hash), "classification": e.classification,
        "payload": e.payload or {},
    }


async def events(db: AsyncSession, tenant_id: str, *, family: str = "", risk: str = "", outcome: str = "",
                 q: str = "", days: int = 30, limit: int = 100, offset: int = 0) -> dict:
    now = _now()
    since = now - timedelta(days=days)
    names_all = await _event_names(db, tenant_id)
    wanted = [n for n in names_all if (not family or classify(n)[0] == family)
              and (not risk or classify(n)[1] == risk) and (not outcome or classify(n)[2] == outcome)]
    base = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id, AuditEvent.ingested_at >= since)
    if family or risk or outcome:
        base = base.where(AuditEvent.event_name.in_(wanted or [""]))
    if q.strip():
        like = f"%{q.strip()}%"
        base = base.where(AuditEvent.id.ilike(like) | AuditEvent.event_name.ilike(like) | AuditEvent.subject_id.ilike(like)
                          | AuditEvent.correlation_id.ilike(like) | AuditEvent.actor_id.ilike(like))
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.order_by(AuditEvent.ingested_at.desc()).limit(min(limit, 200)).offset(offset))).scalars().all()
    names = await _names(db, tenant_id)
    return {"events": [_event_view(e, names) for e in rows], "total": total, "offset": offset,
            "families": FAMILIES, "windowDays": days, "generatedAt": now.isoformat()}


async def overview(db: AsyncSession, tenant_id: str, *, fresh: bool = False) -> dict:
    now = _now()
    month = now - timedelta(days=30)
    total = (await db.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant_id))).scalar_one()
    by_name = (await db.execute(select(AuditEvent.event_name, func.count()).where(
        AuditEvent.tenant_id == tenant_id, AuditEvent.ingested_at >= month).group_by(AuditEvent.event_name))).all()
    fam, outcomes, risks = Counter(), Counter(), Counter()
    for name, count in by_name:
        f, r, o = classify(name)
        fam[f] += count
        outcomes[o] += count
        if o == "denied":
            risks[r] += count
    month_total = sum(fam.values())
    recent = (await db.execute(select(AuditEvent.event_time, AuditEvent.ingested_at).where(
        AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.ingested_at.desc()).limit(500))).all()
    lags = sorted(max(0.0, (_aware(i) - _aware(e)).total_seconds()) for e, i in recent if e and i)
    p95_lag = lags[min(len(lags) - 1, int(0.95 * (len(lags) - 1)))] if lags else None
    open_incidents = (await db.execute(select(SecurityIncident).where(
        SecurityIncident.tenant_id == tenant_id, SecurityIncident.containment_status != "RESOLVED"))).scalars().all()
    exports = (await db.execute(select(AuditExportRequest).where(AuditExportRequest.tenant_id == tenant_id)
                                .order_by(AuditExportRequest.requested_at.desc()))).scalars().all()
    names = await _names(db, tenant_id)
    critical_recent = (await db.execute(select(AuditEvent).where(
        AuditEvent.tenant_id == tenant_id, AuditEvent.ingested_at >= now - timedelta(days=7),
        AuditEvent.event_name.in_([n for n, _ in by_name if classify(n)[1] == "critical" or classify(n)[2] == "denied"] or [""]))
        .order_by(AuditEvent.ingested_at.desc()).limit(5))).scalars().all()
    chain = await chain_status(db, tenant_id, fresh)
    return {
        "summary": {
            "total": total, "last30d": month_total, "denied30d": outcomes["denied"],
            "deniedHighRisk30d": risks["high"] + risks["critical"],
            "openInvestigations": len(open_incidents),
            "investigationsWithEvidence": sum(bool(i.linked_event_ids) for i in open_incidents),
            "chainPassed": chain["passed"], "eventsChecked": chain["events_checked"],
            "brokenAt": chain["first_broken_event_id"], "chainVerifiedAt": chain["verifiedAt"],
            "exportsPending": sum(x.status == "pending" for x in exports),
            "ingestionLagP95Seconds": round(p95_lag, 1) if p95_lag is not None else None,
        },
        "families": [{"key": k, "label": FAMILIES[k], "count": fam.get(k, 0),
                      "pct": round(100 * fam.get(k, 0) / month_total) if month_total else 0} for k in FAMILIES],
        "priority": [_event_view(e, names) for e in critical_recent],
        "exports": [export_view(x, names) for x in exports[:20]],
        "generatedAt": now.isoformat(),
    }


# ── Audit Replay: traces ───────────────────────────────────────────────────

_TERMINAL = {"response_returned", "response_finalised", "answer_receipt", "workflow_completed"}


async def traces(db: AsyncSession, tenant_id: str, *, limit: int = 60) -> dict:
    now = _now()
    rows = (await db.execute(select(AuditEvent.correlation_id, AuditEvent.event_name, AuditEvent.event_time,
                                    AuditEvent.ingested_at, AuditEvent.chain_hash)
                             .where(AuditEvent.tenant_id == tenant_id, AuditEvent.correlation_id.is_not(None))
                             .order_by(AuditEvent.ingested_at.desc()).limit(4000))).all()
    grouped: dict[str, list] = defaultdict(list)
    order: list[str] = []
    for r in rows:
        if r.correlation_id not in grouped:
            order.append(r.correlation_id)
        grouped[r.correlation_id].append(r)
    ids = order[:limit]
    questions = {q.query_id: q.question for q in (await db.execute(select(QueryAnswerRecord).where(
        QueryAnswerRecord.tenant_id == tenant_id, QueryAnswerRecord.query_id.in_(ids or [""])))).scalars()}
    reviews = {r.query_id: r for r in (await db.execute(select(ReviewCase).where(
        ReviewCase.tenant_id == tenant_id, ReviewCase.query_id.in_(ids or [""])))).scalars()}
    incidents = {i.query_id: i for i in (await db.execute(select(SecurityIncident).where(
        SecurityIncident.tenant_id == tenant_id, SecurityIncident.query_id.in_(ids or [""])))).scalars()}
    out = []
    for cid in ids:
        evs = grouped[cid]
        names = {e.event_name for e in evs}
        review, incident = reviews.get(cid), incidents.get(cid)
        unhashed = sum(1 for e in evs if not e.chain_hash)
        if "query_received" in names or "request_validated" in names:
            kind = "Kriton answer"
        elif any(n.startswith("source_") for n in names):
            kind = "Source"
        elif any(n.startswith(("escalation_", "security_incident", "support_ticket")) for n in names):
            kind = "Case"
        else:
            kind = "Governance"
        # Only an answer has a terminal event (response returned); other
        # traces are complete as recorded.
        complete = bool(names & _TERMINAL) if kind == "Kriton answer" else True
        if incident is not None and incident.containment_status != "RESOLVED":
            state = "restricted"
        elif review is not None and review.status in ("open", "triaged", "needs_evidence"):
            state = "review_open"
        elif "refusal_returned" in names:
            state = "refused"
        else:
            state = "verified" if complete and not unhashed else "partial"
        out.append({
            "correlationId": cid, "title": questions.get(cid) or (review.query_text if review else None) or cid,
            "kind": kind, "events": len(evs), "firstAt": _iso(min(e.event_time or e.ingested_at for e in evs)),
            "lastAt": _iso(max(e.ingested_at for e in evs)), "integrity": "verified" if not unhashed else "exception",
            "complete": complete, "state": state, "reviewCase": review.id if review else None,
            "reviewStatus": review.status if review else None, "incident": incident.id if incident else None,
            "refused": "refusal_returned" in names, "humanReview": "human_review_created" in names,
        })
    month = now - timedelta(days=30)
    recorded = (await db.execute(select(func.count(distinct(AuditEvent.correlation_id))).where(
        AuditEvent.tenant_id == tenant_id, AuditEvent.ingested_at >= month))).scalar_one()
    open_reviews = (await db.execute(select(func.count()).select_from(ReviewCase).where(
        ReviewCase.tenant_id == tenant_id, ReviewCase.status.in_(("open", "triaged", "needs_evidence"))))).scalar_one()
    pending_exports = (await db.execute(select(func.count()).select_from(AuditExportRequest).where(
        AuditExportRequest.tenant_id == tenant_id, AuditExportRequest.status == "pending"))).scalar_one()
    return {
        "traces": out,
        "summary": {"recorded30d": recorded, "shown": len(out),
                    "replayReady": sum(t["state"] == "verified" for t in out),
                    "holds": sum(t["state"] in {"restricted", "partial"} or t["integrity"] == "exception" for t in out),
                    "humanReviewsOpen": open_reviews, "exportHolds": pending_exports},
        "integrity": {
            "hashed": sum(t["integrity"] == "verified" for t in out),
            "complete": sum(t["complete"] for t in out),
            "reviewed": sum(bool(t["reviewCase"]) and t["reviewStatus"] not in ("open", "triaged", "needs_evidence") for t in out),
            "total": len(out),
        },
        "generatedAt": now.isoformat(),
    }


# ── Controlled exports ─────────────────────────────────────────────────────

def export_view(x: AuditExportRequest, names: dict[str, str]) -> dict:
    expires = _aware(x.expires_at)
    return {"id": x.id, "ref": x.ref, "purpose": x.purpose, "filters": x.filters, "status": x.status,
            "requestedBy": names.get(x.requested_by, ""), "requestedById": x.requested_by,
            "requestedAt": _iso(x.requested_at), "decidedBy": names.get(x.decided_by or "", None),
            "decidedAt": _iso(x.decided_at), "decisionNote": x.decision_note, "expiresAt": _iso(expires),
            "downloadable": x.status == "approved" and bool(expires and expires > _now()), "downloads": x.downloads}


class ExportError(ValueError):
    """An export the rules refuse."""


async def request_export(db: AsyncSession, actor: User, purpose: str, filters: dict) -> AuditExportRequest:
    if len(purpose.strip()) < 10:
        raise ExportError("State the purpose of the export (at least a sentence)")
    clean = {k: str(v) for k, v in (filters or {}).items() if k in {"family", "risk", "outcome", "q", "days"} and v}
    count = (await db.execute(select(func.count()).select_from(AuditExportRequest)
                              .where(AuditExportRequest.tenant_id == actor.tenant_id))).scalar_one()
    x = AuditExportRequest(tenant_id=actor.tenant_id, ref=f"EXP-{count + 1:03d}", purpose=purpose.strip(), filters=clean,
                           status="pending", requested_by=actor.id, decision_note="", downloads=0)
    db.add(x)
    await db.flush()
    await record_event_async(db, tenant_id=actor.tenant_id, event_name="audit_export_requested", emitting_service="review_console",
                             actor_id=actor.id, subject_type="audit_export", subject_id=x.id, payload={"ref": x.ref, "filters": clean})
    return x


async def decide_export(db: AsyncSession, actor: User, export_id: str, approve: bool, note: str) -> AuditExportRequest:
    x = (await db.execute(select(AuditExportRequest).where(
        AuditExportRequest.id == export_id, AuditExportRequest.tenant_id == actor.tenant_id))).scalar_one_or_none()
    if x is None:
        raise LookupError("Export request not found")
    if x.status != "pending":
        raise ExportError("This request has already been decided")
    if x.requested_by == actor.id:
        raise ExportError("A different Admin must decide your export request")
    if not approve and not note.strip():
        raise ExportError("Record why the export is refused")
    x.status = "approved" if approve else "rejected"
    x.decided_by, x.decided_at, x.decision_note = actor.id, _now(), note.strip()
    x.expires_at = _now() + EXPORT_TTL if approve else None
    await db.flush()
    await record_event_async(db, tenant_id=actor.tenant_id, event_name=f"audit_export_{x.status}", emitting_service="review_console",
                             actor_id=actor.id, subject_type="audit_export", subject_id=x.id, payload={"ref": x.ref})
    return x


async def export_csv(db: AsyncSession, actor: User, export_id: str) -> tuple[str, str]:
    x = (await db.execute(select(AuditExportRequest).where(
        AuditExportRequest.id == export_id, AuditExportRequest.tenant_id == actor.tenant_id))).scalar_one_or_none()
    if x is None:
        raise LookupError("Export request not found")
    if x.status != "approved" or not x.expires_at or _aware(x.expires_at) <= _now():
        raise ExportError("This export is not approved or has expired")
    f = x.filters
    data = await events(db, actor.tenant_id, family=f.get("family", ""), risk=f.get("risk", ""), outcome=f.get("outcome", ""),
                        q=f.get("q", ""), days=int(f.get("days", 30)), limit=200)
    rows = data["events"]
    offset = len(rows)
    while offset < min(data["total"], EXPORT_MAX_ROWS):
        more = await events(db, actor.tenant_id, family=f.get("family", ""), risk=f.get("risk", ""),
                            outcome=f.get("outcome", ""), q=f.get("q", ""), days=int(f.get("days", 30)), limit=200, offset=offset)
        if not more["events"]:
            break
        rows += more["events"]
        offset += len(more["events"])
    buf = io.StringIO()
    w = csv.writer(buf)
    # Event metadata only: payloads can hold customer content and are not exported.
    w.writerow(["event_id", "event_time_utc", "event", "family", "risk", "outcome", "actor", "service",
                "subject_type", "subject_id", "correlation_id", "chain_hashed"])
    for e in rows[:EXPORT_MAX_ROWS]:
        w.writerow([e["id"], e["at"], e["event"], e["familyLabel"], e["risk"], e["outcome"], e["actor"], e["service"],
                    e["subjectType"], e["subjectId"], e["correlationId"], e["chainHashed"]])
    x.downloads += 1
    await db.flush()
    await record_event_async(db, tenant_id=actor.tenant_id, event_name="audit_export_downloaded", emitting_service="review_console",
                             actor_id=actor.id, subject_type="audit_export", subject_id=x.id,
                             payload={"ref": x.ref, "rows": min(len(rows), EXPORT_MAX_ROWS)})
    return f"audit-export-{x.ref}.csv", buf.getvalue()
