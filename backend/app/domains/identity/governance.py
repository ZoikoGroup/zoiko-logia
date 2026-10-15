"""Elevated-access governance: admin impersonation, break-glass grants and
service accounts (Privacy & Security spec §5, Audit Ledger §6, Event Catalog
admin-security family).

Every state change here writes an audit event, every elevation is tenant
scoped and time boxed, and none of them can be used to approve anything:
  * impersonation is read-only "view as" — the API refuses non-read requests
    made under it (see main.py's impersonation middleware);
  * break-glass needs a second Admin to activate it and a review after it ends;
  * service accounts authenticate only with an API key, can never hold Admin,
    and can never impersonate or request break-glass.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import (
    BreakGlassGrant,
    ImpersonationSession,
    ServiceAccount,
    ServiceAccountKey,
    User,
)
from app.domains.identity.permissions import ALL_PERMISSIONS, SERVICE_ACCOUNT_ROLES

API_KEY_PREFIX = "zlk_"
REPEAT_WINDOW = timedelta(days=30)


class GovernanceError(Exception):
    """A refused governance action, carrying the HTTP status to report."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes for timezone=True columns.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _audit(db: AsyncSession, actor: User, event_name: str, subject_type: str, subject_id: str, payload: dict) -> None:
    await record_event_async(
        db,
        tenant_id=actor.tenant_id,
        event_name=event_name,
        emitting_service="identity",
        actor_id=actor.id,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    )


_LIMIT_SETTINGS = {
    "impersonation_max_minutes": "IMPERSONATION_MAX_MINUTES",
    "break_glass_max_minutes": "BREAK_GLASS_MAX_MINUTES",
    "break_glass_repeat_threshold": "BREAK_GLASS_REPEAT_THRESHOLD",
    "service_key_max_days": "SERVICE_KEY_MAX_DAYS",
}


async def _tenant_limit(db: AsyncSession, tenant_id: str, key: str) -> int:
    """The deployment ceiling, or the tenant's stricter value if it set one
    (admin_governance/tenant_policy.py). Never above the deployment's."""
    from app.domains.admin_governance.tenant_policy import tenant_value
    deployment = getattr(get_settings(), _LIMIT_SETTINGS[key])
    tenant = await tenant_value(db, tenant_id, key)
    return deployment if tenant is None else min(deployment, int(tenant))


async def _tenant_user(db: AsyncSession, tenant_id: str, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    return result.scalar_one_or_none()


async def _is_service_account(db: AsyncSession, user_id: str) -> bool:
    return (await db.get(ServiceAccount, user_id)) is not None


def _require_interactive(user: User, action: str) -> None:
    if user.auth_method != "session":
        raise GovernanceError(status.HTTP_403_FORBIDDEN, f"Service accounts cannot {action}.")
    if user.impersonated_by:
        raise GovernanceError(status.HTTP_403_FORBIDDEN, f"You cannot {action} while viewing as another user.")


# ── Impersonation ────────────────────────────────────────────────────────────

async def start_impersonation(
    db: AsyncSession, actor: User, target_user_id: str, reason: str, minutes: int,
) -> ImpersonationSession:
    _require_interactive(actor, "start impersonation")
    limit = await _tenant_limit(db, actor.tenant_id, "impersonation_max_minutes")
    if not 1 <= minutes <= limit:
        raise GovernanceError(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Duration must be between 1 and {limit} minutes.")
    if not reason.strip():
        raise GovernanceError(status.HTTP_422_UNPROCESSABLE_CONTENT, "A reason is required.")
    if target_user_id == actor.id:
        raise GovernanceError(status.HTTP_409_CONFLICT, "You cannot impersonate yourself.")
    target = await _tenant_user(db, actor.tenant_id, target_user_id)
    if target is None:
        raise GovernanceError(status.HTTP_404_NOT_FOUND, "User not found")
    if target.role == "Admin":
        # Viewing as another Admin would expose administrative surfaces the
        # spec reserves for that Admin's own authenticated session.
        raise GovernanceError(status.HTTP_403_FORBIDDEN, "Administrators cannot be impersonated.")
    if not target.is_active or await _is_service_account(db, target.id):
        raise GovernanceError(status.HTTP_409_CONFLICT, "Only active people can be impersonated.")

    # One live session per Admin: starting a new one ends the previous.
    for previous in await _live_sessions(db, actor):
        previous.ended_at = _now()
    session = ImpersonationSession(
        tenant_id=actor.tenant_id,
        actor_id=actor.id,
        target_user_id=target.id,
        reason=reason.strip(),
        expires_at=_now() + timedelta(minutes=minutes),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    await _audit(db, actor, "admin_impersonation_started", "user_account", target.id, {
        "session_id": session.id, "reason": session.reason, "minutes": minutes, "read_only": True,
    })
    return session


async def _live_sessions(db: AsyncSession, actor: User) -> list[ImpersonationSession]:
    result = await db.execute(
        select(ImpersonationSession).where(
            ImpersonationSession.tenant_id == actor.tenant_id,
            ImpersonationSession.actor_id == actor.id,
            ImpersonationSession.ended_at.is_(None),
        )
    )
    return [s for s in result.scalars().all() if _aware(s.expires_at) > _now()]


async def active_impersonation(db: AsyncSession, actor: User) -> ImpersonationSession | None:
    sessions = await _live_sessions(db, actor)
    return sessions[0] if sessions else None


async def end_impersonation(db: AsyncSession, actor: User, session_id: str) -> ImpersonationSession:
    result = await db.execute(
        select(ImpersonationSession).where(
            ImpersonationSession.id == session_id,
            ImpersonationSession.tenant_id == actor.tenant_id,
            ImpersonationSession.actor_id == actor.id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise GovernanceError(status.HTTP_404_NOT_FOUND, "Impersonation session not found")
    if session.ended_at is None:
        session.ended_at = _now()
        await db.commit()
        await _audit(db, actor, "admin_impersonation_ended", "user_account", session.target_user_id, {
            "session_id": session.id,
        })
    return session


async def resolve_impersonation(db: AsyncSession, actor: User, session_id: str) -> User:
    """The user an Admin is viewing as, for a request carrying the session id.
    Fails closed: a missing, ended, expired or foreign session is a 403."""
    if actor.auth_method != "session" or actor.role != "Admin":
        raise GovernanceError(status.HTTP_403_FORBIDDEN, "Impersonation is not available to this account.")
    session = await db.get(ImpersonationSession, session_id)
    if (
        session is None
        or session.tenant_id != actor.tenant_id
        or session.actor_id != actor.id
        or session.ended_at is not None
        or _aware(session.expires_at) <= _now()
    ):
        raise GovernanceError(status.HTTP_403_FORBIDDEN, "This impersonation session has ended.")
    target = await _tenant_user(db, actor.tenant_id, session.target_user_id)
    if target is None or not target.is_active:
        raise GovernanceError(status.HTTP_403_FORBIDDEN, "This impersonation session has ended.")
    target.impersonated_by = actor.id
    target.impersonation_session_id = session.id
    return target


# ── Break-glass ──────────────────────────────────────────────────────────────

def _effective_status(grant: BreakGlassGrant) -> str:
    if grant.status == "active" and _aware(grant.expires_at) <= _now():
        return "expired"
    return grant.status


async def _expire_lapsed(db: AsyncSession, grants: list[BreakGlassGrant]) -> None:
    lapsed = [g for g in grants if g.status == "active" and _effective_status(g) == "expired"]
    for grant in lapsed:
        grant.status = "expired"
        grant.ended_at = grant.expires_at
    if lapsed:
        await db.commit()


async def active_break_glass_permissions(db: AsyncSession, user: User) -> frozenset[str]:
    result = await db.execute(
        select(BreakGlassGrant).where(
            BreakGlassGrant.tenant_id == user.tenant_id,
            BreakGlassGrant.user_id == user.id,
            BreakGlassGrant.status == "active",
        )
    )
    live = [g for g in result.scalars().all() if _effective_status(g) == "active"]
    return frozenset(p for g in live for p in g.permissions)


async def request_break_glass(
    db: AsyncSession, requester: User, permissions: list[str], reason: str, duration_minutes: int,
) -> BreakGlassGrant:
    _require_interactive(requester, "request break-glass access")
    limit = await _tenant_limit(db, requester.tenant_id, "break_glass_max_minutes")
    if not 1 <= duration_minutes <= limit:
        raise GovernanceError(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Duration must be between 1 and {limit} minutes.")
    if not reason.strip():
        raise GovernanceError(status.HTTP_422_UNPROCESSABLE_CONTENT, "A reason is required.")
    requested = sorted(set(permissions))
    unknown = [p for p in requested if p not in ALL_PERMISSIONS]
    if not requested or unknown:
        raise GovernanceError(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown permission(s): {', '.join(unknown) or 'none given'}")
    grant = BreakGlassGrant(
        tenant_id=requester.tenant_id,
        user_id=requester.id,
        permissions=requested,
        reason=reason.strip(),
        duration_minutes=duration_minutes,
    )
    db.add(grant)
    await db.commit()
    await db.refresh(grant)
    await _audit(db, requester, "break_glass_access_requested", "break_glass_grant", grant.id, {
        "permissions": requested, "duration_minutes": duration_minutes, "reason": grant.reason,
    })
    return grant


async def _tenant_grant(db: AsyncSession, actor: User, grant_id: str) -> BreakGlassGrant:
    grant = await db.get(BreakGlassGrant, grant_id)
    if grant is None or grant.tenant_id != actor.tenant_id:
        raise GovernanceError(status.HTTP_404_NOT_FOUND, "Break-glass grant not found")
    await _expire_lapsed(db, [grant])
    return grant


async def approve_break_glass(db: AsyncSession, approver: User, grant_id: str) -> BreakGlassGrant:
    _require_interactive(approver, "approve break-glass access")
    grant = await _tenant_grant(db, approver, grant_id)
    if grant.user_id == approver.id:
        await _audit(db, approver, "self_approval_attempt_blocked", "break_glass_grant", grant.id, {})
        raise GovernanceError(status.HTTP_403_FORBIDDEN, "A different administrator must approve your own request.")
    if grant.status != "requested":
        raise GovernanceError(status.HTTP_409_CONFLICT, f"This request is already {grant.status}.")
    now = _now()
    grant.status = "active"
    grant.approved_by = approver.id
    grant.activated_at = now
    grant.expires_at = now + timedelta(minutes=grant.duration_minutes)
    await db.commit()
    await db.refresh(grant)
    await _audit(db, approver, "break_glass_access_granted", "break_glass_grant", grant.id, {
        "user_id": grant.user_id, "permissions": grant.permissions,
        "expires_at": grant.expires_at.isoformat(),
    })
    recent = (await db.execute(
        select(func.count()).select_from(BreakGlassGrant).where(
            BreakGlassGrant.tenant_id == grant.tenant_id,
            BreakGlassGrant.user_id == grant.user_id,
            BreakGlassGrant.activated_at.is_not(None),
            BreakGlassGrant.activated_at >= now - REPEAT_WINDOW,
        )
    )).scalar_one()
    if recent >= await _tenant_limit(db, grant.tenant_id, "break_glass_repeat_threshold"):
        await _audit(db, approver, "break_glass_repeated_use_detected", "user_account", grant.user_id, {
            "grants_in_30_days": recent, "latest_grant_id": grant.id,
        })
    return grant


async def reject_break_glass(db: AsyncSession, approver: User, grant_id: str) -> BreakGlassGrant:
    _require_interactive(approver, "reject break-glass access")
    grant = await _tenant_grant(db, approver, grant_id)
    if grant.status != "requested":
        raise GovernanceError(status.HTTP_409_CONFLICT, f"This request is already {grant.status}.")
    grant.status = "rejected"
    grant.ended_at = _now()
    grant.ended_by = approver.id
    await db.commit()
    await _audit(db, approver, "break_glass_access_rejected", "break_glass_grant", grant.id, {"user_id": grant.user_id})
    return grant


async def revoke_break_glass(db: AsyncSession, actor: User, grant_id: str) -> BreakGlassGrant:
    """Ends an active grant early. The holder may give it up; any Admin may
    take it away."""
    grant = await _tenant_grant(db, actor, grant_id)
    if actor.id != grant.user_id and actor.role != "Admin":
        raise GovernanceError(status.HTTP_403_FORBIDDEN, "Only the holder or an administrator can end this grant.")
    if grant.status != "active":
        raise GovernanceError(status.HTTP_409_CONFLICT, f"This grant is already {grant.status}.")
    grant.status = "revoked"
    grant.ended_at = _now()
    grant.ended_by = actor.id
    await db.commit()
    await _audit(db, actor, "break_glass_access_revoked", "break_glass_grant", grant.id, {"user_id": grant.user_id})
    return grant


async def review_break_glass(db: AsyncSession, reviewer: User, grant_id: str, notes: str) -> BreakGlassGrant:
    """Post-use review, required once a grant has ended. The holder cannot
    review their own use."""
    _require_interactive(reviewer, "review break-glass access")
    grant = await _tenant_grant(db, reviewer, grant_id)
    if grant.user_id == reviewer.id:
        await _audit(db, reviewer, "self_approval_attempt_blocked", "break_glass_grant", grant.id, {"action": "review"})
        raise GovernanceError(status.HTTP_403_FORBIDDEN, "Another administrator must review your own break-glass use.")
    if grant.status not in {"expired", "revoked"}:
        raise GovernanceError(status.HTTP_409_CONFLICT, "Only a grant that has ended can be reviewed.")
    if grant.reviewed_at is not None:
        raise GovernanceError(status.HTTP_409_CONFLICT, "This grant has already been reviewed.")
    if not notes.strip():
        raise GovernanceError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Review notes are required.")
    grant.reviewed_by = reviewer.id
    grant.reviewed_at = _now()
    grant.review_notes = notes.strip()
    await db.commit()
    await _audit(db, reviewer, "break_glass_access_reviewed", "break_glass_grant", grant.id, {"user_id": grant.user_id})
    return grant


async def list_break_glass(db: AsyncSession, viewer: User) -> list[BreakGlassGrant]:
    """Admins see the tenant's grants; everyone else sees their own."""
    query = select(BreakGlassGrant).where(BreakGlassGrant.tenant_id == viewer.tenant_id)
    if viewer.role != "Admin":
        query = query.where(BreakGlassGrant.user_id == viewer.id)
    grants = list((await db.execute(query.order_by(BreakGlassGrant.requested_at.desc()))).scalars().all())
    await _expire_lapsed(db, grants)
    return grants


# ── Service accounts ─────────────────────────────────────────────────────────

def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def create_service_account(
    db: AsyncSession, admin: User, *, name: str, description: str, role: str, owner_user_id: str,
) -> ServiceAccount:
    _require_interactive(admin, "create service accounts")
    if role not in SERVICE_ACCOUNT_ROLES:
        raise GovernanceError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Service accounts cannot hold that role.")
    if not name.strip():
        raise GovernanceError(status.HTTP_422_UNPROCESSABLE_CONTENT, "A name is required.")
    owner = await _tenant_user(db, admin.tenant_id, owner_user_id)
    if owner is None or not owner.is_active or await _is_service_account(db, owner.id):
        raise GovernanceError(status.HTTP_422_UNPROCESSABLE_CONTENT, "The owner must be an active person in this tenant.")
    user = User(
        tenant_id=admin.tenant_id,
        # No Supabase auth user exists for this address, so it can never sign
        # in interactively; .invalid is reserved and never routable (RFC 2606).
        email=f"svc-{secrets.token_hex(8)}@service-accounts.invalid",
        first_name=name.strip(),
        last_name="",
        full_name=name.strip(),
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    account = ServiceAccount(
        id=user.id,
        tenant_id=admin.tenant_id,
        name=name.strip(),
        description=description.strip(),
        owner_user_id=owner.id,
        created_by=admin.id,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    await _audit(db, admin, "service_account_created", "service_account", account.id, {
        "name": account.name, "role": role, "owner_user_id": owner.id,
    })
    return account


async def list_service_accounts(db: AsyncSession, admin: User) -> list[tuple[ServiceAccount, User, list[ServiceAccountKey]]]:
    accounts = (await db.execute(
        select(ServiceAccount).where(ServiceAccount.tenant_id == admin.tenant_id).order_by(ServiceAccount.created_at)
    )).scalars().all()
    rows = []
    for account in accounts:
        user = await db.get(User, account.id)
        keys = (await db.execute(
            select(ServiceAccountKey)
            .where(ServiceAccountKey.service_account_id == account.id)
            .order_by(ServiceAccountKey.created_at.desc())
        )).scalars().all()
        rows.append((account, user, list(keys)))
    return rows


async def _tenant_service_account(db: AsyncSession, admin: User, account_id: str) -> ServiceAccount:
    account = await db.get(ServiceAccount, account_id)
    if account is None or account.tenant_id != admin.tenant_id:
        raise GovernanceError(status.HTTP_404_NOT_FOUND, "Service account not found")
    return account


async def issue_service_account_key(
    db: AsyncSession, admin: User, account_id: str, expires_in_days: int,
) -> tuple[ServiceAccountKey, str]:
    """Returns the stored key row and the plaintext key — the only time the
    plaintext exists outside the caller's hands."""
    _require_interactive(admin, "issue API keys")
    limit = await _tenant_limit(db, admin.tenant_id, "service_key_max_days")
    if not 1 <= expires_in_days <= limit:
        raise GovernanceError(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Expiry must be between 1 and {limit} days.")
    account = await _tenant_service_account(db, admin, account_id)
    user = await db.get(User, account.id)
    if user is None or not user.is_active:
        raise GovernanceError(status.HTTP_409_CONFLICT, "This service account is disabled.")
    raw_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    key = ServiceAccountKey(
        service_account_id=account.id,
        tenant_id=account.tenant_id,
        key_prefix=raw_key[:12],
        key_hash=hash_api_key(raw_key),
        created_by=admin.id,
        expires_at=_now() + timedelta(days=expires_in_days),
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    await _audit(db, admin, "service_account_key_issued", "service_account", account.id, {
        "key_id": key.id, "key_prefix": key.key_prefix, "expires_at": key.expires_at.isoformat(),
    })
    return key, raw_key


async def revoke_service_account_key(db: AsyncSession, admin: User, account_id: str, key_id: str) -> ServiceAccountKey:
    account = await _tenant_service_account(db, admin, account_id)
    key = await db.get(ServiceAccountKey, key_id)
    if key is None or key.service_account_id != account.id:
        raise GovernanceError(status.HTTP_404_NOT_FOUND, "API key not found")
    if key.revoked_at is None:
        key.revoked_at = _now()
        await db.commit()
        await _audit(db, admin, "service_account_key_revoked", "service_account", account.id, {
            "key_id": key.id, "key_prefix": key.key_prefix,
        })
    return key


async def resolve_api_key(db: AsyncSession, raw_key: str) -> ServiceAccountKey | None:
    """The live key row for a presented API key, or None. Revoked, expired
    and unknown keys all look the same to the caller."""
    if not raw_key.startswith(API_KEY_PREFIX):
        return None
    key = (await db.execute(
        select(ServiceAccountKey).where(ServiceAccountKey.key_hash == hash_api_key(raw_key))
    )).scalar_one_or_none()
    if key is None or key.revoked_at is not None or _aware(key.expires_at) <= _now():
        return None
    return key


async def touch_api_key(db: AsyncSession, key: ServiceAccountKey) -> None:
    """Record use at most once a minute, so a busy integration doesn't turn
    every request into a write."""
    now = _now()
    last = _aware(key.last_used_at)
    if last is None or now - last > timedelta(minutes=1):
        key.last_used_at = now
        await db.commit()


async def service_account_ids(db: AsyncSession, tenant_id: str) -> set[str]:
    rows = await db.execute(select(ServiceAccount.id).where(ServiceAccount.tenant_id == tenant_id))
    return set(rows.scalars().all())
