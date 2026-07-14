from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

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

    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user
