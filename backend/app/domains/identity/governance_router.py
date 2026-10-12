"""REST API for elevated-access governance (identity/governance.py).

  POST /auth/impersonation                       — Admin starts read-only "view as"
  GET  /auth/impersonation/active                — the caller's live session, if any
  POST /auth/impersonation/{id}/end              — end it
  GET  /break-glass/permissions                  — what may be requested
  GET  /break-glass                              — Admin: tenant grants; others: own
  POST /break-glass                              — request emergency access
  POST /break-glass/{id}/approve|reject|revoke|review
  GET  /service-accounts                         — Admin
  POST /service-accounts                         — Admin
  POST /service-accounts/{id}/keys               — Admin; returns the key once
  POST /service-accounts/{id}/keys/{key_id}/revoke
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity import governance
from app.domains.identity.models import BreakGlassGrant, ImpersonationSession, User
from app.domains.identity.permissions import ALL_PERMISSIONS
from app.domains.identity.rbac import get_current_user, require_admin
from app.domains.identity.schemas import (
    BreakGlassGrantPublic,
    BreakGlassRequest,
    BreakGlassReviewRequest,
    ImpersonationSessionPublic,
    ImpersonationStartRequest,
    IssuedServiceAccountKey,
    ServiceAccountCreateRequest,
    ServiceAccountKeyCreateRequest,
    ServiceAccountKeyPublic,
    ServiceAccountPublic,
)

router = APIRouter(tags=["identity-governance"])


def _http(exc: governance.GovernanceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _name(db: AsyncSession, user_id: str) -> str:
    user = await db.get(User, user_id)
    return (user.full_name or user.email) if user else "Unknown user"


async def _session_public(db: AsyncSession, session: ImpersonationSession) -> ImpersonationSessionPublic:
    target = await db.get(User, session.target_user_id)
    return ImpersonationSessionPublic(
        id=session.id,
        target_user_id=session.target_user_id,
        target_name=(target.full_name or target.email) if target else "Unknown user",
        target_email=target.email if target else "",
        target_role=target.role if target else "",
        reason=session.reason,
        started_at=session.started_at,
        expires_at=session.expires_at,
        ended_at=session.ended_at,
    )


async def _grant_public(db: AsyncSession, grant: BreakGlassGrant) -> BreakGlassGrantPublic:
    return BreakGlassGrantPublic(
        id=grant.id,
        user_id=grant.user_id,
        user_name=await _name(db, grant.user_id),
        permissions=list(grant.permissions),
        reason=grant.reason,
        duration_minutes=grant.duration_minutes,
        status=grant.status,
        requested_at=grant.requested_at,
        approved_by=grant.approved_by,
        activated_at=grant.activated_at,
        expires_at=grant.expires_at,
        ended_at=grant.ended_at,
        reviewed_by=grant.reviewed_by,
        reviewed_at=grant.reviewed_at,
        review_notes=grant.review_notes,
        needs_review=grant.status in {"expired", "revoked"} and grant.reviewed_at is None,
    )


# ── Impersonation ────────────────────────────────────────────────────────────

@router.post("/auth/impersonation", response_model=ImpersonationSessionPublic)
async def post_impersonation(
    payload: ImpersonationStartRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ImpersonationSessionPublic:
    try:
        session = await governance.start_impersonation(db, admin, payload.target_user_id, payload.reason, payload.minutes)
    except governance.GovernanceError as exc:
        raise _http(exc) from exc
    return await _session_public(db, session)


@router.get("/auth/impersonation/active", response_model=ImpersonationSessionPublic | None)
async def get_active_impersonation(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImpersonationSessionPublic | None:
    if current_user.impersonated_by or current_user.role != "Admin":
        return None
    session = await governance.active_impersonation(db, current_user)
    return await _session_public(db, session) if session else None


@router.post("/auth/impersonation/{session_id}/end", response_model=ImpersonationSessionPublic)
async def post_end_impersonation(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImpersonationSessionPublic:
    try:
        session = await governance.end_impersonation(db, current_user, session_id)
    except governance.GovernanceError as exc:
        raise _http(exc) from exc
    return await _session_public(db, session)


# ── Break-glass ──────────────────────────────────────────────────────────────

@router.get("/break-glass/permissions", response_model=list[str])
async def get_break_glass_permissions(_: User = Depends(get_current_user)) -> list[str]:
    return sorted(ALL_PERMISSIONS)


@router.get("/break-glass", response_model=list[BreakGlassGrantPublic])
async def get_break_glass(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BreakGlassGrantPublic]:
    return [await _grant_public(db, g) for g in await governance.list_break_glass(db, current_user)]


@router.post("/break-glass", response_model=BreakGlassGrantPublic)
async def post_break_glass(
    payload: BreakGlassRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BreakGlassGrantPublic:
    try:
        grant = await governance.request_break_glass(
            db, current_user, payload.permissions, payload.reason, payload.duration_minutes,
        )
    except governance.GovernanceError as exc:
        raise _http(exc) from exc
    return await _grant_public(db, grant)


@router.post("/break-glass/{grant_id}/approve", response_model=BreakGlassGrantPublic)
async def post_break_glass_approve(
    grant_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin),
) -> BreakGlassGrantPublic:
    try:
        return await _grant_public(db, await governance.approve_break_glass(db, admin, grant_id))
    except governance.GovernanceError as exc:
        raise _http(exc) from exc


@router.post("/break-glass/{grant_id}/reject", response_model=BreakGlassGrantPublic)
async def post_break_glass_reject(
    grant_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin),
) -> BreakGlassGrantPublic:
    try:
        return await _grant_public(db, await governance.reject_break_glass(db, admin, grant_id))
    except governance.GovernanceError as exc:
        raise _http(exc) from exc


@router.post("/break-glass/{grant_id}/revoke", response_model=BreakGlassGrantPublic)
async def post_break_glass_revoke(
    grant_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> BreakGlassGrantPublic:
    try:
        return await _grant_public(db, await governance.revoke_break_glass(db, current_user, grant_id))
    except governance.GovernanceError as exc:
        raise _http(exc) from exc


@router.post("/break-glass/{grant_id}/review", response_model=BreakGlassGrantPublic)
async def post_break_glass_review(
    grant_id: str,
    payload: BreakGlassReviewRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> BreakGlassGrantPublic:
    try:
        return await _grant_public(db, await governance.review_break_glass(db, admin, grant_id, payload.notes))
    except governance.GovernanceError as exc:
        raise _http(exc) from exc


# ── Service accounts ─────────────────────────────────────────────────────────

@router.get("/service-accounts", response_model=list[ServiceAccountPublic])
async def get_service_accounts(
    db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin),
) -> list[ServiceAccountPublic]:
    rows = await governance.list_service_accounts(db, admin)
    return [
        ServiceAccountPublic(
            id=account.id,
            name=account.name,
            description=account.description,
            role=user.role if user else "",
            owner_user_id=account.owner_user_id,
            owner_name=await _name(db, account.owner_user_id),
            is_active=bool(user and user.is_active),
            created_at=account.created_at,
            keys=[ServiceAccountKeyPublic.model_validate(k) for k in keys],
        )
        for account, user, keys in rows
    ]


@router.post("/service-accounts", response_model=ServiceAccountPublic)
async def post_service_account(
    payload: ServiceAccountCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ServiceAccountPublic:
    try:
        account = await governance.create_service_account(
            db, admin, name=payload.name, description=payload.description,
            role=payload.role, owner_user_id=payload.owner_user_id,
        )
    except governance.GovernanceError as exc:
        raise _http(exc) from exc
    return ServiceAccountPublic(
        id=account.id, name=account.name, description=account.description, role=payload.role,
        owner_user_id=account.owner_user_id, owner_name=await _name(db, account.owner_user_id),
        is_active=True, created_at=account.created_at, keys=[],
    )


@router.post("/service-accounts/{account_id}/keys", response_model=IssuedServiceAccountKey)
async def post_service_account_key(
    account_id: str,
    payload: ServiceAccountKeyCreateRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> IssuedServiceAccountKey:
    try:
        key, raw_key = await governance.issue_service_account_key(db, admin, account_id, payload.expires_in_days)
    except governance.GovernanceError as exc:
        raise _http(exc) from exc
    # The plaintext key must not be cached anywhere along the way.
    response.headers["Cache-Control"] = "no-store"
    return IssuedServiceAccountKey(key=raw_key, key_info=ServiceAccountKeyPublic.model_validate(key))


@router.post("/service-accounts/{account_id}/keys/{key_id}/revoke", response_model=ServiceAccountKeyPublic)
async def post_revoke_service_account_key(
    account_id: str,
    key_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ServiceAccountKeyPublic:
    try:
        key = await governance.revoke_service_account_key(db, admin, account_id, key_id)
    except governance.GovernanceError as exc:
        raise _http(exc) from exc
    return ServiceAccountKeyPublic.model_validate(key)
