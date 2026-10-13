import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import supabase_admin
from app.core.config import get_settings
from app.domains.identity.models import Role, ServiceAccount, Tenant, User
from app.domains.identity.schemas import ProvisionRequest, UserCreateRequest

log = logging.getLogger("uvicorn.error")


def _sync_app_metadata_best_effort(user_id: str, tenant_id: str, role: str) -> None:
    """Best-effort stamp of tenant_id/role into the Supabase user's
    app_metadata so future-issued tokens carry it (see database.py's
    _identity_from_request). The local DB row is the source of truth for
    get_current_user, so a missing/misconfigured service-role key must not
    brick provisioning — without this, login 503s right after the profile
    row is committed whenever SUPABASE_SERVICE_ROLE_KEY is absent."""
    try:
        supabase_admin.update_app_metadata(user_id, tenant_id, role)
    except supabase_admin.SupabaseNotConfiguredError:
        log.warning(
            "app_metadata sync skipped: SUPABASE_SERVICE_ROLE_KEY unset. "
            "Provisioning proceeded; tokens will not carry tenant_id/role "
            "until the service-role key is configured."
        )
    except Exception:
        log.warning(
            "app_metadata sync skipped for user %s: admin API call failed.", user_id,
        )

logger = logging.getLogger(__name__)


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def list_roles(db: AsyncSession) -> list[Role]:
    result = await db.execute(select(Role))
    return list(result.scalars().all())


async def list_users(db: AsyncSession, tenant_id: str) -> list[User]:
    """People in the tenant. Service accounts also have a users row (it
    carries their role) but are managed on their own page, not here."""
    service_accounts = select(ServiceAccount.id).where(ServiceAccount.tenant_id == tenant_id)
    result = await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.id.not_in(service_accounts))
    )
    return list(result.scalars().all())


async def create_user(db: AsyncSession, tenant_id: str, payload: UserCreateRequest) -> User:
    """Admin-created teammate: creates the Supabase auth user first, then the
    local profile row keyed by the id Supabase assigned. Without a password the
    user is invited by email and chooses their own on /auth/accept-invite, so
    no Admin ever knows it; with one, the account is confirmed immediately."""
    if payload.password:
        auth_user = supabase_admin.create_user(payload.email, payload.password, email_confirm=True)
    else:
        auth_user = supabase_admin.invite_user(
            payload.email, redirect_to=f"{get_settings().FRONTEND_URL.rstrip('/')}/auth/accept-invite",
        )
    first_name, _, last_name = payload.full_name.partition(" ")

    user = User(
        id=auth_user["id"],
        tenant_id=tenant_id,
        email=payload.email,
        first_name=first_name,
        last_name=last_name,
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    _sync_app_metadata_best_effort(user.id, tenant_id, payload.role)
    return user


async def provision_profile(
    db: AsyncSession,
    user_id: str,
    email: str,
    payload: ProvisionRequest,
    *,
    token_tenant_id: str = "",
    token_role: str = "",
) -> User:
    """Idempotent upsert called by the frontend right after a Supabase
    sign-up/first OAuth login. First call creates the Tenant (from
    company_name) + User row and stamps tenant_id/role into the Supabase
    user's app_metadata. Later calls return the existing row —
    provisioning must never create a second Tenant/User for the same
    Supabase auth user.

    Later calls also repair the stamp when the caller's token disagrees with
    the profile (token_tenant_id/token_role are the verified token's claims).
    The first call commits the User row BEFORE stamping app_metadata, so a
    failed stamp (Admin API down, bad service-role key) used to leave the
    account permanently without a tenant in its tokens — and every
    tenant-scoped RLS write then failed for that user. A repair failure is
    logged, never raised: an existing user must still be able to sign in."""
    existing = await get_user_by_id(db, user_id)
    if existing is not None:
        # Re-stamp app_metadata when this access token's embedded app_metadata
        # has drifted from the authoritative users row — and only then, so a
        # matched re-provision (the common daily login) stays a true no-op
        # that never touches the Admin API. Drift is what breaks RLS writes:
        # rows are written with this row's tenant_id while the RLS WITH CHECK
        # compares against app.tenant_id from the token's claim, so a stale
        # claim makes every INSERT fail with "violates row-level security
        # policy" until a fresh sign-in re-stamps it. A claim that carries no
        # identity at all (a bare sub/email token) tells us nothing to fix.
        # Also when the token carries NO tenant: a first provision whose stamp
        # failed otherwise left that account's tokens without a tenant for
        # good, and every tenant-scoped write failed until it was stamped.
        if (token_tenant_id, token_role) != (existing.tenant_id, existing.role):
            try:
                supabase_admin.update_app_metadata(existing.id, existing.tenant_id, existing.role)
            except Exception as exc:  # noqa: BLE001 — sign-in must not depend on the repair
                logger.warning(
                    "Could not repair app_metadata for user %s (%s); tenant-scoped writes "
                    "will fail until it is stamped", existing.id, type(exc).__name__,
                )
        return existing

    # Invite-only deployments: an unknown sign-up must not be handed a brand
    # new tenant with itself as Admin. Admin-created users already have a row
    # (POST /users), so they took the `existing` branch above.
    if not get_settings().ALLOW_PUBLIC_SIGNUP:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sign-up is by invitation only. Ask your administrator to create your account.",
        )

    full_name = f"{payload.first_name} {payload.last_name}".strip()
    if payload.account_type == "individual":
        if not payload.adult_confirmed:
            # Under-18 learners need the age-status and guardian-consent
            # controls (Privacy spec §9, PRD "Minor learners") before any data
            # is collected; until those exist, individual sign-up is adults only.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Individual accounts are currently for adults only. Please confirm you are 18 or older.",
            )
        # A private workspace of one: same tenant isolation as a company, but
        # its only user learns rather than administers.
        tenant_name = f"{full_name or email.split('@')[0]} (personal)"
        role = "Learner"
    else:
        tenant_name = payload.company_name or ""
        role = "Admin"

    tenant = Tenant(name=tenant_name)
    db.add(tenant)
    await db.flush()

    user = User(
        id=user_id,
        tenant_id=tenant.id,
        email=email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        full_name=full_name,
        role=role,
        is_active=True,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        # A users row already holds this email under a DIFFERENT id — the
        # lookup above is by auth id, but the uniqueness constraint is on
        # email. This is what a re-registration looks like: the Supabase auth
        # user behind the original row was deleted, signing up again minted a
        # fresh auth id, and the id lookup can no longer find the row that
        # still owns the address.
        #
        # Deliberately NOT auto-adopting that row. Claiming it would hand the
        # new sign-up whatever tenant and data the old one had, on the
        # strength of a matching email — an account-linking policy, and one
        # that cuts straight across the tenant isolation this service exists
        # to enforce. Re-linking is an administrative act with a human behind
        # it, so this reports the conflict and stops.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An account already exists for this email address under a "
                "different sign-in identity. An administrator needs to re-link "
                "or remove the existing profile before this address can be "
                "registered again."
            ),
        ) from exc
    await db.refresh(user)
    _sync_app_metadata_best_effort(user.id, user.tenant_id, user.role)
    return user


async def set_user_active(db: AsyncSession, user_id: str, tenant_id: str, is_active: bool) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    return user


async def reset_user_mfa(db: AsyncSession, user_id: str, tenant_id: str, *, actor_id: str) -> int | None:
    """Remove every MFA factor of a tenant user (lost authenticator) and end
    their sessions, so the next sign-in starts fresh. Returns the number of
    factors removed, or None when the user is not in this tenant."""
    result = await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if user.id == actor_id:
        raise AccountChangeError("You cannot reset your own two-step verification. Ask another administrator.")
    factors = supabase_admin.list_mfa_factors(user.id)
    for factor in factors:
        supabase_admin.delete_mfa_factor(user.id, factor["id"])
    try:
        supabase_admin.revoke_all_sessions(user.id)
    except Exception as exc:  # noqa: BLE001 — factors are already gone; sessions expire on their own
        log.warning("Session revocation after MFA reset failed for %s (%s)", user.id, type(exc).__name__)
    return len(factors)


class AccountChangeError(Exception):
    """A role change the governance rules refuse (self-change, last Admin)."""


async def set_user_role(
    db: AsyncSession, user_id: str, tenant_id: str, role: str, *, actor_id: str,
) -> tuple[User, str] | None:
    """Change a tenant user's role. Returns (user, previous_role), or None when
    the user is not in this tenant. Refuses an Admin changing their own role
    (separation of duties — and the classic way to lock a tenant out) and any
    change that would leave the tenant with no active Admin."""
    result = await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if user.id == actor_id:
        raise AccountChangeError("You cannot change your own role. Ask another administrator.")
    previous = user.role
    if previous == "Admin" and role != "Admin":
        admins = await db.execute(
            select(User.id).where(
                User.tenant_id == tenant_id, User.role == "Admin", User.is_active.is_(True), User.id != user.id,
            )
        )
        if admins.first() is None:
            raise AccountChangeError("This is the tenant's last active administrator; assign another Admin first.")
    user.role = role
    await db.commit()
    await db.refresh(user)
    # Tokens carry role in app_metadata; the users row stays the authority for
    # every permission check, so a failed stamp only delays the claim refresh.
    _sync_app_metadata_best_effort(user.id, tenant_id, role)
    return user, previous


async def update_own_profile(
    db: AsyncSession, user_id: str, first_name: str | None, last_name: str | None,
) -> User | None:
    """Self-service edit of the user's own profile row. Scope stays on the
    caller's row — there is no tenant_id parameter here, so PATCH /auth/me
    can never touch another user's record. A None field means "not in this
    request": omitted fields are preserved, and full_name is rebuilt from
    the existing values plus whatever was actually provided — a partial
    PATCH must never blank out a field the client didn't send."""
    existing = await get_user_by_id(db, user_id)
    if existing is None:
        return None
    if first_name is not None:
        existing.first_name = first_name
    if last_name is not None:
        existing.last_name = last_name
    existing.full_name = f"{existing.first_name} {existing.last_name}".strip()
    await db.commit()
    await db.refresh(existing)
    return existing
