"""Tenant Settings: the effective control register for one tenant.

Each control states the authority it sits under, as the policy hierarchy
requires: global safeguards (fixed in code), the deployment's configuration
(backend/.env, read-only here), and tenant-scoped preferences the tenant may
only tighten through an approved change request (tenant_policy.py).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import supabase_admin
from app.core.config import get_settings
from app.domains.admin_governance import tenant_policy
from app.domains.admin_governance.access import _activity, _latest_reviews, _people, review_due
from app.domains.admin_governance.models import SettingChangeRequest
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import BreakGlassGrant, Tenant, User
from app.domains.identity.permissions import ROLE_PERMISSIONS
from app.domains.operations import service as operations

HIERARCHY = [
    {"level": 1, "title": "Global safety and tenant isolation", "detail": "Mandatory protections in code · cannot be overridden"},
    {"level": 2, "title": "Deployment configuration", "detail": "Set for this deployment (backend/.env) · read-only here"},
    {"level": 3, "title": "Tenant preferences and approved rules", "detail": "Only more restrictive values, each approved by a second Admin"},
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(value, unit: str = "") -> str:
    if isinstance(value, bool):
        return "Required" if value else "Not required"
    return f"{value} {unit}".strip()


async def build(db: AsyncSession, admin: User) -> dict:
    s = get_settings()
    now = _now()
    tenant = await db.get(Tenant, admin.tenant_id)
    eff = await tenant_policy.effective_all(db, admin.tenant_id)
    requests = (await db.execute(select(SettingChangeRequest).where(
        SettingChangeRequest.tenant_id == admin.tenant_id).order_by(SettingChangeRequest.requested_at.desc()))).scalars().all()
    names = {u.id: u.full_name or u.email for u in (await db.execute(
        select(User).where(User.tenant_id == admin.tenant_id))).scalars()}
    pending = {r.key: r for r in requests if r.status == "pending"}
    approved_providers = os.getenv("MODEL_GATEWAY_APPROVED_PROVIDERS", "").strip()

    def adjustable(cid, key, risk):
        spec = tenant_policy.ADJUSTABLE[key]
        e = eff[key]
        tightened = e["tenant"] is not None and e["effective"] != e["deployment"]
        state = ("staged" if key in pending else
                 "enforced" if spec.kind == "int" or e["effective"] else "review_due")
        return {
            "id": cid, "key": key, "name": spec.label, "domain": spec.domain, "authority": "tenant_scoped",
            "state": state, "risk": risk, "value": _fmt(e["effective"], spec.unit),
            "deploymentValue": _fmt(e["deployment"], spec.unit),
            "tenantValue": None if e["tenant"] is None else _fmt(e["tenant"], spec.unit),
            "rawEffective": e["effective"], "kind": spec.kind, "unit": spec.unit,
            "description": f"Applies to: {spec.enforced_by}.",
            "rule": "May only be made stricter" + (" (switched on)" if spec.kind == "bool" else " (lowered)")
                    + "; a second Admin approves each change.",
            "tightened": tightened, "changedAt": e["updatedAt"], "changeAuthority": "Admin (maker-checker)",
        }

    def fixed(cid, name, domain, authority, state, risk, value, description):
        return {"id": cid, "key": None, "name": name, "domain": domain, "authority": authority, "state": state,
                "risk": risk, "value": value, "deploymentValue": value, "tenantValue": None, "rawEffective": None,
                "kind": None, "unit": "", "description": description,
                "rule": "Fixed in code; cannot be overridden by a tenant." if authority == "global_locked"
                else "Set for the whole deployment; change it in backend/.env and restart.",
                "tightened": False, "changedAt": None,
                "changeAuthority": "Platform engineering" if authority == "global_locked" else "Deployment operator"}

    controls = [
        fixed("TS-001", "Tenant isolation baseline", "Privacy & Residency", "global_locked", "enforced", "critical",
              "Row-level security on every tenant table",
              "Every tenant table is filtered by the signed-in tenant in the database itself; startup refuses to run if a policy is missing."),
        fixed("TS-002", "Identity provider & sign-in", "Identity & SSO", "deployment",
              "enforced" if supabase_admin.is_configured() else "not_configured", "high",
              "Supabase Auth" if supabase_admin.is_configured() else "Not configured",
              "Email and password, Google and Microsoft sign-in through Supabase Auth. SAML single sign-on is not available yet."),
        adjustable("TS-003", "mfa_required_privileged", "high"),
        fixed("TS-004", "Public sign-up", "Identity & SSO", "deployment", "enforced", "high",
              "Open" if s.ALLOW_PUBLIC_SIGNUP else "Invite-only",
              "When open, anyone can create their own workspace; when invite-only, only people an Admin invites can sign in."),
        adjustable("TS-005", "impersonation_max_minutes", "medium"),
        adjustable("TS-006", "break_glass_max_minutes", "critical"),
        adjustable("TS-007", "break_glass_repeat_threshold", "high"),
        adjustable("TS-008", "service_key_max_days", "high"),
        fixed("TS-009", "Uploaded document retention", "Privacy & Residency", "deployment", "enforced", "high",
              f"{s.DOCUMENT_RETENTION_DAYS} days", "Uploaded documents are deleted after this period."),
        fixed("TS-010", "Generated file retention", "Privacy & Residency", "deployment", "enforced", "medium",
              f"{s.ARTIFACT_RETENTION_DAYS} days", "Generated reports and files are deleted after this period."),
        fixed("TS-011", "Data residency (database region)", "Privacy & Residency", "deployment", "enforced", "high",
              operations.service_location("database"), "Where this deployment's database runs; it is the same for every tenant."),
        fixed("TS-012", "Approved AI model providers", "Kriton & AI", "deployment",
              "enforced" if approved_providers else "review_due", "high",
              approved_providers or "Not restricted",
              "The model gateway calls only the providers on this allow-list. With no list, any configured provider may be used."),
        fixed("TS-013", "Kriton tool access by role", "Kriton & AI", "global_locked", "enforced", "high",
              "Registered roles only", "Kriton's tools run only for roles in the permission registry; an unknown role is refused."),
        fixed("TS-014", "Professional review authority", "Professional Approvals", "global_locked", "enforced", "critical",
              ", ".join(r for r, perms in ROLE_PERMISSIONS.items() if "review.resolve" in perms),
              "Only roles holding review.resolve can approve, correct or reject a Kriton answer; nobody can clear their own work."),
        fixed("TS-015", "Minor learner accounts", "Professional Approvals", "global_locked", "blocked", "critical",
              "Blocked", "Under-18 sign-ups are refused until guardian-consent controls exist."),
        fixed("TS-016", "Alert notifications", "Notifications", "deployment", "not_configured", "medium",
              "In-app only", "No email, Slack or pager channel is connected; alerts are delivered in the console."),
    ]
    for c in controls:
        c["pendingRequest"] = pending[c["key"]].ref if c["key"] in pending else None
        c["history"] = [_request_view(r, names) for r in requests if r.key == c["key"]] if c["key"] else []

    prohibited = (await db.execute(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.tenant_id == admin.tenant_id,
        AuditEvent.event_name == "tenant_setting_override_prohibited"))).scalar_one()
    people = [u for u in await _people(db, admin.tenant_id) if u.is_active]
    reviews = await _latest_reviews(db, admin.tenant_id)
    reviews_due = sum(1 for u in people if review_due(u, reviews.get(u.id), now)[1])
    exceptions = (await db.execute(select(func.count()).select_from(BreakGlassGrant).where(
        BreakGlassGrant.tenant_id == admin.tenant_id, BreakGlassGrant.status == "active",
        BreakGlassGrant.expires_at > now))).scalar_one()
    applied = sum(r.status == "applied" for r in requests)

    return {
        "tenant": {"name": tenant.name if tenant else "", "id": admin.tenant_id,
                   "policyVersion": f"v{applied + 1}", "evaluatedAt": now.isoformat(),
                   "region": operations.service_location("database")},
        "controls": controls,
        "requests": [_request_view(r, names) for r in requests],
        "hierarchy": HIERARCHY,
        "summary": {
            "effectiveControls": sum(c["state"] == "enforced" for c in controls),
            "totalControls": len(controls),
            "stagedRequests": len(pending),
            "prohibitedOverrides": prohibited + sum(r.status == "rejected" for r in requests),
            "reviewsDue": reviews_due,
            "tightened": sum(c["tightened"] for c in controls),
            "activeExceptions": exceptions,
        },
        "activity": await _activity(db, admin.tenant_id, prefixes=("tenant_setting_",), limit=8),
        "generatedAt": now.isoformat(),
    }


def _request_view(r: SettingChangeRequest, names: dict[str, str]) -> dict:
    spec = tenant_policy.ADJUSTABLE.get(r.key)
    unit = spec.unit if spec else ""
    return {"id": r.id, "ref": r.ref, "key": r.key, "setting": spec.label if spec else r.key,
            "from": _fmt(r.current_value.get("v"), unit), "to": _fmt(r.proposed_value.get("v"), unit),
            "reason": r.reason, "status": r.status, "requestedBy": names.get(r.requested_by, ""),
            "requestedById": r.requested_by, "requestedAt": r.requested_at.isoformat() if r.requested_at else None,
            "decidedBy": names.get(r.decided_by or "", None), "decidedAt": r.decided_at.isoformat() if r.decided_at else None,
            "decisionNote": r.decision_note}
