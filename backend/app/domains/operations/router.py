# Endpoints backing the Operations pages: Alerts Center, Provider Register,
# Integrations and Status & Health.
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.command_center.service import build_governance, cached
from app.domains.identity.models import User
from app.domains.identity.rbac import enforce_step_up, get_current_user, require_admin
from app.domains.operations import alerts as alert_service
from app.domains.operations import health, registers
from app.domains.operations import service as operations
from app.domains.operations.models import ServiceOwner
from app.domains.risk_safety.models import EmergencySafetyBlock

router = APIRouter(prefix="/operations", tags=["Operations"])

# Operations pages are for governance roles; never Learners.
OPERATIONS_ROLES = {"Admin", "AI Governance Lead", "Governance Ops Lead", "Risk Admin", "System Auditor"}
# System Auditor reads everything here and changes nothing.
ALERT_RESPONDERS = OPERATIONS_ROLES - {"System Auditor"}
REGISTER_EDITORS = {"Admin", "Governance Ops Lead", "Risk Admin"}


async def require_operations(user: User = Depends(get_current_user)) -> User:
    if user.role not in OPERATIONS_ROLES:
        raise HTTPException(status_code=403, detail="Operations views are not available for this role")
    return user


async def require_responder(user: User = Depends(require_operations)) -> User:
    if user.role not in ALERT_RESPONDERS:
        raise HTTPException(status_code=403, detail="Your role can view alerts but not act on them")
    return user


async def require_register_editor(user: User = Depends(require_operations),
                                  db: AsyncSession = Depends(get_db)) -> User:
    if user.role not in REGISTER_EDITORS:
        raise HTTPException(status_code=403, detail="Your role can view the register but not change it")
    await enforce_step_up(db, user, "model.manage")
    return user


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422 if isinstance(exc, ValueError) else 404, detail=str(exc))


# ── Status & Health ────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_db), user: User = Depends(require_operations)) -> dict:
    return await health.build_status(db, user)


class OwnerBody(BaseModel):
    owner_user_id: str


@router.put("/services/{service_key}/owner")
async def set_service_owner(service_key: str, body: OwnerBody, db: AsyncSession = Depends(get_db),
                            admin: User = Depends(require_admin)) -> dict:
    if service_key not in operations.SERVICE_NAMES and service_key != "audit_ledger":
        raise HTTPException(status_code=404, detail="Unknown service")
    owner = (await db.execute(select(User).where(User.id == body.owner_user_id, User.tenant_id == admin.tenant_id,
                                                 User.is_active.is_(True)))).scalar_one_or_none()
    if owner is None:
        raise HTTPException(status_code=422, detail="Owner must be an active user in this workspace")
    row = (await db.execute(select(ServiceOwner).where(ServiceOwner.tenant_id == admin.tenant_id,
                                                       ServiceOwner.service_key == service_key))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        db.add(ServiceOwner(tenant_id=admin.tenant_id, service_key=service_key, owner_user_id=owner.id,
                            updated_by=admin.id, updated_at=now))
    else:
        row.owner_user_id, row.updated_by, row.updated_at = owner.id, admin.id, now
    await db.flush()
    await record_event_async(
        db, tenant_id=admin.tenant_id, event_name="service_owner_assigned", emitting_service="operations",
        actor_id=admin.id, subject_type="monitored_service", subject_id=service_key, payload={"owner": owner.id})
    return {"serviceKey": service_key, "ownerId": owner.id, "owner": owner.full_name or owner.email}


@router.get("/connections")
async def get_connections(_: User = Depends(require_operations)) -> dict:
    return {
        "modelProviders": operations.model_providers(),
        "dataSources": operations.data_sources(),
        "integrations": operations.integrations(),
    }


# ── Alerts Center ──────────────────────────────────────────────────────────

@router.get("/assignees")
async def get_assignees(db: AsyncSession = Depends(get_db), user: User = Depends(require_operations)) -> list[dict]:
    return await alert_service.assignees(db, user.tenant_id)


@router.get("/alerts")
async def get_alerts(fresh: bool = False, db: AsyncSession = Depends(get_db),
                     user: User = Depends(require_operations)) -> dict:
    """Live conditions (the Governance Dashboard's exceptions — so the two
    pages always agree — and dependencies that are down) synced into alerts."""
    now = datetime.now(timezone.utc)
    view = await cached(
        ("governance", user.tenant_id, user.id, user.role, user.updated_at.isoformat(), "CONNECTED", 30),
        lambda: build_governance(user, now, 30, "CONNECTED"), fresh=fresh,
    )
    conditions = alert_service.governance_conditions(view["exceptions"])
    conditions += await alert_service.health_conditions(db, now)
    await alert_service.sync(db, user.tenant_id, conditions, now)
    naive_now = now.replace(tzinfo=None)
    blocks = (await db.execute(select(func.count()).select_from(EmergencySafetyBlock)
                               .where(EmergencySafetyBlock.expires_at > naive_now))).scalar_one()
    return await alert_service.list_alerts(db, user.tenant_id, safety_blocks=blocks, now=now)


class AlertBody(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    severity: Literal["Critical", "High", "Medium", "Low"]
    category: str = Field(default="Platform operations", max_length=80)
    detail: str = Field(default="", max_length=4000)
    service_key: str | None = None


@router.post("/alerts", status_code=201)
async def raise_alert(body: AlertBody, db: AsyncSession = Depends(get_db),
                      user: User = Depends(require_responder)) -> dict:
    try:
        alert = await alert_service.create_manual(db, user, title=body.title.strip(), severity=body.severity,
                                                  category=body.category.strip(), detail=body.detail.strip(),
                                                  service_key=body.service_key)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return await alert_service.view_one(db, alert)


class AlertAction(BaseModel):
    action: Literal["acknowledge", "investigate", "assign", "escalate", "contain", "resolve", "suppress", "reopen"]
    note: str = Field(default="", max_length=2000)
    owner_user_id: str | None = None


@router.post("/alerts/{alert_id}/actions")
async def act_on_alert(alert_id: str, body: AlertAction, db: AsyncSession = Depends(get_db),
                       user: User = Depends(require_responder)) -> dict:
    if body.action == "suppress":
        await enforce_step_up(db, user, "admin")
    try:
        alert = await alert_service.act(db, user, alert_id, body.action, note=body.note,
                                        owner_user_id=body.owner_user_id, is_admin=user.role == "Admin")
    except (ValueError, LookupError) as exc:
        raise _bad_request(exc) from exc
    return await alert_service.view_one(db, alert)


# ── Provider Register ──────────────────────────────────────────────────────

Level = Literal["critical", "high", "medium", "low"]


class ProviderBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: Literal["ai_model", "cloud_security", "content", "other"]
    service: str = Field(default="", max_length=200)
    config_key: str | None = Field(default=None, max_length=120)
    criticality: Level = "medium"
    region: str = Field(default="", max_length=120)
    approved_use: str = Field(default="", max_length=300)
    data_classification: str = Field(default="", max_length=120)
    contract_state: str = Field(default="none", max_length=80)
    owner_user_id: str | None = None
    next_review_at: datetime | None = None


class ProviderPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    category: Literal["ai_model", "cloud_security", "content", "other"] | None = None
    service: str | None = Field(default=None, max_length=200)
    criticality: Level | None = None
    region: str | None = Field(default=None, max_length=120)
    approved_use: str | None = Field(default=None, max_length=300)
    data_classification: str | None = Field(default=None, max_length=120)
    contract_state: str | None = Field(default=None, max_length=80)
    owner_user_id: str | None = None
    next_review_at: datetime | None = None


class GateBody(BaseModel):
    status: Literal["pass", "open", "fail"]
    note: str = Field(default="", max_length=1000)


class DecisionBody(BaseModel):
    decision: str
    note: str = Field(default="", max_length=1000)


@router.get("/providers")
async def get_providers(db: AsyncSession = Depends(get_db), user: User = Depends(require_operations)) -> dict:
    return await registers.provider_register(db, user.tenant_id)


@router.post("/providers", status_code=201)
async def register_provider(body: ProviderBody, db: AsyncSession = Depends(get_db),
                            user: User = Depends(require_register_editor)) -> dict:
    try:
        record = await registers.create_provider(db, user, body.model_dump())
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return await registers.provider_view(db, user.tenant_id, record.id)


@router.patch("/providers/{record_id}")
async def update_provider(record_id: str, body: ProviderPatch, db: AsyncSession = Depends(get_db),
                          user: User = Depends(require_register_editor)) -> dict:
    try:
        await registers.update_provider(db, user, record_id, body.model_dump(exclude_unset=True))
    except (ValueError, LookupError) as exc:
        raise _bad_request(exc) from exc
    return await registers.provider_view(db, user.tenant_id, record_id)


@router.put("/providers/{record_id}/gates/{gate}")
async def set_provider_gate(record_id: str, gate: str, body: GateBody, db: AsyncSession = Depends(get_db),
                            user: User = Depends(require_register_editor)) -> dict:
    try:
        await registers.set_provider_gate(db, user, record_id, gate, body.status, body.note)
    except (ValueError, LookupError) as exc:
        raise _bad_request(exc) from exc
    return await registers.provider_view(db, user.tenant_id, record_id)


@router.post("/providers/{record_id}/decision")
async def decide_provider(record_id: str, body: DecisionBody, db: AsyncSession = Depends(get_db),
                          user: User = Depends(require_register_editor)) -> dict:
    try:
        await registers.decide_provider(db, user, record_id, body.decision, body.note)
    except (ValueError, LookupError) as exc:
        raise _bad_request(exc) from exc
    return await registers.provider_view(db, user.tenant_id, record_id)


# ── Integrations ───────────────────────────────────────────────────────────

Category = Literal["accounting", "ai_tools", "evidence", "source_feeds", "infrastructure"]
Flow = Literal["inbound", "outbound", "bidirectional"]


class IntegrationBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: Category
    provider_id: str | None = None
    health_key: str | None = None
    data_flow: Flow = "inbound"
    region: str = Field(default="", max_length=120)
    risk_tier: Level = "medium"
    auth_method: str = Field(default="", max_length=120)
    scopes_requested: list[str] = Field(default_factory=list, max_length=50)
    scopes_approved: list[str] = Field(default_factory=list, max_length=50)
    owner_user_id: str | None = None


class IntegrationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    category: Category | None = None
    provider_id: str | None = None
    health_key: str | None = None
    data_flow: Flow | None = None
    region: str | None = Field(default=None, max_length=120)
    risk_tier: Level | None = None
    auth_method: str | None = Field(default=None, max_length=120)
    scopes_requested: list[str] | None = Field(default=None, max_length=50)
    scopes_approved: list[str] | None = Field(default=None, max_length=50)
    owner_user_id: str | None = None


@router.get("/integrations")
async def get_integrations(db: AsyncSession = Depends(get_db), user: User = Depends(require_operations)) -> dict:
    return await registers.integration_register(db, user.tenant_id)


@router.post("/integrations", status_code=201)
async def register_integration(body: IntegrationBody, db: AsyncSession = Depends(get_db),
                               user: User = Depends(require_register_editor)) -> dict:
    try:
        record = await registers.create_integration(db, user, body.model_dump())
    except (ValueError, LookupError) as exc:
        raise _bad_request(exc) from exc
    return await registers.integration_view(db, user.tenant_id, record.id)


@router.patch("/integrations/{record_id}")
async def update_integration(record_id: str, body: IntegrationPatch, db: AsyncSession = Depends(get_db),
                             user: User = Depends(require_register_editor)) -> dict:
    try:
        await registers.update_integration(db, user, record_id, body.model_dump(exclude_unset=True))
    except (ValueError, LookupError) as exc:
        raise _bad_request(exc) from exc
    return await registers.integration_view(db, user.tenant_id, record_id)


@router.put("/integrations/{record_id}/gates/{gate}")
async def set_integration_gate(record_id: str, gate: str, body: GateBody, db: AsyncSession = Depends(get_db),
                               user: User = Depends(require_register_editor)) -> dict:
    try:
        await registers.set_integration_gate(db, user, record_id, gate, body.status, body.note)
    except (ValueError, LookupError) as exc:
        raise _bad_request(exc) from exc
    return await registers.integration_view(db, user.tenant_id, record_id)


@router.post("/integrations/{record_id}/decision")
async def decide_integration(record_id: str, body: DecisionBody, db: AsyncSession = Depends(get_db),
                             user: User = Depends(require_register_editor)) -> dict:
    try:
        await registers.decide_integration(db, user, record_id, body.decision, body.note)
    except (ValueError, LookupError) as exc:
        raise _bad_request(exc) from exc
    return await registers.integration_view(db, user.tenant_id, record_id)
