import logging

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db, session_is_sqlite
from app.core.supabase_auth import verify_token
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity import governance
from app.domains.identity.models import User
from app.domains.identity.permissions import STEP_UP_PERMISSIONS, user_has_permission
from app.domains.identity.service import get_user_by_id

log = logging.getLogger("uvicorn.error")

# Error detail the frontend keys on to send the user to MFA enrolment instead
# of showing a generic "forbidden".
MFA_REQUIRED_DETAIL = (
    "Multi-factor authentication is required for this action. Set it up under "
    "Account security, then sign in again."
)

# tokenUrl is cosmetic here (Supabase issues the tokens now, not this
# backend) — kept only so Swagger's "Authorize" button still works.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/provision", auto_error=False)


async def _set_rls_identity(db: AsyncSession, *, tenant_id: str, user_id: str | None = None) -> None:
    """Point this request's RLS context at the resolved identity, committed so
    a later rollback cannot undo it (see get_db in app/core/database.py)."""
    if session_is_sqlite(db):
        return
    await db.execute(text("SELECT set_config('app.tenant_id', :tenant_id, false)"), {"tenant_id": tenant_id or ""})
    if user_id is not None:
        await db.execute(text("SELECT set_config('app.user_id', :user_id, false)"), {"user_id": user_id})
    await db.commit()


async def _user_from_api_key(db: AsyncSession, raw_key: str, credentials_error: HTTPException) -> User:
    """Service-account authentication. get_db could not seed an RLS identity
    from a non-JWT credential, so it is set here from the key's own row
    before the users row (self-row RLS) is read."""
    key = await governance.resolve_api_key(db, raw_key)
    if key is None:
        raise credentials_error
    await _set_rls_identity(db, tenant_id=key.tenant_id, user_id=key.service_account_id)
    user = await get_user_by_id(db, key.service_account_id)
    if user is None or not user.is_active or user.tenant_id != key.tenant_id:
        raise credentials_error
    await governance.touch_api_key(db, key)
    user.auth_method = "api_key"
    return user


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    impersonation_session: str | None = Header(default=None, alias="X-Impersonation-Session"),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_error
    # Called directly (tests, internal callers) the Header() default object is
    # passed through unchanged; only a real header value counts.
    impersonating = isinstance(impersonation_session, str) and impersonation_session != ""

    if token.startswith(governance.API_KEY_PREFIX):
        if impersonating:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Service accounts cannot impersonate.")
        return await _user_from_api_key(db, token, credentials_error)

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
    user.auth_aal = claims.aal

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
    await _set_rls_identity(db, tenant_id=user.tenant_id)

    if impersonating:
        try:
            target = await governance.resolve_impersonation(db, user, impersonation_session)
        except governance.GovernanceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        # Reads now run as the viewed user, so RLS shows exactly what they see.
        # The impersonation middleware already refused every non-read request.
        await _set_rls_identity(db, tenant_id=target.tenant_id, user_id=target.id)
        target.break_glass_permissions = await governance.active_break_glass_permissions(db, target)
        return target

    user.break_glass_permissions = await governance.active_break_glass_permissions(db, user)
    return user


def require_permission(permission: str):
    """Dependency factory: require the authenticated user's role to carry a
    concrete permission (see identity/permissions.py for the registry). Fails
    closed — a role this registry knows nothing about can do nothing here."""

    async def dependency(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not user_has_permission(current_user, permission):
            await record_access_denied(db, current_user, permission, "missing_permission")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}",
            )
        if permission in STEP_UP_PERMISSIONS:
            await enforce_step_up(db, current_user, permission)
        return current_user

    return dependency


async def require_admin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    if current_user.role != "Admin":
        await record_access_denied(db, current_user, "admin", "missing_role")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    await enforce_step_up(db, current_user, "admin")
    return current_user


async def enforce_step_up(db: AsyncSession, user: User, required: str) -> None:
    """Refuse a privileged action from a session that has not completed MFA,
    when the deployment requires it. The assurance level comes from the
    verified token (get_current_user), never from the request body."""
    if not get_settings().MFA_REQUIRED_FOR_PRIVILEGED:
        return
    if getattr(user, "auth_aal", "aal1") == "aal2":
        return
    # A service account's API key is a non-interactive credential with no
    # session to step up; its scope is bounded instead by a non-Admin role,
    # a named owner, an expiry and revocation (identity/governance.py).
    if getattr(user, "auth_method", "session") == "api_key":
        return
    await record_access_denied(db, user, required, "mfa_required")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MFA_REQUIRED_DETAIL)


async def record_access_denied(db: AsyncSession, user: User, required: str, reason: str) -> None:
    """Write the canonical `access_denied` event (Event Catalog, admin
    security family) for a refused authorization. Best effort: a failed audit
    write is logged but never turns the 403 into a 500 or, worse, an allow."""
    try:
        await record_event_async(
            db,
            tenant_id=user.tenant_id,
            event_name="access_denied",
            emitting_service="identity",
            actor_id=user.id,
            subject_type="user_account",
            subject_id=user.id,
            payload={
                "required": required, "role": user.role, "reason": reason,
                **({"impersonated_by": user.impersonated_by} if getattr(user, "impersonated_by", None) else {}),
            },
        )
    except Exception as exc:  # noqa: BLE001 — the denial itself must still stand
        log.warning("access_denied audit write failed for user %s (%s)", user.id, type(exc).__name__)
