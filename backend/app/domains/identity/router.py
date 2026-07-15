from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.supabase_auth import verify_token
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user, oauth2_scheme, require_admin
from app.domains.identity.schemas import (
    ProvisionRequest,
    RolePublic,
    UserActiveUpdateRequest,
    UserCreateRequest,
    UserListItem,
    UserPublic,
)
from app.domains.identity.service import (
    create_user,
    list_roles,
    list_users,
    provision_profile,
    set_user_active,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(tags=["identity"])


@auth_router.post("/provision", response_model=UserPublic)
async def provision(
    payload: ProvisionRequest,
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(oauth2_scheme),
) -> UserPublic:
    """Called by the frontend right after Supabase sign-up/first OAuth
    login. Verifies the token itself (rather than depending on
    get_current_user, which 401s when the local profile doesn't exist
    yet — exactly the case on someone's very first call here)."""
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    claims = verify_token(token)
    if claims is None or claims.email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    user = await provision_profile(db, claims.sub, claims.email, payload)
    return UserPublic.model_validate(user)


@auth_router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(current_user)


@users_router.get("/roles", response_model=list[RolePublic])
async def get_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RolePublic]:
    roles = await list_roles(db)
    return [RolePublic.model_validate(r) for r in roles]


@users_router.get("/users", response_model=list[UserListItem])
async def get_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[UserListItem]:
    users = await list_users(db, admin.tenant_id)
    return [UserListItem.model_validate(u) for u in users]


@users_router.post("/users", response_model=UserListItem)
async def post_user(
    payload: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserListItem:
    user = await create_user(db, admin.tenant_id, payload)
    return UserListItem.model_validate(user)


@users_router.patch("/users/{user_id}", response_model=UserListItem)
async def patch_user(
    user_id: str,
    payload: UserActiveUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserListItem:
    user = await set_user_active(db, user_id, admin.tenant_id, payload.is_active)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserListItem.model_validate(user)
