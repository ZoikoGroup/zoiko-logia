from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.supabase_auth import verify_token
from app.domains.identity.models import User
from app.domains.identity.permissions import user_has_permission
from app.domains.identity.service import get_user_by_id

# tokenUrl is cosmetic here (Supabase issues the tokens now, not this
# backend) — kept only so Swagger's "Authorize" button still works.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/provision", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_error

    claims = verify_token(token)
    if claims is None:
        raise credentials_error

    user = await get_user_by_id(db, claims.sub)
    if user is None:
        # Valid Supabase session, but the frontend hasn't called
        # /auth/provision yet to create the local profile row.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not provisioned — sign in again to complete setup",
        )
    if not user.is_active:
        raise credentials_error

    # get_db scoped this session's RLS identity from the token's app_metadata,
    # which is only a cached copy of the tenant: an account whose stamp never
    # landed (e.g. provisioning with a bad service-role key) carried an empty
    # app.tenant_id, so every tenant-isolated write in the request failed —
    # a crashed follow-up calculation, evidence bundles never saved. The
    # verified profile row is the authority; re-scope to it.
    if db.sync_session.get_bind().dialect.name == "postgresql":
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, false)"), {"tenant_id": user.tenant_id}
        )

    return user


def require_permission(permission: str):
    """Dependency factory: require the authenticated user's role to carry a
    concrete permission (see identity/permissions.py for the registry). Fails
    closed — a role this registry knows nothing about can do nothing here."""

    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if not user_has_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}",
            )
        return current_user

    return dependency


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user
