"""Platform control plane API (Super Admin). Separate from every tenant
route: access comes from users.platform_role, never from the tenant role, and
each refusal is audited (AUD-01)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user, record_access_denied
from app.domains.platform import directory, service

router = APIRouter(prefix="/platform", tags=["Platform control plane"])


async def require_super_admin(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    """A person (not an API key), acting as themselves (not impersonated),
    holding the platform Super Admin role."""
    reason = None
    if getattr(user, "auth_method", "session") != "session":
        reason = "service_account"
    elif getattr(user, "impersonated_by", None):
        reason = "impersonation"
    elif user.platform_role not in service.PLATFORM_ROLES:
        reason = "missing_platform_role"
    if reason:
        await record_access_denied(db, user, "platform.super_admin", reason)
        raise HTTPException(status_code=403, detail="Platform Super Admin access required")
    return user


@router.get("/command")
async def command(_: User = Depends(require_super_admin)) -> dict:
    # Cross-tenant aggregates need the owner connection; service.py is the
    # boundary that keeps the result to metadata.
    async with AsyncSessionLocal() as db:
        return await service.command_overview(db)


@router.get("/directory")
async def platform_directory(_: User = Depends(require_super_admin)) -> dict:
    # Every company and account across tenants, with sign-in status. The owner
    # connection reads past RLS (and Supabase's auth schema); directory.py
    # keeps it to identity metadata.
    async with AsyncSessionLocal() as db:
        return await directory.directory(db)
