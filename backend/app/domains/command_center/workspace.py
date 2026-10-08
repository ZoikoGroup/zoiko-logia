"""My Workspace: the signed-in user's own recent activity and pending tasks.

Recent activity is what this user did, from records that name them:
saved answers and drafts they own, review cases they resolved, escalations
they decided, and their own audit-ledger actions (uploads, approvals,
profile changes).

Pending tasks are what is waiting on this user, each shown only to a role
that may act on it:
  open review cases                         (review.resolve)
  pending escalations, with their SLA       (safety.manage)
  their own unfinished drafts
  source versions awaiting approval         (source.manage)
  prompts awaiting approval                 (model.manage)
Maker-checker: a version or prompt the user submitted is not their task,
since they may not approve their own submission.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import User
from app.domains.identity.permissions import MODEL_MANAGE, REVIEW_RESOLVE, SAFETY_MANAGE, SOURCE_MANAGE, user_has_permission
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.domains.model_gateway.models import PromptTemplate
from app.domains.risk_safety.models import EscalationCase, EscalationStatus
from app.domains.source_library.models import Source, SourceVersion
from app.orchestration.models import ReviewCase

ACTIVITY_LIMIT = 15
TASK_LIMIT = 15
_PER_SOURCE = 10

# Ledger events worth showing as the user's own activity, with their label.
_AUDIT_LABELS = {
    "kriton_workspace.attachment_uploaded": "Uploaded a document",
    "kriton_workspace.attachment_deleted": "Deleted a document",
    "prompt_template_approved": "Approved a prompt template",
    "source_version_approved": "Approved a source version",
    "auth.profile_updated": "Updated a user profile",
    "auth.user_created": "Created a user",
    "auth.user_activation_changed": "Changed a user's access",
    "auth.sessions_revoked": "Revoked sessions",
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


def _short(text: str | None, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _value(enum_or_str) -> str:
    return str(getattr(enum_or_str, "value", enum_or_str) or "")


async def _activity(db: AsyncSession, user: User) -> list[dict]:
    items: list[dict] = []
    for a in (await db.execute(
        select(SavedAnswer).where(SavedAnswer.tenant_id == user.tenant_id, SavedAnswer.user_id == user.id)
        .order_by(SavedAnswer.created_at.desc()).limit(_PER_SOURCE)
    )).scalars():
        items.append({"id": f"answer:{a.id}", "kind": "saved_answer", "label": f"Saved an answer: {_short(a.query_text)}",
                      "at": _iso(a.created_at), "href": "/saved-answers"})
    for d in (await db.execute(
        select(Draft).where(Draft.tenant_id == user.tenant_id, Draft.user_id == user.id)
        .order_by(Draft.updated_at.desc()).limit(_PER_SOURCE)
    )).scalars():
        items.append({"id": f"draft:{d.id}", "kind": "draft", "label": f"Edited draft: {_short(d.title)} ({d.status})",
                      "at": _iso(d.updated_at or d.created_at), "href": "/drafts-reports"})
    for case in (await db.execute(
        select(ReviewCase).where(ReviewCase.tenant_id == user.tenant_id, ReviewCase.reviewer_id == user.id,
                                 ReviewCase.resolved_at.is_not(None))
        .order_by(ReviewCase.resolved_at.desc()).limit(_PER_SOURCE)
    )).scalars():
        decision = case.reviewer_decision or "resolved"
        items.append({"id": f"review:{case.id}", "kind": "review", "label": f"Reviewed ({decision}): {_short(case.query_text)}",
                      "at": _iso(case.resolved_at), "href": "/review-tasks"})
    for case in (await db.execute(
        select(EscalationCase).where(EscalationCase.tenant_id == user.tenant_id, EscalationCase.reviewer_id == user.id)
        .order_by(EscalationCase.resolved_at.desc()).limit(_PER_SOURCE)
    )).scalars():
        items.append({"id": f"escalation:{case.id}", "kind": "escalation",
                      "label": f"Decided escalation ({case.reviewer_decision or _value(case.status).lower()}): {_short(case.topic)}",
                      "at": _iso(case.resolved_at or case.created_at), "href": "/escalation-queue"})
    for event in (await db.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == user.tenant_id, AuditEvent.actor_id == user.id,
                                 AuditEvent.event_name.in_(list(_AUDIT_LABELS)))
        .order_by(AuditEvent.ingested_at.desc()).limit(_PER_SOURCE)
    )).scalars():
        items.append({"id": f"audit:{event.id}", "kind": "audit", "label": _AUDIT_LABELS[event.event_name],
                      "at": _iso(event.event_time or event.ingested_at), "href": "/audit-logs"})
    items.sort(key=lambda item: item["at"] or "", reverse=True)
    return items[:ACTIVITY_LIMIT]


async def _tasks(db: AsyncSession, user: User, now: datetime) -> list[dict]:
    tasks: list[dict] = []
    if user_has_permission(user, REVIEW_RESOLVE):
        for case in (await db.execute(
            select(ReviewCase).where(ReviewCase.tenant_id == user.tenant_id, ReviewCase.status.in_(("open", "needs_evidence")))
            .order_by(ReviewCase.created_at).limit(_PER_SOURCE)
        )).scalars():
            tasks.append({"id": f"review:{case.id}", "kind": "review", "label": f"Review answer: {_short(case.query_text)}",
                          "status": "Needs evidence" if case.status == "needs_evidence" else "Open",
                          "tone": "bad" if _value(case.risk_level).upper() in {"HIGH", "RESTRICTED"} else "warn",
                          "dueAt": None, "href": "/review-tasks"})
    if user_has_permission(user, SAFETY_MANAGE):
        for case in (await db.execute(
            select(EscalationCase).where(EscalationCase.tenant_id == user.tenant_id,
                                         EscalationCase.status == EscalationStatus.PENDING)
            .order_by(EscalationCase.sla_deadline).limit(_PER_SOURCE)
        )).scalars():
            due = _aware(case.sla_deadline)
            overdue = bool(due and due < now)
            tasks.append({"id": f"escalation:{case.id}", "kind": "escalation", "label": f"Decide escalation: {_short(case.topic)}",
                          "status": "SLA breached" if overdue else ("Due" if due else "Pending"),
                          "tone": "bad" if overdue else "warn", "dueAt": _iso(due), "href": "/escalation-queue"})
    for d in (await db.execute(
        select(Draft).where(Draft.tenant_id == user.tenant_id, Draft.user_id == user.id, Draft.status != "Final")
        .order_by(Draft.updated_at.desc()).limit(_PER_SOURCE)
    )).scalars():
        tasks.append({"id": f"draft:{d.id}", "kind": "draft", "label": f"Finish draft: {_short(d.title)}",
                      "status": d.status, "tone": "info", "dueAt": None, "href": "/drafts-reports"})
    if user_has_permission(user, SOURCE_MANAGE):
        rows = (await db.execute(
            select(SourceVersion, Source).join(Source, Source.id == SourceVersion.source_id)
            .where(SourceVersion.tenant_id == user.tenant_id, SourceVersion.status == "PROPOSED",
                   SourceVersion.submitted_by != user.id)
            .limit(_PER_SOURCE)
        )).all()
        for version, source in rows:
            tasks.append({"id": f"source:{version.id}", "kind": "source_approval",
                          "label": f"Approve source: {_short(source.title, 60)} {version.version_label}",
                          "status": "Awaiting approval", "tone": "warn", "dueAt": None, "href": "/source-library"})
    if user_has_permission(user, MODEL_MANAGE):
        for prompt in (await db.execute(
            select(PromptTemplate).where(PromptTemplate.status == "PendingReview", PromptTemplate.submitted_by != user.id)
            .limit(_PER_SOURCE)
        )).scalars():
            tasks.append({"id": f"prompt:{prompt.id}", "kind": "prompt_approval",
                          "label": f"Approve prompt: {prompt.name} {prompt.version}",
                          "status": "Awaiting approval", "tone": "warn", "dueAt": None, "href": "/model-prompt-registry"})
    order = {"bad": 0, "warn": 1, "info": 2}
    tasks.sort(key=lambda t: order.get(t["tone"], 9))
    return tasks[:TASK_LIMIT]


async def build_my_workspace(db: AsyncSession, user: User, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "recentActivity": await _activity(db, user),
        "pendingTasks": await _tasks(db, user, now),
        "generatedAt": now.isoformat(),
    }
