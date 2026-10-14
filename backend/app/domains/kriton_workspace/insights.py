"""Reports & Insights: how Kriton is used in a tenant, from records it keeps.

Every figure is an aggregate over the tenant's own records in a time
window; no question text or personal data is returned.

  Questions asked, per day   audit event query_received
  Outcomes and routes        audit event response_finalised (outcome, route)
  Risk levels                audit event risk_classified (risk_level)
  Response time              audit event response_returned (latency_ms)
  Topics                     the recorded questions, classified by
                             source_taxonomy.detect_topics (counts only)
  Source websites            the hosts of the answers' recorded web sources
  Review cases               review_cases (status, source)
  Feedback                   answer_feedback (up / down)
  Workspace output           saved answers, drafts by status, CPD minutes

Each section is read in its own savepoint and grouped in the database, so
only small totals cross the network, and a slow or failed section reports
"unavailable" instead of failing the report.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import User
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.domains.learning_cpd.models import CPDEntry
from app.orchestration.models import AnswerFeedback, QueryAnswerRecord, ReviewCase
from app.orchestration.source_taxonomy import detect_topics

MAX_WINDOW_DAYS = 90
TEXT_SAMPLE = 500  # recent answers read for topics and source websites
TOP_N = 8


async def _section(db: AsyncSession, read):
    """Run one section in a savepoint; None when it fails."""
    try:
        async with db.begin_nested():
            return await read()
    except Exception:  # noqa: BLE001 - one slow section must not fail the report
        return None


def _event_count_by(db_field, tenant_id: str, name: str, since: datetime):
    return (
        select(db_field, func.count())
        .where(AuditEvent.tenant_id == tenant_id, AuditEvent.event_name == name, AuditEvent.ingested_at >= since)
        .group_by(db_field)
    )


async def build_insights(db: AsyncSession, user: User, window_days: int = 30, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    window_days = max(1, min(window_days, MAX_WINDOW_DAYS))
    since = now - timedelta(days=window_days)
    tenant = user.tenant_id

    async def daily():
        day = func.date(AuditEvent.ingested_at)
        rows = (await db.execute(_event_count_by(day, tenant, "query_received", since).order_by(day))).all()
        return [{"date": str(d), "count": c} for d, c in rows]

    async def grouped(event_name: str, key: str):
        field = AuditEvent.payload[key].as_string()
        rows = (await db.execute(_event_count_by(field, tenant, event_name, since))).all()
        return sorted(({"label": label or "unknown", "count": c} for label, c in rows), key=lambda r: -r["count"])

    async def latency():
        value = AuditEvent.payload["latency_ms"].as_float()
        avg, peak, n = (await db.execute(
            select(func.avg(value), func.max(value), func.count())
            .where(AuditEvent.tenant_id == tenant, AuditEvent.event_name == "response_returned",
                   AuditEvent.ingested_at >= since)
        )).one()
        return {"averageMs": round(avg or 0), "maxMs": round(peak or 0), "measured": n}

    async def answer_sample():
        rows = (await db.execute(
            select(QueryAnswerRecord.question, QueryAnswerRecord.external_evidence)
            .where(QueryAnswerRecord.tenant_id == tenant, QueryAnswerRecord.created_at >= since)
            .order_by(QueryAnswerRecord.created_at.desc()).limit(TEXT_SAMPLE)
        )).all()
        topics, hosts = Counter(), Counter()
        for question, evidence in rows:
            topics.update(detect_topics(question or "") or {"other"})
            for host in {(urlsplit((e or {}).get("url") or "").hostname or "") for e in evidence or []}:
                if host:
                    hosts[host[4:] if host.startswith("www.") else host] += 1
        return {
            "answersSampled": len(rows),
            "topics": [{"label": t, "count": c} for t, c in topics.most_common(TOP_N)],
            "sourceSites": [{"label": h, "count": c} for h, c in hosts.most_common(TOP_N)],
        }

    async def reviews():
        rows = (await db.execute(
            select(ReviewCase.status, ReviewCase.source, func.count())
            .where(ReviewCase.tenant_id == tenant, ReviewCase.created_at >= since)
            .group_by(ReviewCase.status, ReviewCase.source)
        )).all()
        by_status, by_source = Counter(), Counter()
        for status, source, c in rows:
            by_status[status] += c
            by_source[source] += c
        return {"byStatus": dict(by_status), "bySource": dict(by_source), "total": sum(by_status.values())}

    async def feedback():
        rows = (await db.execute(
            select(AnswerFeedback.rating, func.count())
            .where(AnswerFeedback.tenant_id == tenant, AnswerFeedback.created_at >= since)
            .group_by(AnswerFeedback.rating)
        )).all()
        return {rating: c for rating, c in rows}

    async def workspace():
        saved = (await db.execute(select(func.count()).select_from(SavedAnswer).where(
            SavedAnswer.tenant_id == tenant, SavedAnswer.created_at >= since))).scalar_one()
        drafts = dict((await db.execute(select(Draft.status, func.count()).where(
            Draft.tenant_id == tenant, Draft.updated_at >= since).group_by(Draft.status))).all())
        cpd = (await db.execute(select(func.coalesce(func.sum(CPDEntry.minutes), 0), func.count()).where(
            CPDEntry.tenant_id == tenant, CPDEntry.logged_at >= since))).one()
        return {"savedAnswers": saved, "draftsByStatus": drafts, "cpdMinutes": int(cpd[0] or 0), "cpdEntries": cpd[1]}

    sections = {
        "questionsPerDay": await _section(db, daily),
        "outcomes": await _section(db, lambda: grouped("response_finalised", "outcome")),
        "routes": await _section(db, lambda: grouped("response_finalised", "route")),
        "riskLevels": await _section(db, lambda: grouped("risk_classified", "risk_level")),
        "latency": await _section(db, latency),
        "answers": await _section(db, answer_sample),
        "reviews": await _section(db, reviews),
        "feedback": await _section(db, feedback),
        "workspace": await _section(db, workspace),
    }
    per_day = sections["questionsPerDay"] or []
    return {
        "windowDays": window_days,
        "since": since.isoformat(),
        "generatedAt": now.isoformat(),
        "totalQuestions": sum(d["count"] for d in per_day) if sections["questionsPerDay"] is not None else None,
        **sections,
        "unavailable": [name for name, value in sections.items() if value is None],
    }
