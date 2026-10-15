# Endpoints backing the Administration pages. The Operations pages live in
# app/domains/operations/router.py.
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.admin_governance import access, elevated, overview, releases, settings_console, tenant_policy
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import ServiceAccount, User
from app.domains.identity.rbac import enforce_step_up, get_current_user, require_admin

router = APIRouter(tags=["Administration"])

RELEASE_VIEWERS = {"Admin", "AI Governance Lead", "Governance Ops Lead", "Risk Admin", "System Auditor"}
RELEASE_EDITORS = {"Admin", "Governance Ops Lead", "Risk Admin"}


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 422, detail=str(exc))


# ── Roles & Permissions ────────────────────────────────────────────────────

@router.get("/admin/roles-matrix")
async def get_roles_matrix(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await overview.roles_matrix(db, admin.tenant_id)


@router.get("/admin/roles-console")
async def get_roles_console(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await access.roles_view(db, admin.tenant_id)


class SimulateBody(BaseModel):
    role: str
    permission: str
    session_mfa: bool = False


@router.post("/admin/roles/simulate")
async def simulate_access(body: SimulateBody, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    mfa = await tenant_policy.effective(db, admin.tenant_id, "mfa_required_privileged")
    return access.simulate(body.role, body.permission, mfa_required=bool(mfa), session_mfa=body.session_mfa)


@router.get("/admin/activity")
async def get_activity(subject_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> list[dict]:
    return await access.activity(db, admin.tenant_id, subject_id)


# ── Users & Teams ──────────────────────────────────────────────────────────

@router.get("/admin/users-overview")
async def get_users_overview(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await access.users_view(db, admin.tenant_id)


class TeamBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=300)
    owner_user_id: str | None = None


class TeamPatch(BaseModel):
    owner_user_id: str | None = None
    add: list[str] = Field(default_factory=list, max_length=100)
    remove: list[str] = Field(default_factory=list, max_length=100)


@router.post("/admin/teams", status_code=201)
async def create_team(body: TeamBody, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    try:
        team = await access.create_team(db, admin, body.name, body.description, body.owner_user_id)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": team.id, "name": team.name}


@router.patch("/admin/teams/{team_id}")
async def update_team(team_id: str, body: TeamPatch, db: AsyncSession = Depends(get_db),
                      admin: User = Depends(require_admin)) -> dict:
    try:
        team = await access.update_team(db, admin, team_id, owner_id=body.owner_user_id, add=body.add, remove=body.remove)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": team.id, "name": team.name}


class ReviewBody(BaseModel):
    user_id: str
    decision: Literal["certified", "role_changed", "deactivated"]
    note: str = Field(default="", max_length=1000)


@router.post("/admin/access-reviews", status_code=201)
async def record_access_review(body: ReviewBody, db: AsyncSession = Depends(get_db),
                               admin: User = Depends(require_admin)) -> dict:
    try:
        review = await access.record_review(db, admin, body.user_id, body.decision, body.note)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": review.id, "decision": review.decision}


# ── Tenant Settings ────────────────────────────────────────────────────────

@router.get("/admin/tenant-settings")
async def get_tenant_settings(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await settings_console.build(db, admin)


class ChangeBody(BaseModel):
    key: str
    value: bool | int
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/admin/settings/changes", status_code=201)
async def request_setting_change(body: ChangeBody, db: AsyncSession = Depends(get_db),
                                 admin: User = Depends(require_admin)) -> dict:
    try:
        req = await tenant_policy.request_change(db, admin, body.key, body.value, body.reason)
    except tenant_policy.PolicyError as exc:
        if str(exc).startswith("Prohibited override") or "not tenant-adjustable" in str(exc):
            # Counted on the Tenant Settings page: attempts to loosen a safeguard.
            await record_event_async(db, tenant_id=admin.tenant_id, event_name="tenant_setting_override_prohibited",
                                     emitting_service="admin_governance", actor_id=admin.id,
                                     subject_type="tenant_setting", subject_id=body.key,
                                     payload={"to": body.value, "reason": str(exc)})
        raise _refused(exc) from exc
    return {"id": req.id, "ref": req.ref, "status": req.status}


class DecisionBody(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=1000)


@router.post("/admin/settings/changes/{request_id}/decision")
async def decide_setting_change(request_id: str, body: DecisionBody, db: AsyncSession = Depends(get_db),
                                admin: User = Depends(require_admin)) -> dict:
    try:
        req = await tenant_policy.decide(db, admin, request_id, body.approve, body.note)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": req.id, "ref": req.ref, "status": req.status}


@router.get("/admin/usage")
async def get_usage(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await overview.usage(db, admin.tenant_id)


# ── Service Accounts & Entities ────────────────────────────────────────────

@router.get("/admin/service-accounts-overview")
async def get_service_accounts_overview(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await elevated.service_accounts(db, admin.tenant_id)


class OwnerBody(BaseModel):
    owner_user_id: str


@router.put("/admin/service-accounts/{account_id}/owner")
async def transfer_service_account(account_id: str, body: OwnerBody, db: AsyncSession = Depends(get_db),
                                   admin: User = Depends(require_admin)) -> dict:
    account = (await db.execute(select(ServiceAccount).where(
        ServiceAccount.id == account_id, ServiceAccount.tenant_id == admin.tenant_id))).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Service account not found")
    owner = (await db.execute(select(User).where(User.id == body.owner_user_id, User.tenant_id == admin.tenant_id,
                                                 User.is_active.is_(True)))).scalar_one_or_none()
    service = (await db.execute(select(ServiceAccount.id).where(ServiceAccount.id == body.owner_user_id))).first()
    if owner is None or service is not None:
        raise HTTPException(status_code=422, detail="The owner must be an active person in this workspace")
    previous = account.owner_user_id
    account.owner_user_id = owner.id
    await db.flush()
    await record_event_async(db, tenant_id=admin.tenant_id, event_name="service_account_owner_changed",
                             emitting_service="admin_governance", actor_id=admin.id, subject_type="service_account",
                             subject_id=account.id, payload={"from": previous, "to": owner.id})
    return {"id": account.id, "ownerId": owner.id}


@router.get("/admin/entities")
async def get_entities(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await elevated.entities(db, admin.tenant_id)


# ── Release Gates ──────────────────────────────────────────────────────────

async def require_release_viewer(user: User = Depends(get_current_user)) -> User:
    if user.role not in RELEASE_VIEWERS:
        raise HTTPException(status_code=403, detail="Release gates are not available for this role")
    return user


async def require_release_editor(user: User = Depends(require_release_viewer), db: AsyncSession = Depends(get_db)) -> User:
    if user.role not in RELEASE_EDITORS:
        raise HTTPException(status_code=403, detail="Your role can view releases but not change them")
    await enforce_step_up(db, user, "evaluation.manage")
    return user


@router.get("/admin/releases")
async def get_releases(db: AsyncSession = Depends(get_db), user: User = Depends(require_release_viewer)) -> dict:
    return await releases.register(db, user)


class ReleaseBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    component: str = Field(min_length=2, max_length=60)
    change_ref: str = Field(default="", max_length=60)
    description: str = Field(default="", max_length=2000)
    risk: Literal["critical", "high", "medium", "low"] = "medium"
    owner_user_id: str | None = None


@router.post("/admin/releases", status_code=201)
async def create_release(body: ReleaseBody, db: AsyncSession = Depends(get_db),
                         user: User = Depends(require_release_editor)) -> dict:
    try:
        r = await releases.create(db, user, body.model_dump())
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": r.id, "ref": r.ref}


class GateBody(BaseModel):
    status: Literal["pass", "open", "fail"]
    note: str = Field(default="", max_length=1000)


@router.put("/admin/releases/{release_id}/gates/{gate}")
async def set_release_gate(release_id: str, gate: str, body: GateBody, db: AsyncSession = Depends(get_db),
                           user: User = Depends(require_release_editor)) -> dict:
    try:
        r = await releases.set_gate(db, user, release_id, gate, body.status, body.note)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": r.id, "ref": r.ref}


class ReleaseAction(BaseModel):
    action: Literal["approve", "deploy", "rollback"]
    note: str = Field(default="", max_length=1000)


@router.post("/admin/releases/{release_id}/actions")
async def act_on_release(release_id: str, body: ReleaseAction, db: AsyncSession = Depends(get_db),
                         user: User = Depends(require_release_editor)) -> dict:
    try:
        live = await releases.live_evidence(db, user)
        r = await releases.transition(db, user, live, release_id, body.action, body.note)
    except (ValueError, LookupError) as exc:
        raise _refused(exc) from exc
    return {"id": r.id, "ref": r.ref, "status": r.status}
