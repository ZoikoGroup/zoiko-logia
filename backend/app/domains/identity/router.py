import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import supabase_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.supabase_auth import verify_token
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User
from app.domains.identity.permissions import STEP_UP_PERMISSIONS, permissions_for_role
from app.domains.identity.rbac import get_current_user, oauth2_scheme, require_admin
from app.domains.identity.schemas import (
    MfaStatus,
    ProfileUpdateRequest,
    ProvisionRequest,
    RolePublic,
    UserActiveUpdateRequest,
    UserCreatedResponse,
    UserCreateRequest,
    UserListItem,
    UserPublic,
    UserRoleUpdateRequest,
)
from app.domains.identity.service import (
    AccountChangeError,
    create_user,
    get_user_by_id,
    list_roles,
    list_users,
    provision_profile,
    reset_user_mfa,
    set_user_active,
    set_user_role,
    update_own_profile,
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
    yet — exactly the case on someone's very first call here).

    Provisioning is bound to the token's own subject: the Tenant + User it
    creates are keyed by claims.sub, so even a logged-in user who somehow
    calls this with someone else's token can only ever create a brand-new
    tenant for that token's owner — they cannot claim or join an existing
    tenant, because the request carries no tenant reference to target."""
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    claims = verify_token(token)
    if claims is None or claims.email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    was_first_provision = (await get_user_by_id(db, claims.sub)) is None
    try:
        user = await provision_profile(
            db, claims.sub, claims.email, payload,
            token_tenant_id=claims.tenant_id, token_role=claims.role,
        )
    except supabase_admin.SupabaseNotConfiguredError:
        # Defensive: provisioning commits the local profile row before the
        # (best-effort) app_metadata sync, so this should no longer happen —
        # kept so a future regression 503s loudly instead of half-creating.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase admin API not configured — set SUPABASE_URL / "
            "SUPABASE_SERVICE_ROLE_KEY in backend/.env to enable "
            "provisioning.",
        )
    # Re-provisioning runs on every login (the frontend calls it after each
    # sign-in), so only the call that actually created the account earns an
    # audit event — a no-op re-provision must not pollute the chain.
    if was_first_provision:
        await record_event_async(
            db,
            tenant_id=user.tenant_id,
            event_name="auth.provisioned",
            emitting_service="identity",
            actor_id=user.id,
            subject_type="user_account",
            subject_id=user.id,
            payload={"first_time": True, "company_name": payload.company_name},
        )
    return UserPublic.model_validate(user)


@auth_router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(current_user)


@auth_router.patch("/me", response_model=UserPublic)
async def patch_me(
    payload: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserPublic:
    updated = await update_own_profile(db, current_user.id, payload.first_name, payload.last_name)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await record_event_async(
        db,
        tenant_id=updated.tenant_id,
        event_name="auth.profile_updated",
        emitting_service="identity",
        actor_id=updated.id,
        subject_type="user_account",
        subject_id=updated.id,
        payload={
            "fields_changed": [
                field
                for field, value in (("first_name", payload.first_name), ("last_name", payload.last_name))
                if value
            ]
        },
    )
    return UserPublic.model_validate(updated)


@auth_router.post("/sign-out-all-sessions", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out_all_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Revoke every session the user holds, server-side, via the Supabase
    Admin API. Works even for a stolen/lost session on a device that never
    signs out on its own.

    Fails closed when the Admin API is unconfigured (503, like provision):
    a 204 that never revoked anything would be a false success, and the
    auth.sessions_revoked audit event is written only once revocation is
    actually confirmed."""
    try:
        revoked = supabase_admin.revoke_all_sessions(current_user.id)
    except supabase_admin.SupabaseNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase admin API not configured — set SUPABASE_URL / "
            "SUPABASE_SERVICE_ROLE_KEY in backend/.env to revoke sessions.",
        )
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Supabase did not confirm session revocation (expected 204).",
        )
    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="auth.sessions_revoked",
        emitting_service="identity",
        actor_id=current_user.id,
        subject_type="user_account",
        subject_id=current_user.id,
        payload={},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.get("/mfa/status", response_model=MfaStatus)
async def mfa_status(current_user: User = Depends(get_current_user)) -> MfaStatus:
    """The MFA policy as it applies to the caller. Enrolment and challenge
    run entirely through Supabase Auth (TOTP factors) in the browser; the
    backend only enforces the resulting token assurance level."""
    return MfaStatus(
        required_for_privileged=get_settings().MFA_REQUIRED_FOR_PRIVILEGED,
        privileged_role=current_user.role == "Admin"
        or bool(permissions_for_role(current_user.role) & STEP_UP_PERMISSIONS),
        current_aal=current_user.auth_aal,
    )


@auth_router.post("/mfa/enrolled", status_code=status.HTTP_204_NO_CONTENT)
async def mfa_enrolled(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Audit hook the frontend calls right after a TOTP factor is verified.
    Trusts only the token: the session must already be aal2 (Supabase raises
    it on successful verification), so a client cannot log an enrolment that
    never happened."""
    if current_user.auth_aal != "aal2":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This session has not completed an MFA challenge.",
        )
    await record_event_async(
        db,
        tenant_id=current_user.tenant_id,
        event_name="auth.mfa_enrolled",
        emitting_service="identity",
        actor_id=current_user.id,
        subject_type="user_account",
        subject_id=current_user.id,
        payload={"factor_type": "totp"},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@users_router.post("/users", response_model=UserCreatedResponse)
async def post_user(
    payload: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserCreatedResponse:
    invited = not payload.password
    try:
        user = await create_user(db, admin.tenant_id, payload)
    except supabase_admin.SupabaseNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase admin API not configured — set SUPABASE_URL / "
            "SUPABASE_SERVICE_ROLE_KEY in backend/.env to create users.",
        )
    except httpx.HTTPStatusError as exc:
        # Supabase refuses e.g. an address that already has an account.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if exc.response.status_code in (400, 409, 422) else status.HTTP_502_BAD_GATEWAY,
            detail="Supabase could not create this account — the email may already be registered.",
        ) from exc
    await record_event_async(
        db,
        tenant_id=admin.tenant_id,
        event_name="auth.user_invited" if invited else "auth.user_created",
        emitting_service="identity",
        actor_id=admin.id,
        subject_type="user_account",
        subject_id=user.id,
        payload={"email": payload.email, "role": payload.role},
    )
    return UserCreatedResponse(**UserListItem.model_validate(user).model_dump(), invited=invited)


@users_router.post("/users/{user_id}/mfa/reset", status_code=status.HTTP_204_NO_CONTENT)
async def post_user_mfa_reset(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Response:
    """For a user who lost their authenticator: removes their factors and ends
    their sessions. They sign in with their password and can enrol again."""
    try:
        removed = await reset_user_mfa(db, user_id, admin.tenant_id, actor_id=admin.id)
    except AccountChangeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except supabase_admin.SupabaseNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase admin API not configured — MFA cannot be reset.",
        )
    if removed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await record_event_async(
        db,
        tenant_id=admin.tenant_id,
        event_name="admin_mfa_reset",
        emitting_service="identity",
        actor_id=admin.id,
        subject_type="user_account",
        subject_id=user_id,
        payload={"factors_removed": removed},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@users_router.patch("/users/{user_id}", response_model=UserListItem)
async def patch_user(
    user_id: str,
    payload: UserActiveUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserListItem:
    if user_id == admin.id and not payload.is_active:
        # Self-deactivation is how a single-Admin tenant locks itself out.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot deactivate your own account. Ask another administrator.",
        )
    user = await set_user_active(db, user_id, admin.tenant_id, payload.is_active)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await record_event_async(
        db,
        tenant_id=admin.tenant_id,
        event_name="auth.user_activation_changed",
        emitting_service="identity",
        actor_id=admin.id,
        subject_type="user_account",
        subject_id=user.id,
        payload={"is_active": user.is_active},
    )
    return UserListItem.model_validate(user)


@users_router.patch("/users/{user_id}/role", response_model=UserListItem)
async def patch_user_role(
    user_id: str,
    payload: UserRoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserListItem:
    try:
        changed = await set_user_role(db, user_id, admin.tenant_id, payload.role, actor_id=admin.id)
    except AccountChangeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if changed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user, previous_role = changed
    await record_event_async(
        db,
        tenant_id=admin.tenant_id,
        event_name="admin_permission_changed",
        emitting_service="identity",
        actor_id=admin.id,
        subject_type="user_account",
        subject_id=user.id,
        payload={"previous_role": previous_role, "new_role": user.role},
    )
    return UserListItem.model_validate(user)