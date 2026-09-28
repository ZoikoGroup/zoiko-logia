from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import supabase_admin
from app.domains.identity.models import Role, Tenant, User
from app.domains.identity.schemas import ProvisionRequest, UserCreateRequest
import logging

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


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def list_roles(db: AsyncSession) -> list[Role]:
    result = await db.execute(select(Role))
    return list(result.scalars().all())


async def list_users(db: AsyncSession, tenant_id: str) -> list[User]:
    result = await db.execute(select(User).where(User.tenant_id == tenant_id))
    return list(result.scalars().all())


async def create_user(db: AsyncSession, tenant_id: str, payload: UserCreateRequest) -> User:
    """Admin-created teammate: creates the Supabase auth user first (service
    role, auto-confirmed — this isn't the public sign-up flow, so there's
    no email-verification step to wait on), then the local profile row
    keyed by the id Supabase assigned."""
    auth_user = supabase_admin.create_user(payload.email, payload.password, email_confirm=True)
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


async def provision_profile(db: AsyncSession, user_id: str, email: str, payload: ProvisionRequest) -> User:
    """Idempotent upsert called by the frontend right after a Supabase
    sign-up/first OAuth login. First call creates the Tenant (from
    company_name) + User row and stamps tenant_id/role into the Supabase
    user's app_metadata. Later calls just return the existing row —
    provisioning must never create a second Tenant/User for the same
    Supabase auth user."""
    existing = await get_user_by_id(db, user_id)
    if existing is not None:
        return existing

    tenant = Tenant(name=payload.company_name or "")
    db.add(tenant)
    await db.flush()

    user = User(
        id=user_id,
        tenant_id=tenant.id,
        email=email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        full_name=f"{payload.first_name} {payload.last_name}".strip(),
        role="Admin",
        is_active=True,
    )
    db.add(user)
    await db.commit()
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
