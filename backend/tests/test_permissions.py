"""Section 2 — role→permission registry and require_permission.

Locks down the approved permission matrix (name-for-name, so a future change
to who-can-do-what is a deliberate edit, not a silent drift), the deny-by-
default behaviour for anything outside it, and the dependency wrapper. A
source-level check also pins the router migration: the four modules that were
Admin-only batch checks must now be permission-gated, no exceptions.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from app.domains.audit_ledger import router as audit_router
from app.domains.identity.models import User
from app.domains.identity.permissions import (
    AUDIT_CORRECT,
    ALL_PERMISSIONS,
    MODEL_MANAGE,
    ROLE_PERMISSIONS,
    SOURCE_MANAGE,
    SOURCE_READ,
    SUPPORT_MANAGE,
    SUPPORT_READ,
    permissions_for_role,
    user_has_permission,
)
from app.domains.identity.rbac import require_permission
from app.domains.model_gateway import router as model_gateway_router
from app.domains.source_library import router as source_router
from app.domains.support_incident import router as support_router

# The six role-table roles from scripts/seed_dev_user.py ROLES, plus the
# literal "Admin" that /auth/provision assigns every first signer.
SEEDED_ROLES = {
    "Admin",
    "Governance Ops Lead",
    "Source Admin",
    "Syllabus Admin",
    "Jurisdiction Lead",
    "Risk Admin",
    "System Auditor",
}


def _user(role: str) -> User:
    return User(id="user-1", tenant_id="tenant-1", email="a@example.com", full_name="A B", role=role)


async def test_permissions_declared_exactly_once_in_registry() -> None:
    declared = {SOURCE_READ, SOURCE_MANAGE, SUPPORT_READ, SUPPORT_MANAGE, MODEL_MANAGE, AUDIT_CORRECT}
    assert ALL_PERMISSIONS == declared
    # Every permission a role carries must be a declared one — a mistyped
    # permission would otherwise silently deny forever (unknown permission).
    assigned = {p for perms in ROLE_PERMISSIONS.values() for p in perms}
    assert assigned <= declared


async def test_role_matrix_matches_approved_mapping() -> None:
    assert set(ROLE_PERMISSIONS) == SEEDED_ROLES, "registry must cover exactly the assignable roles"
    assert ROLE_PERMISSIONS["Admin"] == ALL_PERMISSIONS
    assert ROLE_PERMISSIONS["Governance Ops Lead"] == frozenset({
        SOURCE_READ, SOURCE_MANAGE, SUPPORT_READ, SUPPORT_MANAGE, MODEL_MANAGE, AUDIT_CORRECT,
    })
    assert ROLE_PERMISSIONS["Source Admin"] == frozenset({SOURCE_READ, SOURCE_MANAGE})
    assert ROLE_PERMISSIONS["Syllabus Admin"] == frozenset()
    assert ROLE_PERMISSIONS["Jurisdiction Lead"] == frozenset({SOURCE_READ})
    assert ROLE_PERMISSIONS["Risk Admin"] == frozenset({MODEL_MANAGE})
    assert ROLE_PERMISSIONS["System Auditor"] == frozenset({SOURCE_READ, SUPPORT_READ})


async def test_unknown_role_denies_everything() -> None:
    assert permissions_for_role("CFO") == frozenset()
    assert not user_has_permission(_user("CFO"), SOURCE_READ)
    assert not user_has_permission(_user("CFO"), MODEL_MANAGE)


async def test_write_permissions_require_more_than_read() -> None:
    """A source.read-only role (Jurisdiction Lead, System Auditor) must not be
    able to write; a manage permission must always be paired with its read."""
    for role in ("Jurisdiction Lead", "System Auditor"):
        perms = permissions_for_role(role)
        assert SUPPORT_MANAGE not in perms
        assert SOURCE_MANAGE not in perms
    for perms in ROLE_PERMISSIONS.values():
        if SOURCE_MANAGE in perms:
            assert SOURCE_READ in perms


async def test_require_permission_grants_holder() -> None:
    dependency = require_permission(SOURCE_MANAGE)
    source_admin = await dependency(_user("Source Admin"))
    assert source_admin.role == "Source Admin"
    governance = await dependency(_user("Governance Ops Lead"))
    assert governance.role == "Governance Ops Lead"


async def test_require_permission_denies_with_403() -> None:
    dependency = require_permission(SOURCE_MANAGE)
    with pytest.raises(HTTPException) as exc:
        await dependency(_user("Jurisdiction Lead"))
    assert exc.value.status_code == 403
    assert "source.manage" in exc.value.detail


async def test_require_permission_denies_unknown_role() -> None:
    dependency = require_permission(SOURCE_READ)
    with pytest.raises(HTTPException) as exc:
        await dependency(_user("Executive"))
    assert exc.value.status_code == 403


async def test_admin_still_carries_every_permission() -> None:
    admin = _user("Admin")
    for permission in ALL_PERMISSIONS:
        assert user_has_permission(admin, permission)


async def test_migrated_routers_are_permission_gated_not_admin_gated() -> None:
    """The four modules that were blanket-Admin must now gate on permissions —
    pinned structurally so a 'quick refactor back' to require_admin fails."""
    for module in (source_router, support_router, audit_router, model_gateway_router):
        source = inspect.getsource(module)
        assert "require_admin" not in source, f"{module.__name__} still uses require_admin"
        assert "require_permission(" in source, f"{module.__name__} lost its permission gates"


async def test_non_migrated_admin_endpoints_intact_in_identity_router() -> None:
    """identity and engagement routers keep require_admin (tenant-admin user
    management + engagement lifecycle) — still present, unchanged."""
    from app.domains.identity import engagement_router as engagement_module
    from app.domains.identity import router as identity_module

    assert "require_admin" in inspect.getsource(identity_module)
    assert "require_admin" in inspect.getsource(engagement_module)
    assert "require_permission(" not in inspect.getsource(identity_module), "identity router unexpectedly permission-gated"
    assert "require_permission(" not in inspect.getsource(engagement_module), "engagement router unexpectedly permission-gated"