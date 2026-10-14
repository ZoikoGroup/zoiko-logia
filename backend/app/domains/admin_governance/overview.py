"""Administration views built from the tenant's real records and the running
configuration: the role/permission matrix, workspace settings and usage.

No sample values. Settings that come from the deployment (backend/.env) are
shown read-only with that origin; billing is reported as not connected because
no billing system exists yet.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.identity.models import ServiceAccount, Tenant, User
from app.domains.identity.permissions import ROLE_PERMISSIONS
from app.domains.kriton_workspace.models import Document, Draft, GeneratedArtifact, SavedAnswer
from app.orchestration.models import QueryAnswerRecord

# What each role is for — product definitions from the Admin Governance
# Console spec (§3), kept beside the permission registry they describe.
ROLE_PURPOSE = {
    "Admin": "Tenant administrator: everything, including users, roles and access governance.",
    "Governance Ops Lead": "Console-wide operational oversight; full read/write across governance modules.",
    "Source Admin": "Ingests and approves sources, metadata and licence rights.",
    "Syllabus Admin": "Professional-body and syllabus mapping (no gated endpoints yet).",
    "Jurisdiction Lead": "Jurisdiction rollout readiness; reads the source library.",
    "Risk Admin": "Risk policy, evaluation gates, model and prompt registry, escalations.",
    "SME Reviewer": "Works the answer review queue: approves, corrects or rejects Kriton answers.",
    "System Auditor": "Read-only access to sources, support, safety, reviews and evaluations.",
    "Learner": "Learns and practises with Kriton; no governance permissions.",
}


async def _people(db: AsyncSession, tenant_id: str) -> list[User]:
    service_ids = select(ServiceAccount.id).where(ServiceAccount.tenant_id == tenant_id)
    return list((await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.id.not_in(service_ids))
    )).scalars().all())


async def roles_matrix(db: AsyncSession, tenant_id: str) -> dict:
    people = await _people(db, tenant_id)
    holders = Counter(u.role for u in people if u.is_active)
    roles = [
        {"name": name, "purpose": ROLE_PURPOSE.get(name, ""), "permissions": sorted(perms),
         "activeUsers": holders.get(name, 0)}
        for name, perms in ROLE_PERMISSIONS.items()
    ]
    # Users holding a role the registry doesn't know have no permissions at
    # all (e.g. an old demo persona); surface them so an Admin can fix it.
    unknown = sorted({u.role for u in people if u.role not in ROLE_PERMISSIONS})
    return {"roles": roles, "unrecognisedRoles": [{"name": r, "activeUsers": holders.get(r, 0)} for r in unknown]}


async def tenant_settings(db: AsyncSession, tenant_id: str) -> dict:
    s = get_settings()
    tenant = await db.get(Tenant, tenant_id)
    people = await _people(db, tenant_id)
    service_accounts = (await db.execute(
        select(func.count()).select_from(ServiceAccount).where(ServiceAccount.tenant_id == tenant_id)
    )).scalar_one()

    def setting(label: str, value, note: str = "") -> dict:
        return {"label": label, "value": value, "note": note, "source": "Deployment setting (backend/.env)"}

    return {
        "workspace": {"name": tenant.name if tenant else "", "id": tenant_id},
        "people": {
            "total": len(people), "active": sum(u.is_active for u in people),
            "inactive": sum(not u.is_active for u in people), "serviceAccounts": service_accounts,
            "byRole": dict(Counter(u.role for u in people if u.is_active).most_common()),
        },
        "security": [
            setting("MFA required for privileged actions", s.MFA_REQUIRED_FOR_PRIVILEGED,
                    "When on, admin and *.manage actions need a session verified with an authenticator code."),
            setting("Public sign-up", s.ALLOW_PUBLIC_SIGNUP,
                    "When off, only users an Admin creates or invites can sign in."),
            setting("Impersonation limit (minutes)", s.IMPERSONATION_MAX_MINUTES),
            setting("Break-glass limit (minutes)", s.BREAK_GLASS_MAX_MINUTES),
            setting("Break-glass repeat-use threshold (30 days)", s.BREAK_GLASS_REPEAT_THRESHOLD),
            setting("Service-account key lifetime (days)", s.SERVICE_KEY_MAX_DAYS),
        ],
        "retention": [
            setting("Uploaded documents (days)", s.DOCUMENT_RETENTION_DAYS),
            setting("Generated files (days)", s.ARTIFACT_RETENTION_DAYS),
            setting("Failed uploads (hours)", s.FAILED_UPLOAD_RETENTION_HOURS),
        ],
    }


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def usage(db: AsyncSession, tenant_id: str, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    this_month = _month_start(now)
    six_months_ago = _month_start(this_month - timedelta(days=150))

    def count(model, *conditions):
        return select(func.count()).select_from(model).where(model.tenant_id == tenant_id, *conditions).scalar_subquery()

    totals = (await db.execute(select(
        count(QueryAnswerRecord).label("questions_all_time"),
        count(QueryAnswerRecord, QueryAnswerRecord.created_at >= this_month).label("questions_this_month"),
        count(SavedAnswer).label("saved_answers"),
        count(Draft).label("drafts"),
        count(Document).label("documents"),
        count(GeneratedArtifact).label("generated_files"),
        select(func.count(func.distinct(QueryAnswerRecord.user_id)))
        .where(QueryAnswerRecord.tenant_id == tenant_id, QueryAnswerRecord.created_at >= this_month)
        .scalar_subquery().label("active_users_this_month"),
    ))).one()._mapping

    # Questions per month for the last six months, grouped here so the same
    # code runs on Postgres and SQLite.
    stamps = (await db.execute(
        select(QueryAnswerRecord.created_at)
        .where(QueryAnswerRecord.tenant_id == tenant_id, QueryAnswerRecord.created_at >= six_months_ago)
    )).scalars().all()
    per_month = Counter((s if s.tzinfo else s.replace(tzinfo=timezone.utc)).strftime("%Y-%m") for s in stamps)
    months, cursor = [], six_months_ago
    while cursor <= this_month:
        key = cursor.strftime("%Y-%m")
        months.append({"month": key, "label": cursor.strftime("%b %Y"), "questions": per_month.get(key, 0)})
        cursor = (cursor + timedelta(days=32)).replace(day=1)

    return {
        "totals": dict(totals),
        "questionsByMonth": months,
        "billing": {"connected": False,
                    "reason": "No billing or subscription system is connected to this deployment yet."},
        "generatedAt": now.isoformat(),
    }
