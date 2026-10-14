# Endpoints backing the Operations and Administration pages.
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.admin_governance import overview
from app.domains.command_center.service import build_governance, cached
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user, require_admin
from app.domains.operations import service as operations

router = APIRouter(tags=["Operations & Administration"])

# Operations pages are for governance roles; never Learners.
_OPERATIONS_ROLES = {"Admin", "AI Governance Lead", "Governance Ops Lead", "Risk Admin", "System Auditor"}


async def require_operations(user: User = Depends(get_current_user)) -> User:
    if user.role not in _OPERATIONS_ROLES:
        raise HTTPException(status_code=403, detail="Operations views are not available for this role")
    return user


@router.get("/operations/alerts")
async def get_alerts(fresh: bool = False, user: User = Depends(require_operations)) -> dict:
    """The live governance exceptions — the same list the Governance Dashboard
    shows, so the two pages always agree."""
    now = datetime.now(timezone.utc)
    view = await cached(
        ("governance", user.tenant_id, user.id, user.role, user.updated_at.isoformat(), "CONNECTED", 30),
        lambda: build_governance(user, now, 30, "CONNECTED"), fresh=fresh,
    )
    return {"alerts": view["exceptions"], "generatedAt": view["generatedAt"]}


@router.get("/operations/connections")
async def get_connections(_: User = Depends(require_operations)) -> dict:
    return {
        "modelProviders": operations.model_providers(),
        "dataSources": operations.data_sources(),
        "integrations": operations.integrations(),
    }


@router.get("/operations/status")
async def get_status(db: AsyncSession = Depends(get_db), user: User = Depends(require_operations)) -> dict:
    checks = await operations.status_checks(db, user.tenant_id)
    return {"checks": checks, "checkedAt": datetime.now(timezone.utc).isoformat()}


@router.get("/admin/roles-matrix")
async def get_roles_matrix(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await overview.roles_matrix(db, admin.tenant_id)


@router.get("/admin/tenant-settings")
async def get_tenant_settings(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await overview.tenant_settings(db, admin.tenant_id)


@router.get("/admin/usage")
async def get_usage(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return await overview.usage(db, admin.tenant_id)
