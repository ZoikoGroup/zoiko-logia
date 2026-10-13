"""Personal home view: the Command Center and My Workspace pages.

Everything here is the signed-in user's real data, scoped to their tenant:
  * attention items, deadlines and review queue reuse the Governance
    Dashboard assessment, so the same live conditions and role filtering
    apply (Learners have no governance view and get none of it);
  * active matters are the engagements the user is an active member of;
  * recent work is their own Kriton questions, saved answers and drafts;
  * their break-glass grants, so elevated access is never forgotten.

Empty collections stay empty — no sample matters, names or deadlines.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.governance_dashboard.assessment import assess, overall_state
from app.domains.identity.models import BreakGlassGrant, Engagement, EngagementMembership, Tenant, User
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.orchestration.models import QueryAnswerRecord

RECENT_PER_KIND = 8
DEADLINE_HORIZON = timedelta(days=30)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


def _snippet(text: str, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def _recent_work(db: AsyncSession, user: User) -> tuple[list[dict], dict[str, int]]:
    scope = dict(tenant_id=user.tenant_id, user_id=user.id)
    questions = (await db.execute(
        select(QueryAnswerRecord).filter_by(**scope).order_by(QueryAnswerRecord.created_at.desc()).limit(RECENT_PER_KIND)
    )).scalars().all()
    saved = (await db.execute(
        select(SavedAnswer).filter_by(**scope).order_by(SavedAnswer.created_at.desc()).limit(RECENT_PER_KIND)
    )).scalars().all()
    drafts = (await db.execute(
        select(Draft).filter_by(**scope).order_by(Draft.updated_at.desc()).limit(RECENT_PER_KIND)
    )).scalars().all()

    items = (
        [{"id": f"question:{q.query_id}", "kind": "Kriton question", "title": _snippet(q.question),
          "at": _iso(q.created_at), "href": "/ask-kriton"} for q in questions]
        + [{"id": f"saved:{s.id}", "kind": "Saved answer", "title": _snippet(s.query_text),
            "at": _iso(s.created_at), "href": "/saved-answers"} for s in saved]
        + [{"id": f"draft:{d.id}", "kind": f"Draft · {d.status}", "title": _snippet(d.title),
            "at": _iso(d.updated_at), "href": "/drafts-reports"} for d in drafts]
    )
    items.sort(key=lambda item: item["at"] or "", reverse=True)

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    counts = {
        "questionsLast7Days": (await db.execute(
            select(func.count()).select_from(QueryAnswerRecord).filter_by(**scope)
            .where(QueryAnswerRecord.created_at >= week_ago)
        )).scalar_one(),
        "savedAnswers": (await db.execute(select(func.count()).select_from(SavedAnswer).filter_by(**scope))).scalar_one(),
        "drafts": (await db.execute(select(func.count()).select_from(Draft).filter_by(**scope))).scalar_one(),
    }
    return items, counts


async def _matters(db: AsyncSession, user: User) -> list[dict]:
    rows = (await db.execute(
        select(Engagement, EngagementMembership.engagement_role)
        .join(EngagementMembership, EngagementMembership.engagement_id == Engagement.id)
        .where(
            Engagement.tenant_id == user.tenant_id,
            EngagementMembership.user_id == user.id,
            EngagementMembership.status == "active",
            EngagementMembership.revoked_at.is_(None),
        )
        .order_by(Engagement.created_at.desc())
    )).all()
    return [{"id": e.id, "name": e.name, "status": e.status, "myRole": role, "createdAt": _iso(e.created_at)}
            for e, role in rows]


async def _my_break_glass(db: AsyncSession, user: User) -> list[dict]:
    grants = (await db.execute(
        select(BreakGlassGrant)
        .where(BreakGlassGrant.tenant_id == user.tenant_id, BreakGlassGrant.user_id == user.id,
               BreakGlassGrant.status.in_(("requested", "active")))
        .order_by(BreakGlassGrant.requested_at.desc())
    )).scalars().all()
    now = datetime.now(timezone.utc)
    return [{"id": g.id, "status": "expired" if g.status == "active" and _aware(g.expires_at) <= now else g.status,
             "permissions": list(g.permissions), "expiresAt": _iso(g.expires_at)} for g in grants]


async def build_home(db: AsyncSession, user: User) -> dict:
    now = datetime.now(timezone.utc)
    tenant_name = (await db.execute(select(Tenant.name).where(Tenant.id == user.tenant_id))).scalar_one_or_none()
    recent, counts = await _recent_work(db, user)
    matters = await _matters(db, user)
    grants = await _my_break_glass(db, user)

    governance = user.role != "Learner"
    attention, queue, deadlines, assurance = [], [], [], None
    if governance:
        assessment = await assess(db, user, now=now)
        attention = [a for a in assessment.alerts if a["severity"] in ("critical", "high")]
        queue = assessment.queue
        horizon = (now + DEADLINE_HORIZON).isoformat()
        deadlines = sorted(
            ({"id": a["id"], "title": a["title"], "dueAt": a["dueAt"], "overdue": a["dueAt"] < now.isoformat(),
              "href": a["drilldownTarget"]} for a in assessment.alerts if a["dueAt"] and a["dueAt"] <= horizon),
            key=lambda d: d["dueAt"],
        )
        assurance = {"overallState": overall_state(assessment.domains),
                     "blockedGates": sum(1 for g in assessment.release if g["state"] == "blocked")}
    for grant in grants:
        if grant["status"] == "active" and grant["expiresAt"]:
            deadlines.append({"id": f"break-glass:{grant['id']}", "title": "Your emergency access ends",
                              "dueAt": grant["expiresAt"], "overdue": False, "href": "/break-glass"})
    deadlines.sort(key=lambda d: d["dueAt"])

    return {
        "user": {"firstName": user.first_name or (user.full_name or "").split(" ")[0], "fullName": user.full_name,
                 "email": user.email, "role": user.role},
        "workspace": {"name": tenant_name or "Your workspace", "tenantId": user.tenant_id},
        "generatedAt": now.isoformat(),
        "counts": {**counts, "attention": len(attention), "reviews": len(queue), "deadlines": len(deadlines),
                   "activeMatters": len(matters)},
        "attentionItems": attention,
        "reviewQueue": queue,
        "deadlines": deadlines,
        "activeMatters": matters,
        "recentWork": recent,
        "breakGlass": grants,
        "assurance": assurance,
    }
