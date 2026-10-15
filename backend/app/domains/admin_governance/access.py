"""Users & Teams and Roles & Permissions: people, teams, access reviews,
offboarding, and the enforced role registry.

Everything is read from the tenant's records, the permission registry and
Supabase Auth (sign-in, invitation and MFA status). Access reviews follow
Privacy & Security §5: privileged roles monthly, every other role quarterly,
and never by the person reviewed.
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import supabase_admin
from app.core.config import get_settings
from app.domains.admin_governance import tenant_policy
from app.domains.admin_governance.models import AccessReview, Team, TeamMember
from app.domains.admin_governance.overview import ROLE_PURPOSE
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import (
    BreakGlassGrant, EngagementMembership, ServiceAccount, ServiceAccountKey, User,
)
from app.domains.identity.permissions import (
    ALL_PERMISSIONS, ROLE_PERMISSIONS, SERVICE_ACCOUNT_ROLES, STEP_UP_PERMISSIONS,
)
from app.domains.operations.models import IntegrationRecord, OperationsAlert, ProviderRecord, ServiceOwner

PRIVILEGED_REVIEW_DAYS = 30
STANDARD_REVIEW_DAYS = 90
INVITE_STALE_DAYS = 7
ACTIVE_ALERT_STATES = ("unacknowledged", "acknowledged", "investigating", "contained")

PERMISSION_LABELS = {
    "source.read": "Read source library", "source.manage": "Approve sources & versions",
    "support.read": "Read support & incidents", "support.manage": "Act on support & incidents",
    "model.manage": "Approve models & prompts", "audit.correct": "Correct the audit ledger",
    "safety.read": "Read AI safety", "safety.manage": "Change AI safety controls",
    "review.read": "Read review cases", "review.resolve": "Resolve review cases",
    "evaluation.read": "Read evaluations", "evaluation.manage": "Run evaluations & promote releases",
}

# Separation of duties: permission pairs one role must not hold together.
SOD_RULES = [
    ("review.resolve", "audit.correct", "Resolves a review case and can also correct the audit record of it"),
    ("model.manage", "evaluation.manage", "Changes a model or prompt and can also pass its own evaluation gate"),
    ("source.manage", "audit.correct", "Approves a source and can also correct the ledger entry for that approval"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: datetime | None) -> datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=timezone.utc))


def _iso(v: datetime | None) -> str | None:
    v = _aware(v)
    return v.isoformat() if v else None


def is_privileged(role: str) -> bool:
    return role == "Admin" or bool(ROLE_PERMISSIONS.get(role, frozenset()) & STEP_UP_PERMISSIONS)


def sod_conflicts(role: str) -> list[dict]:
    perms = ROLE_PERMISSIONS.get(role, frozenset())
    return [{"permissions": [a, b], "reason": why} for a, b, why in SOD_RULES if a in perms and b in perms]


class AccessError(ValueError):
    """A change the access rules refuse."""


# ── Supabase Auth status (sign-in, invitation, MFA) ────────────────────────

_AUTH_CACHE: dict[str, tuple[float, dict]] = {}
_AUTH_TTL = 60.0


async def _auth_status(user_ids: list[str]) -> dict[str, dict]:
    """Per-user sign-in facts from the Supabase Admin API, cached a minute.
    Missing (not configured, network fault) means "unknown", never a guess."""
    if not supabase_admin.is_configured() or not user_ids:
        return {}
    now = time.monotonic()
    out = {uid: data for uid in user_ids if (hit := _AUTH_CACHE.get(uid)) and now - hit[0] < _AUTH_TTL
           for data in [hit[1]]}
    missing = [uid for uid in user_ids if uid not in out][:200]
    if missing:
        base = get_settings().SUPABASE_URL.rstrip("/")
        limit = asyncio.Semaphore(8)

        async def fetch(client: httpx.AsyncClient, uid: str):
            async with limit:
                try:
                    r = await client.get(f"{base}/auth/v1/admin/users/{uid}", headers=supabase_admin._headers())
                    if r.status_code != 200:
                        return uid, None
                    u = r.json()
                    factors = [f for f in (u.get("factors") or []) if f.get("status") == "verified"]
                    providers = (u.get("app_metadata") or {}).get("providers") or []
                    return uid, {"lastSignInAt": u.get("last_sign_in_at"), "invitedAt": u.get("invited_at"),
                                 "confirmedAt": u.get("email_confirmed_at") or u.get("confirmed_at"),
                                 "mfa": bool(factors), "providers": providers}
                except (httpx.HTTPError, ValueError):
                    return uid, None

        async with httpx.AsyncClient(timeout=5.0) as client:
            for uid, data in await asyncio.gather(*(fetch(client, uid) for uid in missing)):
                if data is not None:
                    _AUTH_CACHE[uid] = (now, data)
                    out[uid] = data
    return out


# ── Shared reads ───────────────────────────────────────────────────────────

async def _service_ids(db: AsyncSession, tenant_id: str) -> set[str]:
    return set((await db.execute(select(ServiceAccount.id).where(ServiceAccount.tenant_id == tenant_id))).scalars())


async def _people(db: AsyncSession, tenant_id: str) -> list[User]:
    service = await _service_ids(db, tenant_id)
    users = (await db.execute(select(User).where(User.tenant_id == tenant_id).order_by(User.full_name))).scalars().all()
    return [u for u in users if u.id not in service]


async def _latest_reviews(db: AsyncSession, tenant_id: str) -> dict[str, AccessReview]:
    rows = (await db.execute(select(AccessReview).where(AccessReview.tenant_id == tenant_id)
                             .order_by(AccessReview.reviewed_at))).scalars().all()
    return {r.user_id: r for r in rows}


def review_due(user: User, last: AccessReview | None, now: datetime) -> tuple[datetime, bool]:
    interval = timedelta(days=PRIVILEGED_REVIEW_DAYS if is_privileged(user.role) else STANDARD_REVIEW_DAYS)
    # A review of an earlier role does not certify the current one.
    base = _aware(last.reviewed_at) if last and last.role == user.role else _aware(user.created_at)
    due = base + interval
    return due, due <= now


async def _blockers(db: AsyncSession, tenant_id: str, user_ids: set[str]) -> dict[str, list[dict]]:
    """What an inactive person still owns or holds: offboarding is complete
    only when every item has been reassigned or revoked."""
    out: dict[str, list[dict]] = defaultdict(list)
    if not user_ids:
        return out
    ids = list(user_ids)
    owned_sa = (await db.execute(select(ServiceAccount).where(
        ServiceAccount.tenant_id == tenant_id, ServiceAccount.owner_user_id.in_(ids)))).scalars().all()
    if owned_sa:
        live_keys = set((await db.execute(select(ServiceAccountKey.service_account_id).where(
            ServiceAccountKey.service_account_id.in_([s.id for s in owned_sa]), ServiceAccountKey.revoked_at.is_(None),
            ServiceAccountKey.expires_at > _now()))).scalars())
        for s in owned_sa:
            out[s.owner_user_id].append({"kind": "credential", "label": f"Owns service account {s.name}"
                                         + (" with a live API key" if s.id in live_keys else "")})
    for model, label in ((ProviderRecord, "provider"), (IntegrationRecord, "integration")):
        for r in (await db.execute(select(model).where(model.tenant_id == tenant_id, model.owner_user_id.in_(ids)))).scalars():
            out[r.owner_user_id].append({"kind": "ownership", "label": f"Owns {label} {r.ref} · {r.name}"})
    for a in (await db.execute(select(OperationsAlert).where(
            OperationsAlert.tenant_id == tenant_id, OperationsAlert.owner_user_id.in_(ids),
            OperationsAlert.state.in_(ACTIVE_ALERT_STATES)))).scalars():
        out[a.owner_user_id].append({"kind": "ownership", "label": f"Owns open alert {a.ref}"})
    for s in (await db.execute(select(ServiceOwner).where(
            ServiceOwner.tenant_id == tenant_id, ServiceOwner.owner_user_id.in_(ids)))).scalars():
        out[s.owner_user_id].append({"kind": "ownership", "label": f"Owns monitored service {s.service_key}"})
    for t in (await db.execute(select(Team).where(Team.tenant_id == tenant_id, Team.owner_user_id.in_(ids)))).scalars():
        out[t.owner_user_id].append({"kind": "ownership", "label": f"Owns team {t.name}"})
    for m in (await db.execute(select(TeamMember).where(
            TeamMember.tenant_id == tenant_id, TeamMember.user_id.in_(ids)))).scalars():
        out[m.user_id].append({"kind": "team", "label": "Still a member of a team"})
    for m in (await db.execute(select(EngagementMembership).where(
            EngagementMembership.tenant_id == tenant_id, EngagementMembership.user_id.in_(ids),
            EngagementMembership.status == "active"))).scalars():
        out[m.user_id].append({"kind": "access", "label": "Active client engagement membership"})
    for g in (await db.execute(select(BreakGlassGrant).where(
            BreakGlassGrant.tenant_id == tenant_id, BreakGlassGrant.user_id.in_(ids),
            BreakGlassGrant.status.in_(("requested", "active"))))).scalars():
        out[g.user_id].append({"kind": "access", "label": "Pending or active break-glass grant"})
    return out


def _offboarding_gates(blockers: list[dict]) -> list[dict]:
    kinds = Counter(b["kind"] for b in blockers)
    return [
        {"label": "Interactive sessions revoked", "status": "pass",
         "note": "The backend refuses every request from a deactivated account"},
        {"label": "Team access removed", "status": "open" if kinds["team"] else "pass",
         "note": "Still listed in a team" if kinds["team"] else "No team memberships"},
        {"label": "Delegated credentials revoked", "status": "open" if kinds["credential"] else "pass",
         "note": "Service-account ownership must move to an active person" if kinds["credential"] else "No credentials held"},
        {"label": "Resource ownership transferred", "status": "open" if kinds["ownership"] else "pass",
         "note": f"{kinds['ownership']} owned record(s) need a new owner" if kinds["ownership"] else "Nothing owned"},
        {"label": "Engagement and emergency access ended", "status": "open" if kinds["access"] else "pass",
         "note": "Active engagement or break-glass access remains" if kinds["access"] else "None remaining"},
    ]


async def _activity(db: AsyncSession, tenant_id: str, *, subject_ids: list[str] | None = None,
                    names: list[str] | None = None, prefixes: tuple[str, ...] = (), limit: int = 20) -> list[dict]:
    q = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
    if subject_ids:
        q = q.where(AuditEvent.subject_id.in_(subject_ids))
    if names:
        q = q.where(AuditEvent.event_name.in_(names))
    rows = (await db.execute(q.order_by(AuditEvent.ingested_at.desc()).limit(limit * (4 if prefixes else 1)))).scalars().all()
    if prefixes:
        rows = [r for r in rows if r.event_name.startswith(prefixes)][:limit]
    actor_ids = {r.actor_id for r in rows if r.actor_id}
    actors = {u.id: u.full_name or u.email for u in (await db.execute(
        select(User).where(User.id.in_(actor_ids or {""})))).scalars()}
    return [{"id": r.id, "event": r.event_name, "at": _iso(r.ingested_at), "actor": actors.get(r.actor_id or "", "System"),
             "subjectType": r.subject_type, "subjectId": r.subject_id,
             "detail": {k: v for k, v in (r.payload or {}).items() if k in {"ref", "role", "from", "to", "previous_role",
                                                                            "new_role", "is_active", "status", "note",
                                                                            "reason", "decision", "required", "permission"}}}
            for r in rows]


async def activity(db: AsyncSession, tenant_id: str, subject_id: str) -> list[dict]:
    return await _activity(db, tenant_id, subject_ids=[subject_id], limit=30)


# ── Users & Teams ──────────────────────────────────────────────────────────

async def users_view(db: AsyncSession, tenant_id: str) -> dict:
    now = _now()
    people = await _people(db, tenant_id)
    auth = await _auth_status([u.id for u in people])
    teams = (await db.execute(select(Team).where(Team.tenant_id == tenant_id).order_by(Team.name))).scalars().all()
    members = (await db.execute(select(TeamMember).where(TeamMember.tenant_id == tenant_id))).scalars().all()
    reviews = await _latest_reviews(db, tenant_id)
    inactive = {u.id for u in people if not u.is_active}
    blockers = await _blockers(db, tenant_id, inactive)
    teams_by_user: dict[str, list[str]] = defaultdict(list)
    team_names = {t.id: t.name for t in teams}
    for m in members:
        teams_by_user[m.user_id].append(team_names.get(m.team_id, ""))
    names = {u.id: u.full_name or u.email for u in people}

    rows = []
    for u in people:
        a = auth.get(u.id)
        never_signed_in = a is not None and not a.get("lastSignInAt")
        invited = bool(a and a.get("invitedAt")) and never_signed_in
        if not u.is_active:
            status = "offboarding" if blockers.get(u.id) else "inactive"
        else:
            status = "invited" if invited else "active"
        due_at, overdue = review_due(u, reviews.get(u.id), now)
        last = reviews.get(u.id)
        identity = ("unknown" if a is None else "invite_pending" if invited
                    else "mfa" if a.get("mfa") else "password_only")
        rows.append({
            "id": u.id, "name": u.full_name or u.email, "email": u.email, "role": u.role,
            "privileged": is_privileged(u.role), "teams": sorted(teams_by_user.get(u.id, [])),
            "status": status, "isActive": u.is_active, "identity": identity,
            "providers": (a or {}).get("providers", []), "lastSignInAt": (a or {}).get("lastSignInAt"),
            "invitedAt": (a or {}).get("invitedAt"), "createdAt": _iso(u.created_at),
            "reviewDueAt": due_at.isoformat(), "reviewOverdue": overdue and u.is_active,
            "lastReview": {"at": _iso(last.reviewed_at), "decision": last.decision, "reviewer": names.get(last.reviewer_id, ""),
                           "role": last.role} if last else None,
            "blockers": blockers.get(u.id, []),
            "offboardingGates": _offboarding_gates(blockers.get(u.id, [])) if not u.is_active else [],
        })

    team_rows = []
    for t in teams:
        ids = [m.user_id for m in members if m.team_id == t.id]
        team_rows.append({"id": t.id, "name": t.name, "description": t.description, "ownerId": t.owner_user_id,
                          "owner": names.get(t.owner_user_id or ""), "memberIds": ids, "members": len(ids),
                          "createdAt": _iso(t.created_at)})

    active = [r for r in rows if r["isActive"]]
    priorities = []
    for r in rows:
        if r["status"] == "offboarding":
            priorities.append({"kind": "offboarding", "userId": r["id"], "title": f"Offboarding · {r['name']}",
                               "detail": f"{len(r['blockers'])} item(s) still owned or held"})
    stale = [r for r in rows if r["status"] == "invited" and r["invitedAt"]
             and datetime.fromisoformat(r["invitedAt"].replace("Z", "+00:00")) < now - timedelta(days=INVITE_STALE_DAYS)]
    if stale:
        priorities.append({"kind": "invitations", "userId": stale[0]["id"], "title": "Invitations not accepted",
                           "detail": f"{len(stale)} invitation(s) older than {INVITE_STALE_DAYS} days"})
    overdue = [r for r in active if r["reviewOverdue"]]
    if overdue:
        priorities.append({"kind": "reviews", "userId": overdue[0]["id"], "title": "Access certifications due",
                           "detail": f"{len(overdue)} person(s) due for recertification"})
    known = [r for r in active if r["identity"] != "unknown"]
    return {
        "members": rows, "teams": team_rows,
        "summary": {
            "activeMembers": sum(r["status"] == "active" for r in rows),
            "openInvitations": sum(r["status"] == "invited" for r in rows),
            "staleInvitations": len(stale),
            "activeTeams": len(team_rows), "ownedTeams": sum(1 for t in team_rows if t["ownerId"]),
            "reviewsDue": len(overdue),
            "reviewsDueSoon": sum(1 for r in active if not r["reviewOverdue"]
                                  and datetime.fromisoformat(r["reviewDueAt"]) <= now + timedelta(days=7)),
            "offboardingCases": sum(r["status"] == "offboarding" for r in rows),
            "inactive": len(inactive),
        },
        "priorities": priorities,
        "controls": [
            {"label": "Identity proofing & MFA", "status": "pass" if known and all(r["identity"] == "mfa" for r in known) else "open",
             "detail": f"{sum(r['identity'] == 'mfa' for r in known)} of {len(known)} active people use an authenticator"
                       if known else "Sign-in status unavailable"},
            {"label": "Roles from the enforced registry only", "status": "pass" if all(r["role"] in ROLE_PERMISSIONS for r in active) else "fail",
             "detail": "Unknown roles carry no permissions; assignment is validated"},
            {"label": "Independent access reviews", "status": "pass" if not overdue else "open",
             "detail": "A person can never certify their own access"},
            {"label": "Revocation on deactivation", "status": "pass" if not any(r["status"] == "offboarding" for r in rows) else "open",
             "detail": "Deactivated accounts are refused at once; owned records must be reassigned"},
        ],
        "authStatusAvailable": bool(auth),
        "generatedAt": now.isoformat(),
    }


async def _audit(db: AsyncSession, actor: User, event: str, subject_type: str, subject_id: str, payload: dict) -> None:
    await record_event_async(db, tenant_id=actor.tenant_id, event_name=event, emitting_service="admin_governance",
                             actor_id=actor.id, subject_type=subject_type, subject_id=subject_id, payload=payload)


async def _tenant_person(db: AsyncSession, tenant_id: str, user_id: str | None, *, active: bool = True) -> User:
    if not user_id:
        raise AccessError("Choose a person")
    q = select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    if active:
        q = q.where(User.is_active.is_(True))
    user = (await db.execute(q)).scalar_one_or_none()
    if user is None or user.id in await _service_ids(db, tenant_id):
        raise AccessError("Choose an active person in this workspace")
    return user


async def create_team(db: AsyncSession, actor: User, name: str, description: str, owner_id: str | None) -> Team:
    name = name.strip()
    if not name:
        raise AccessError("A team name is required")
    if (await db.execute(select(Team.id).where(Team.tenant_id == actor.tenant_id, Team.name == name))).first():
        raise AccessError("A team with this name already exists")
    if owner_id:
        await _tenant_person(db, actor.tenant_id, owner_id)
    team = Team(tenant_id=actor.tenant_id, name=name, description=description.strip(), owner_user_id=owner_id,
                created_by=actor.id)
    db.add(team)
    await db.flush()
    await _audit(db, actor, "team_created", "team", team.id, {"name": name})
    return team


async def update_team(db: AsyncSession, actor: User, team_id: str, *, owner_id: str | None = None,
                      add: list[str] = (), remove: list[str] = ()) -> Team:
    team = (await db.execute(select(Team).where(Team.id == team_id, Team.tenant_id == actor.tenant_id))).scalar_one_or_none()
    if team is None:
        raise LookupError("Team not found")
    if owner_id:
        await _tenant_person(db, actor.tenant_id, owner_id)
        team.owner_user_id = owner_id
    for uid in add:
        await _tenant_person(db, actor.tenant_id, uid)
        if not (await db.execute(select(TeamMember.id).where(TeamMember.team_id == team.id, TeamMember.user_id == uid))).first():
            db.add(TeamMember(tenant_id=actor.tenant_id, team_id=team.id, user_id=uid, added_by=actor.id))
    for uid in remove:
        row = (await db.execute(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == uid))).scalar_one_or_none()
        if row is not None:
            await db.delete(row)
    await db.flush()
    await _audit(db, actor, "team_updated", "team", team.id,
                 {"owner": owner_id, "added": list(add), "removed": list(remove)})
    return team


async def record_review(db: AsyncSession, actor: User, user_id: str, decision: str, note: str) -> AccessReview:
    if decision not in {"certified", "role_changed", "deactivated"}:
        raise AccessError("Unknown decision")
    if user_id == actor.id:
        raise AccessError("You cannot certify your own access; another Admin must review it")
    person = await _tenant_person(db, actor.tenant_id, user_id, active=decision != "deactivated")
    if decision != "certified" and not note.strip():
        raise AccessError("Record why the access changed")
    review = AccessReview(tenant_id=actor.tenant_id, user_id=person.id, role=person.role, decision=decision,
                          note=note.strip(), reviewer_id=actor.id)
    db.add(review)
    await db.flush()
    await _audit(db, actor, "access_review_recorded", "user_account", person.id,
                 {"decision": decision, "role": person.role, "note": note.strip()})
    return review


# ── Roles & Permissions ────────────────────────────────────────────────────

async def roles_view(db: AsyncSession, tenant_id: str) -> dict:
    now = _now()
    people = await _people(db, tenant_id)
    active = [u for u in people if u.is_active]
    service_ids = await _service_ids(db, tenant_id)
    service_users = (await db.execute(select(User).where(User.id.in_(service_ids or {""}), User.is_active.is_(True)))).scalars().all()
    people_by_role = Counter(u.role for u in active)
    service_by_role = Counter(u.role for u in service_users)
    reviews = await _latest_reviews(db, tenant_id)
    overdue = [u for u in active if review_due(u, reviews.get(u.id), now)[1]]
    active_breakglass = (await db.execute(select(func.count()).select_from(BreakGlassGrant).where(
        BreakGlassGrant.tenant_id == tenant_id, BreakGlassGrant.status == "active",
        BreakGlassGrant.expires_at > now))).scalar_one()
    completed_reviews = (await db.execute(select(func.count()).select_from(AccessReview).where(
        AccessReview.tenant_id == tenant_id))).scalar_one()

    roles = []
    for name, perms in ROLE_PERMISSIONS.items():
        conflicts = sod_conflicts(name)
        roles.append({
            "name": name, "purpose": ROLE_PURPOSE.get(name, ""), "scope": "Tenant",
            "permissions": sorted(perms), "people": people_by_role.get(name, 0),
            "serviceAccounts": service_by_role.get(name, 0),
            "privileged": is_privileged(name), "stepUp": sorted(perms & STEP_UP_PERMISSIONS),
            "boundary": ("Everything, including users, keys and grants" if name == "Admin"
                         else "No governance permissions" if not perms
                         else f"{len(perms)} permission{'s' if len(perms) != 1 else ''}"
                         + (" · read only" if not perms & STEP_UP_PERMISSIONS else "")),
            "assignableToServiceAccounts": name in SERVICE_ACCOUNT_ROLES,
            "sodConflicts": conflicts, "reviewInterval": PRIVILEGED_REVIEW_DAYS if is_privileged(name) else STANDARD_REVIEW_DAYS,
        })
    unknown = sorted({u.role for u in active if u.role not in ROLE_PERMISSIONS})
    holders_with_conflicts = [u for u in active if sod_conflicts(u.role)]
    mfa = await tenant_policy.effective(db, tenant_id, "mfa_required_privileged")
    admins = sum(u.role == "Admin" for u in active)
    tests = [
        ("Every role in use is in the enforced registry", not unknown,
         "Unrecognised: " + ", ".join(unknown) if unknown else "All assigned roles are known"),
        ("Learner holds no governance permission", not ROLE_PERMISSIONS.get("Learner"), "Deny by default"),
        ("Service accounts can never hold Admin", "Admin" not in SERVICE_ACCOUNT_ROLES,
         "Administration needs a person"),
        ("System Auditor is read-only", not (ROLE_PERMISSIONS.get("System Auditor", frozenset()) & STEP_UP_PERMISSIONS),
         "No manage, resolve or correct permission"),
        ("Every privileged permission is in the registry", STEP_UP_PERMISSIONS <= ALL_PERMISSIONS, "Step-up list is consistent"),
        ("This workspace has an active Admin", admins > 0, f"{admins} active Admin(s)"),
        ("MFA required for privileged actions", bool(mfa),
         "Required" if mfa else "Not required by the deployment or this tenant (Tenant Settings)"),
        ("No standing emergency access", active_breakglass == 0,
         f"{active_breakglass} active break-glass grant(s)" if active_breakglass else "None active"),
        ("Access certifications current", not overdue, f"{len(overdue)} overdue" if overdue else "All current"),
        ("No separation-of-duties conflict held by a person", not holders_with_conflicts,
         f"{len(holders_with_conflicts)} person(s) hold a role with a conflict" if holders_with_conflicts else "None"),
    ]
    events = await _activity(db, tenant_id, names=[
        "access_denied", "admin_permission_changed", "auth.user_activation_changed", "access_review_recorded",
        "break_glass_access_granted", "break_glass_access_requested", "admin_impersonation_started"], limit=12)
    return {
        "roles": roles,
        "permissions": [{"key": p, "label": PERMISSION_LABELS.get(p, p), "stepUp": p in STEP_UP_PERMISSIONS}
                        for p in sorted(ALL_PERMISSIONS)],
        "sodRules": [{"permissions": [a, b], "reason": why,
                      "roles": [r for r, perms in ROLE_PERMISSIONS.items() if a in perms and b in perms]}
                     for a, b, why in SOD_RULES],
        "policyTests": [{"label": label, "passed": bool(ok), "detail": detail} for label, ok, detail in tests],
        "unrecognisedRoles": [{"name": r, "people": sum(u.role == r for u in active)} for r in unknown],
        "summary": {
            "roles": len(roles), "privilegedRoles": sum(r["privileged"] for r in roles),
            "identities": len(active) + len(service_users), "people": len(active), "serviceAccounts": len(service_users),
            "sodConflicts": sum(1 for r in roles if r["sodConflicts"]),
            "peopleWithConflicts": len(holders_with_conflicts),
            "reviewsDue": len(overdue), "reviewsCompleted": completed_reviews,
            "activeBreakGlass": active_breakglass,
            "testsPassed": sum(1 for _, ok, _ in tests if ok), "testsTotal": len(tests),
        },
        "events": events,
        "generatedAt": now.isoformat(),
    }


def simulate(role: str, permission: str, *, mfa_required: bool, session_mfa: bool) -> dict:
    """What the backend would decide, with the rule that decides it."""
    if permission not in ALL_PERMISSIONS:
        return {"decision": "deny", "reason": "Unknown permission: deny by default"}
    if role not in ROLE_PERMISSIONS:
        return {"decision": "deny", "reason": "Role is not in the registry: it carries no permissions"}
    if permission not in ROLE_PERMISSIONS[role]:
        return {"decision": "deny", "reason": f"{role} does not hold {permission}; only an approved break-glass grant could add it"}
    if permission in STEP_UP_PERMISSIONS and mfa_required and not session_mfa:
        return {"decision": "step_up", "reason": "Allowed only after an MFA challenge in this session"}
    return {"decision": "allow", "reason": f"{role} holds {permission}"}
