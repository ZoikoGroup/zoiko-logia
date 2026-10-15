"""Service Accounts and Entities/Clients views.

Service accounts: each machine identity's state, risk and authorization
checks, worked out from its role, owner and keys — the same records the
service-account API manages. Entities/Clients: the client engagements that
exist today (F1 engagement model). A legal-entity register stays blocked
pending DPIA and Legal/Compliance sign-off.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin_governance.access import sod_conflicts
from app.domains.identity.models import (
    Engagement, EngagementGrant, EngagementMembership, ServiceAccount, ServiceAccountKey, User,
)
from app.domains.identity.permissions import ROLE_PERMISSIONS, STEP_UP_PERMISSIONS

RENEWAL_WINDOW = timedelta(days=7)
DORMANT_AFTER = timedelta(days=30)
ROTATION_AGE = timedelta(days=90)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: datetime | None) -> datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=timezone.utc))


def _iso(v: datetime | None) -> str | None:
    v = _aware(v)
    return v.isoformat() if v else None


async def service_accounts(db: AsyncSession, tenant_id: str) -> dict:
    now = _now()
    accounts = (await db.execute(select(ServiceAccount).where(ServiceAccount.tenant_id == tenant_id)
                                 .order_by(ServiceAccount.created_at))).scalars().all()
    ids = [a.id for a in accounts]
    users = {u.id: u for u in (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars()}
    keys: dict[str, list[ServiceAccountKey]] = defaultdict(list)
    for k in (await db.execute(select(ServiceAccountKey).where(ServiceAccountKey.service_account_id.in_(ids or [""])))).scalars():
        keys[k.service_account_id].append(k)

    rows = []
    for a in accounts:
        identity = users.get(a.id)
        owner = users.get(a.owner_user_id)
        perms = ROLE_PERMISSIONS.get(identity.role if identity else "", frozenset())
        live = [k for k in keys[a.id] if k.revoked_at is None and _aware(k.expires_at) > now]
        expiring = [k for k in live if _aware(k.expires_at) <= now + RENEWAL_WINDOW]
        last_used = max((_aware(k.last_used_at) for k in keys[a.id] if k.last_used_at), default=None)
        oldest_live = min((_aware(k.created_at) for k in live), default=None)
        owner_ok = bool(owner and owner.is_active)
        active = bool(identity and identity.is_active)
        writes = sorted(perms & STEP_UP_PERMISSIONS)
        if not active:
            state = "disabled"
        elif not owner_ok:
            state = "quarantined"
        elif not live:
            state = "dormant" if keys[a.id] else "no_credential"
        elif expiring:
            state = "restricted"  # renewal due: a new key is needed before the old one lapses
        else:
            state = "active"
        risk = "critical" if not owner_ok and live else "high" if writes else "medium" if perms else "low"
        checks = [
            {"label": "Named accountable owner", "status": "pass" if owner_ok else "fail",
             "note": f"{owner.full_name or owner.email}" + ("" if owner_ok else " is deactivated; assign a new owner")
             if owner else "Owner not found"},
            {"label": "Credential health / rotation",
             "status": "pass" if live and not expiring and oldest_live and now - oldest_live <= ROTATION_AGE
             else "open" if live else "fail",
             "note": (f"{len(expiring)} key(s) expire within 7 days" if expiring else
                      "Oldest live key is over 90 days old; rotate it" if oldest_live and now - oldest_live > ROTATION_AGE else
                      f"{len(live)} live key(s)") if live else "No live key"},
            {"label": "Least-privilege role", "status": "pass" if not writes else "open",
             "note": "Read-only role" if not writes else f"Can change governed state: {', '.join(writes)}"},
            {"label": "Usage reviewed", "status": "pass" if last_used and now - last_used <= DORMANT_AFTER else "open",
             "note": f"Last used {last_used.date().isoformat()}" if last_used else "Never used"},
            {"label": "Independent authorization", "status": "pass" if a.created_by != a.owner_user_id else "open",
             "note": "Created by someone other than its owner" if a.created_by != a.owner_user_id
             else "The owner created it; have another Admin confirm the purpose"},
        ]
        rows.append({
            "id": a.id, "name": a.name, "description": a.description, "role": identity.role if identity else "",
            "permissions": sorted(perms), "ownerId": a.owner_user_id, "owner": owner.full_name if owner else "",
            "ownerActive": owner_ok, "createdBy": (users.get(a.created_by).full_name if users.get(a.created_by) else ""),
            "createdAt": _iso(a.created_at), "isActive": active, "state": state, "risk": risk,
            "liveKeys": len(live), "expiringKeys": len(expiring),
            "nextExpiry": _iso(min((k.expires_at for k in live), default=None)),
            "lastUsedAt": _iso(last_used), "checks": checks,
            "checksPassed": sum(c["status"] == "pass" for c in checks), "sodConflicts": sod_conflicts(identity.role if identity else ""),
            "keys": [{"id": k.id, "prefix": k.key_prefix, "createdAt": _iso(k.created_at), "expiresAt": _iso(k.expires_at),
                      "revokedAt": _iso(k.revoked_at), "lastUsedAt": _iso(k.last_used_at)} for k in keys[a.id]],
        })
    states = Counter(r["state"] for r in rows)
    return {
        "accounts": rows,
        "summary": {
            "accounts": len(rows), "liveKeys": sum(r["liveKeys"] for r in rows),
            "renewals": sum(1 for r in rows if r["expiringKeys"]),
            "scopeExceptions": sum(1 for r in rows if r["isActive"] and any(c["label"] == "Least-privilege role" and c["status"] != "pass" for c in r["checks"])),
            "ownershipReviews": sum(1 for r in rows if not r["ownerActive"]),
            "quarantined": states["quarantined"], "states": dict(states),
        },
        "generatedAt": now.isoformat(),
    }


async def entities(db: AsyncSession, tenant_id: str) -> dict:
    now = _now()
    engagements = (await db.execute(select(Engagement).where(Engagement.tenant_id == tenant_id)
                                    .order_by(Engagement.created_at))).scalars().all()
    memberships = (await db.execute(select(EngagementMembership).where(EngagementMembership.tenant_id == tenant_id))).scalars().all()
    grants = (await db.execute(select(EngagementGrant).where(EngagementGrant.tenant_id == tenant_id))).scalars().all()
    users = {u.id: u for u in (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars()}
    ops: dict[str, list[str]] = defaultdict(list)
    for g in grants:
        if g.effect == "allow" and (g.expires_at is None or _aware(g.expires_at) > now):
            ops[g.membership_id].append(g.operation)
    rows = []
    for e in engagements:
        members = [m for m in memberships if m.engagement_id == e.id]
        active = [m for m in members if m.status == "active"]
        rows.append({
            "id": e.id, "name": e.name, "status": e.status, "rightsVersion": e.rights_version,
            "createdAt": _iso(e.created_at), "activeMembers": len(active), "revokedMembers": len(members) - len(active),
            "members": [{"userId": m.user_id, "name": (users[m.user_id].full_name if m.user_id in users else m.user_id),
                         "role": m.engagement_role, "status": m.status, "grantedAt": _iso(m.granted_at),
                         "revokedAt": _iso(m.revoked_at), "operations": sorted(ops.get(m.id, []))} for m in members],
        })
    return {
        "engagements": rows,
        "summary": {"engagements": len(rows), "active": sum(r["status"] == "active" for r in rows),
                    "members": sum(r["activeMembers"] for r in rows),
                    "revoked": sum(r["revokedMembers"] for r in rows),
                    "withoutMembers": sum(1 for r in rows if r["activeMembers"] == 0)},
        "legalEntityRegister": {"available": False,
                                "reason": "Blocked pending Data Protection Impact Assessment and Legal/Compliance sign-off."},
        "generatedAt": now.isoformat(),
    }
