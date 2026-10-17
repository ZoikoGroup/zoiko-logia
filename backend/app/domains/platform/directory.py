"""Super Admin directory: every company (tenant) and every account on the
platform, with each account's sign-in status.

Identity and account metadata only — names, emails, roles, account state and
sign-in times. Never tenant content (documents, conversations, workpapers),
and from Supabase's auth schema only non-secret columns: no password hashes,
tokens, IP addresses or user agents.

Sign-in facts come straight from Supabase's auth schema on the owner
connection (the same Postgres database). On a database without it (SQLite in
tests) they are reported as unknown rather than guessed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import session_is_sqlite
from app.domains.audit_ledger.models import AuditEvent
from app.domains.billing.models import BillingPlan
from app.domains.identity.models import ServiceAccount, Tenant, User

PERSONAL_SUFFIX = " (personal)"
# Access tokens refresh hourly, so a session refreshed within this window
# belongs to someone who has the app open (or did a moment ago).
ONLINE_WINDOW = timedelta(minutes=65)

_AUTH_USERS = text("""
    SELECT u.id::text AS id, u.email_confirmed_at, u.last_sign_in_at, u.created_at, u.banned_until,
           COALESCE(u.raw_app_meta_data->'providers', '[]'::jsonb) AS providers
    FROM auth.users u
    WHERE u.deleted_at IS NULL
""")
_AUTH_SESSIONS = text("""
    SELECT s.user_id::text AS user_id, count(*) AS sessions,
           max(COALESCE(s.refreshed_at, s.updated_at, s.created_at)) AS last_seen
    FROM auth.sessions s
    WHERE s.not_after IS NULL OR s.not_after > now()
    GROUP BY s.user_id
""")
_AUTH_MFA = text("SELECT user_id::text AS user_id FROM auth.mfa_factors WHERE status = 'verified' GROUP BY user_id")


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


def _latest(*values: datetime | None) -> datetime | None:
    present = [_aware(v) for v in values if v is not None]
    return max(present) if present else None


async def _auth_facts(db: AsyncSession) -> tuple[bool, dict, dict, set]:
    """(available, auth users by id, live sessions by user id, ids with MFA)."""
    if session_is_sqlite(db):
        return False, {}, {}, set()
    try:
        users = {r["id"]: r for r in (await db.execute(_AUTH_USERS)).mappings()}
        sessions = {r["user_id"]: r for r in (await db.execute(_AUTH_SESSIONS)).mappings()}
        mfa = set((await db.execute(_AUTH_MFA)).scalars())
    except Exception:  # noqa: BLE001 — no auth schema / no grant: say "unknown", never guess
        await db.rollback()
        return False, {}, {}, set()
    return True, users, sessions, mfa


def _status(user: User, auth: dict | None, auth_available: bool, now: datetime) -> str:
    if not user.is_active:
        return "deactivated"
    if not auth_available:
        return "active"
    if auth is None:
        return "no_login"  # profile without a Supabase identity: cannot sign in
    banned = _aware(auth["banned_until"])
    if banned and banned > now:
        return "suspended"
    if not auth["email_confirmed_at"]:
        return "unconfirmed"
    if not auth["last_sign_in_at"]:
        return "never_signed_in"
    return "active"


async def directory(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    tenants = (await db.execute(select(Tenant))).scalars().all()
    users = (await db.execute(select(User))).scalars().all()
    service_ids = set((await db.execute(select(ServiceAccount.id))).scalars())
    auth_available, auth_users, sessions, mfa = await _auth_facts(db)

    last_activity = dict((await db.execute(
        select(AuditEvent.actor_id, func.max(AuditEvent.ingested_at))
        .where(AuditEvent.actor_id.is_not(None)).group_by(AuditEvent.actor_id))).all())
    tenant_activity = dict((await db.execute(
        select(AuditEvent.tenant_id, func.max(AuditEvent.ingested_at)).group_by(AuditEvent.tenant_id))).all())
    planned = set((await db.execute(
        select(BillingPlan.tenant_id).where(BillingPlan.status == "active"))).scalars())
    tenant_names = {t.id: t.name for t in tenants}

    accounts: list[dict] = []
    for u in users:
        if u.id in service_ids:
            continue  # API credentials, managed per tenant — not people
        auth = auth_users.get(u.id)
        live = sessions.get(u.id)
        last_seen = _aware(live["last_seen"]) if live else None
        accounts.append({
            "id": u.id,
            "name": u.full_name or u.email.split("@")[0],
            "email": u.email,
            "role": u.role,
            "platformRole": u.platform_role,
            "tenantId": u.tenant_id,
            "tenant": tenant_names.get(u.tenant_id, "Unknown company"),
            "status": _status(u, auth, auth_available, now),
            "createdAt": _iso(u.created_at),
            "emailConfirmed": bool(auth and auth["email_confirmed_at"]) if auth_available else None,
            "lastSignInAt": _iso(auth["last_sign_in_at"]) if auth else None,
            "lastSeenAt": _iso(last_seen),
            "lastActivityAt": _iso(last_activity.get(u.id)),
            "online": bool(last_seen and now - last_seen <= ONLINE_WINDOW),
            "activeSessions": int(live["sessions"]) if live else 0,
            "mfa": u.id in mfa if auth_available else None,
            "providers": list(auth["providers"]) if auth else [],
        })
    accounts.sort(key=lambda a: (not a["online"], -(_aware(datetime.fromisoformat(a["lastSignInAt"])).timestamp()
                                                     if a["lastSignInAt"] else 0), a["email"]))

    by_tenant: dict[str, list[dict]] = defaultdict(list)
    for a in accounts:
        by_tenant[a["tenantId"]].append(a)

    def signed_in_within(members: list[dict], window: timedelta) -> int:
        return sum(1 for m in members if m["lastSignInAt"] and now - datetime.fromisoformat(m["lastSignInAt"]) <= window)

    companies: list[dict] = []
    for t in tenants:
        members = by_tenant.get(t.id, [])
        personal = t.name.endswith(PERSONAL_SUFFIX)
        last_sign_in = _latest(*(datetime.fromisoformat(m["lastSignInAt"]) for m in members if m["lastSignInAt"]))
        last_active = _latest(_aware(tenant_activity.get(t.id)), last_sign_in)
        online = sum(m["online"] for m in members)
        if not members:
            state = "empty"
        elif online:
            state = "online"
        elif last_active and now - last_active <= timedelta(days=30):
            state = "active"
        else:
            state = "dormant"
        created = [datetime.fromisoformat(m["createdAt"]) for m in members if m["createdAt"]]
        name = (t.name[: -len(PERSONAL_SUFFIX)] if personal else t.name).strip()
        if not name:
            # Signed up without a company name: identify it by its owner.
            owner = next((m for m in members if m["role"] == "Admin"), members[0] if members else None)
            name = f"Unnamed company ({owner['email']})" if owner else "Unnamed company"
        companies.append({
            "id": t.id,
            "name": name,
            "type": "personal" if personal else "company",
            "state": state,
            "createdAt": _iso(min(created)) if created else None,
            "members": len(members),
            "activeMembers": sum(m["status"] == "active" for m in members),
            "online": online,
            "signedIn24h": signed_in_within(members, timedelta(hours=24)),
            "signedIn7d": signed_in_within(members, timedelta(days=7)),
            "roles": dict(Counter(m["role"] for m in members)),
            "admins": [{"name": m["name"], "email": m["email"]} for m in members if m["role"] == "Admin"],
            "lastSignInAt": _iso(last_sign_in),
            "lastActivityAt": _iso(last_active),
            "billingPlan": t.id in planned,
            "issues": sum(m["status"] in ("unconfirmed", "no_login", "suspended") for m in members),
        })
    order = {"online": 0, "active": 1, "dormant": 2, "empty": 3}
    companies.sort(key=lambda c: (order[c["state"]], -(datetime.fromisoformat(c["lastActivityAt"]).timestamp()
                                                        if c["lastActivityAt"] else 0), c["name"].lower()))

    statuses = Counter(a["status"] for a in accounts)
    real = [c for c in companies if c["type"] == "company"]
    return {
        "generatedAt": now.isoformat(),
        "signInDataAvailable": auth_available,
        "summary": {
            "companies": len(real),
            "personalWorkspaces": len(companies) - len(real),
            "companiesOnline": sum(c["online"] > 0 for c in real),
            "companiesSignedIn24h": sum(c["signedIn24h"] > 0 for c in real),
            "companiesActive30d": sum(c["state"] in ("online", "active") for c in real),
            "accounts": len(accounts),
            "online": sum(a["online"] for a in accounts),
            "signedIn24h": signed_in_within(accounts, timedelta(hours=24)),
            "signedIn7d": signed_in_within(accounts, timedelta(days=7)),
            "statuses": dict(statuses),
            "roles": dict(Counter(a["role"] for a in accounts)),
            "withMfa": sum(1 for a in accounts if a["mfa"]),
        },
        "companies": companies,
        "accounts": accounts,
    }
