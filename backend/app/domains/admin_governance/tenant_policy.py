"""Tenant policy: the settings a tenant may tighten below its deployment.

Policy hierarchy (Tenant Settings spec): global safeguards first, then the
deployment's configuration, then the tenant's own preferences — and a tenant
preference may only be MORE restrictive. A change is staged as a request and
takes effect only when a second Admin approves it. The effective value is
what the governance code enforces (identity/governance.py, rbac.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.admin_governance.models import SettingChangeRequest, TenantPolicy
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User


@dataclass(frozen=True)
class Adjustable:
    key: str
    label: str
    domain: str
    kind: str  # "bool" (may only be switched on) | "int" (may only be lowered)
    deployment: Callable[[], bool | int]
    minimum: int = 1
    unit: str = ""
    enforced_by: str = ""


ADJUSTABLE: dict[str, Adjustable] = {a.key: a for a in (
    Adjustable("mfa_required_privileged", "MFA for privileged actions", "Identity & SSO", "bool",
               lambda: get_settings().MFA_REQUIRED_FOR_PRIVILEGED,
               enforced_by="Admin endpoints and every *.manage, review.resolve and audit.correct action"),
    Adjustable("impersonation_max_minutes", "Impersonation time limit", "Identity & SSO", "int",
               lambda: get_settings().IMPERSONATION_MAX_MINUTES, unit="minutes",
               enforced_by="Read-only “View as” sessions"),
    Adjustable("break_glass_max_minutes", "Break-glass time limit", "Privacy & Residency", "int",
               lambda: get_settings().BREAK_GLASS_MAX_MINUTES, unit="minutes",
               enforced_by="Emergency access grants"),
    Adjustable("break_glass_repeat_threshold", "Break-glass repeat-use alert", "Privacy & Residency", "int",
               lambda: get_settings().BREAK_GLASS_REPEAT_THRESHOLD, unit="grants in 30 days",
               enforced_by="Security review flag on repeated emergency access"),
    Adjustable("service_key_max_days", "Service-account key lifetime", "Integrations", "int",
               lambda: get_settings().SERVICE_KEY_MAX_DAYS, unit="days",
               enforced_by="API keys issued to service accounts"),
)}


class PolicyError(ValueError):
    """A change the policy hierarchy or the approval rules refuse."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _stored(db: AsyncSession, tenant_id: str) -> dict[str, TenantPolicy]:
    rows = (await db.execute(select(TenantPolicy).where(TenantPolicy.tenant_id == tenant_id))).scalars().all()
    return {r.key: r for r in rows}


def _combine(spec: Adjustable, tenant_value):
    deployment = spec.deployment()
    if tenant_value is None:
        return deployment
    # Only ever as strict as the deployment, or stricter.
    return (deployment or bool(tenant_value)) if spec.kind == "bool" else min(deployment, int(tenant_value))


async def tenant_value(db: AsyncSession, tenant_id: str | None, key: str):
    """The tenant's own stored value, or None (none set, or unreadable)."""
    if not tenant_id:
        return None
    try:
        row = (await db.execute(select(TenantPolicy).where(
            TenantPolicy.tenant_id == tenant_id, TenantPolicy.key == key))).scalar_one_or_none()
    except Exception:  # noqa: BLE001 — a read fault keeps the deployment value
        return None
    return row.value.get("v") if row else None


async def effective(db: AsyncSession, tenant_id: str | None, key: str):
    """The value enforced for this tenant. Falls back to the deployment value
    if the tenant's policy cannot be read, so a fault never loosens a limit
    below the deployment's own."""
    return _combine(ADJUSTABLE[key], await tenant_value(db, tenant_id, key))


async def effective_all(db: AsyncSession, tenant_id: str) -> dict[str, dict]:
    stored = await _stored(db, tenant_id)
    out = {}
    for key, spec in ADJUSTABLE.items():
        row = stored.get(key)
        out[key] = {"deployment": spec.deployment(), "tenant": row.value.get("v") if row else None,
                    "effective": _combine(spec, row.value.get("v") if row else None),
                    "updatedAt": row.updated_at.isoformat() if row else None}
    return out


def validate_proposal(key: str, proposed, current) -> bool | int:
    spec = ADJUSTABLE.get(key)
    if spec is None:
        raise PolicyError("This setting is not tenant-adjustable; it is locked by a global or deployment policy.")
    if spec.kind == "bool":
        if not isinstance(proposed, bool):
            raise PolicyError("Choose on or off.")
        if current and not proposed:
            raise PolicyError("Prohibited override: a tenant can only make this stricter. It is required by "
                              + ("the deployment." if spec.deployment() else "your tenant policy; turning it off would loosen it."))
        if proposed == current:
            raise PolicyError("That is already the effective value.")
        return proposed
    if isinstance(proposed, bool) or not isinstance(proposed, int):
        raise PolicyError("Enter a whole number.")
    if proposed < spec.minimum:
        raise PolicyError(f"Must be at least {spec.minimum}.")
    if proposed > current:
        raise PolicyError(f"Prohibited override: a tenant can only lower this limit (currently {current} {spec.unit}).")
    if proposed == current:
        raise PolicyError("That is already the effective value.")
    return proposed


async def _audit(db: AsyncSession, actor: User, event: str, req: SettingChangeRequest, payload: dict) -> None:
    await record_event_async(db, tenant_id=actor.tenant_id, event_name=event, emitting_service="admin_governance",
                             actor_id=actor.id, subject_type="tenant_setting", subject_id=req.key,
                             payload={"ref": req.ref, **payload})


async def request_change(db: AsyncSession, actor: User, key: str, proposed, reason: str) -> SettingChangeRequest:
    if key not in ADJUSTABLE:
        raise PolicyError("This setting is not tenant-adjustable; it is locked by a global or deployment policy.")
    if not reason.strip():
        raise PolicyError("A reason is required.")
    current = await effective(db, actor.tenant_id, key)
    value = validate_proposal(key, proposed, current)
    pending = (await db.execute(select(SettingChangeRequest.id).where(
        SettingChangeRequest.tenant_id == actor.tenant_id, SettingChangeRequest.key == key,
        SettingChangeRequest.status == "pending"))).first()
    if pending:
        raise PolicyError("A change to this setting is already waiting for approval.")
    count = (await db.execute(select(func.count()).select_from(SettingChangeRequest)
                              .where(SettingChangeRequest.tenant_id == actor.tenant_id))).scalar_one()
    req = SettingChangeRequest(tenant_id=actor.tenant_id, ref=f"CHG-{count + 1:03d}", key=key,
                               current_value={"v": current}, proposed_value={"v": value}, reason=reason.strip(),
                               status="pending", requested_by=actor.id, decision_note="")
    db.add(req)
    await db.flush()
    await _audit(db, actor, "tenant_setting_change_requested", req, {"from": current, "to": value})
    return req


async def decide(db: AsyncSession, actor: User, request_id: str, approve: bool, note: str) -> SettingChangeRequest:
    req = (await db.execute(select(SettingChangeRequest).where(
        SettingChangeRequest.id == request_id, SettingChangeRequest.tenant_id == actor.tenant_id))).scalar_one_or_none()
    if req is None:
        raise LookupError("Change request not found")
    if req.status != "pending":
        raise PolicyError("This request has already been decided.")
    if not approve and req.requested_by == actor.id:
        req.status = "withdrawn"
    elif req.requested_by == actor.id:
        raise PolicyError("Approval must come from a different Admin than the requester.")
    elif approve:
        # Re-validate against today's effective value: the deployment may have
        # changed since the request was staged.
        current = await effective(db, actor.tenant_id, req.key)
        value = validate_proposal(req.key, req.proposed_value["v"], current)
        row = (await db.execute(select(TenantPolicy).where(
            TenantPolicy.tenant_id == actor.tenant_id, TenantPolicy.key == req.key))).scalar_one_or_none()
        if row is None:
            db.add(TenantPolicy(tenant_id=actor.tenant_id, key=req.key, value={"v": value},
                                change_request_id=req.id, updated_by=actor.id, updated_at=_now()))
        else:
            row.value, row.change_request_id, row.updated_by, row.updated_at = {"v": value}, req.id, actor.id, _now()
        req.status = "applied"
    else:
        if not note.strip():
            raise PolicyError("A reason is required to reject a change.")
        req.status = "rejected"
    req.decided_by, req.decided_at, req.decision_note = actor.id, _now(), note.strip()
    await db.flush()
    await _audit(db, actor, f"tenant_setting_change_{req.status}", req, {"note": note.strip()})
    return req
