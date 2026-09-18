from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.supabase_auth import verify_token
from app.domains.identity.models import User
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

    # Re-scope RLS to the tenant this user actually belongs to.
    #
    # get_db seeds app.tenant_id from the JWT's app_metadata, because it runs
    # before any DB lookup is possible (see _identity_from_request). But that
    # claim is a COPY of users.tenant_id taken when the token was minted, and
    # the two drift: re-provisioning mints a fresh tenant into app_metadata
    # while the users row keeps the original, and every token already in a
    # browser keeps the stale value until its holder signs out.
    #
    # Drift breaks writes, not reads. Rows are written with
    # current_user.tenant_id (this row), while the RLS WITH CHECK compares
    # against app.tenant_id (the claim) — so every INSERT into a tenant-scoped
    # table fails with "new row violates row-level security policy" while
    # SELECTs keep working, because the users policy keys off app.user_id,
    # which never drifts.
    #
    # This row is the authority: it is server-written, carries the foreign
    # keys the rest of the schema hangs off, and owns the tenant's existing
    # data. Overriding the claim with it narrows nothing — identity still
    # comes from the verified token's `sub` (app.user_id, set by get_db and
    # deliberately untouched here); this only corrects WHICH tenant that
    # already-authenticated user is scoped to, from the server's own record
    # rather than from a cached claim.
    if not get_settings().is_sqlite:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
            {"tenant_id": user.tenant_id or ""},
        )

    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user
