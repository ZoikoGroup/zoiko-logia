"""Shared controls for WF-01 platform release governance.

require_governance(permission): the permission (identity/permissions.py), and
membership of the platform governance tenant (settings.
KRITON_GOVERNANCE_TENANT_ID). Unset, or another tenant, is refused and the
denial audited: platform governance is not a tenant Admin capability.

Writes require an Idempotency-Key; records are hash-bound (sha256 of their
canonical JSON) and signed with KRITON_GOVERNANCE_SIGNING_KEY when it is
configured. Without the key a record is UNSIGNED_NO_KEY, which no release
gate accepts. Errors carry a machine-readable code (WF-01 §13).
"""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import record_access_denied, require_permission


def governance_error(code: str, message: str, http_status: int = status.HTTP_409_CONFLICT) -> HTTPException:
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


def require_governance(permission: str):
    base = require_permission(permission)

    async def dependency(current_user: User = Depends(base), db: AsyncSession = Depends(get_db)) -> User:
        governance_tenant = get_settings().KRITON_GOVERNANCE_TENANT_ID.strip()
        if not governance_tenant:
            await record_access_denied(db, current_user, permission, "governance_tenant_not_configured")
            raise governance_error("GOVERNANCE_TENANT_NOT_CONFIGURED",
                                   "Platform release governance is not configured on this deployment.", status.HTTP_403_FORBIDDEN)
        if current_user.tenant_id != governance_tenant:
            await record_access_denied(db, current_user, permission, "not_governance_member")
            raise governance_error("NOT_GOVERNANCE_MEMBER",
                                   "Platform release governance is limited to the governance tenant.", status.HTTP_403_FORBIDDEN)
        return current_user

    return dependency


def idempotency_key(key: str | None = Header(default=None, alias="Idempotency-Key")) -> str:
    if not key or not key.strip() or len(key) > 200:
        raise governance_error("IDEMPOTENCY_KEY_REQUIRED", "Send an Idempotency-Key header (1-200 characters).",
                               status.HTTP_400_BAD_REQUEST)
    return key.strip()


def canonical_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def sign(content_sha256: str) -> tuple[str, str]:
    """(signature, status): an HMAC over the content hash with the configured
    key, or ("", "UNSIGNED_NO_KEY") when no key is configured."""
    key = get_settings().KRITON_GOVERNANCE_SIGNING_KEY
    if not key:
        return "", "UNSIGNED_NO_KEY"
    return hmac.new(key.encode(), content_sha256.encode(), hashlib.sha256).hexdigest(), "SIGNED"
