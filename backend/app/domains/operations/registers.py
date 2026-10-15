"""Provider Register (Provider Due Diligence Register, ZL-T0-12) and the
Integrations register.

Records are entered by governance staff and start under review with every
assurance gate open. A provider or connection can only be approved for scoped
use when every gate passes, and never by the person who registered it
(maker-checker). Gates that can be derived from other records are derived,
not typed in: an integration's provider gate follows its provider's decision
and its least-privilege gate compares requested and approved scopes.
Every change is audited.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User
from app.domains.operations import service as operations
from app.domains.operations.models import IntegrationRecord, ProviderRecord, ServiceHealthSample

PROVIDER_CATEGORIES = {"ai_model": "AI & model", "cloud_security": "Cloud & security",
                       "content": "Content licensors", "other": "Other services"}
PROVIDER_DECISIONS = ("approved_scoped", "conditional", "under_review", "on_hold", "suspended")
PROVIDER_GATES = {
    "security_assessment": ("Security assessment", "Security control review and pen-test evidence recorded"),
    "regional_deployment": ("Regional deployment", "Processing regions and data boundary documented"),
    "exit_plan": ("Exit and fallback plan", "Fallback path and exit route reviewed"),
    "dpa_transfer": ("DPA / transfer terms", "Data processing terms and cross-border safeguards signed"),
    "no_training": ("No-training assurance", "Contractual exclusion of customer data from model training"),
    "subprocessors": ("Subprocessor transparency", "Subprocessor disclosure and change-notice terms reviewed"),
}

INTEGRATION_CATEGORIES = {"accounting": "Accounting systems", "ai_tools": "AI tools",
                          "evidence": "Evidence & documents", "source_feeds": "Source feeds",
                          "infrastructure": "Infrastructure"}
INTEGRATION_STATES = ("approved_scoped", "pending", "under_review", "on_hold", "suspended")
DATA_FLOWS = ("inbound", "outbound", "bidirectional")
LEVELS = ("critical", "high", "medium", "low")
# Gates an approver records by hand; the other two are derived.
INTEGRATION_GATES = {
    "provider_approval": ("Provider scoped approval", "derived"),
    "tenant_authorization": ("Tenant authorization", "manual"),
    "least_privilege": ("Least-privilege scopes", "derived"),
    "residency_privacy": ("Residency and privacy", "manual"),
    "secret_vault": ("Authentication and secret vault", "manual"),
    "replay_idempotency": ("Replay and idempotency", "manual"),
    "release_approval": ("Evaluation and release approval", "manual"),
}
GATE_STATUSES = ("pass", "open", "fail")
REVIEW_HORIZON = timedelta(days=90)


class RegisterError(ValueError):
    """A change the register's rules refuse."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


def _entry(action: str, actor: User, note: str = "") -> dict:
    return {"at": _now().isoformat(), "action": action, "actorId": actor.id,
            "actor": actor.full_name or actor.email, "note": note}


def _blank_gates(keys) -> dict:
    return {k: {"status": "open", "note": "", "by": None, "at": None} for k in keys}


async def _names(db: AsyncSession, tenant_id: str, ids: set) -> dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.tenant_id == tenant_id, User.id.in_(ids)))).scalars().all()
    return {u.id: u.full_name or u.email for u in rows}


async def _next_ref(db: AsyncSession, model, tenant_id: str, prefix: str) -> str:
    count = (await db.execute(select(func.count()).select_from(model).where(model.tenant_id == tenant_id))).scalar_one()
    return f"{prefix}-{count + 1:03d}"


async def _audit(db: AsyncSession, actor: User, event: str, subject_type: str, record, payload: dict) -> None:
    await record_event_async(db, tenant_id=actor.tenant_id, event_name=event, emitting_service="operations",
                             actor_id=actor.id, subject_type=subject_type, subject_id=record.id,
                             payload={"ref": record.ref, **payload})


async def _owner_ok(db: AsyncSession, tenant_id: str, owner_id: str | None) -> None:
    if owner_id and (await db.execute(select(User.id).where(
            User.id == owner_id, User.tenant_id == tenant_id, User.is_active.is_(True)))).first() is None:
        raise RegisterError("Owner must be an active user in this workspace")


def _check_choice(value, allowed, label: str) -> None:
    if value is not None and value not in allowed:
        raise RegisterError(f"Unknown {label}")


# ── Providers ──────────────────────────────────────────────────────────────

def _provider_view(p: ProviderRecord, names: dict[str, str], configured: set[str], now: datetime) -> dict:
    gates = [{"key": k, "label": label, "description": desc, **(p.gates.get(k) or {"status": "open"}),
              "byName": names.get((p.gates.get(k) or {}).get("by") or "")}
             for k, (label, desc) in PROVIDER_GATES.items()]
    review = _aware(p.next_review_at)
    return {
        "id": p.id, "ref": p.ref, "name": p.name, "category": p.category,
        "categoryLabel": PROVIDER_CATEGORIES.get(p.category, p.category), "service": p.service,
        "configKey": p.config_key, "inUse": bool(p.config_key and p.config_key in configured),
        "decision": p.decision, "criticality": p.criticality, "region": p.region,
        "approvedUse": p.approved_use, "dataClassification": p.data_classification,
        "contractState": p.contract_state, "ownerId": p.owner_user_id, "owner": names.get(p.owner_user_id or ""),
        "nextReviewAt": _iso(review), "reviewDue": bool(review and review <= now + REVIEW_HORIZON),
        "gates": gates, "gatesPassed": sum(g["status"] == "pass" for g in gates), "gatesTotal": len(gates),
        "createdBy": names.get(p.created_by), "createdAt": _iso(p.created_at),
        "decidedBy": names.get(p.decided_by or ""), "decidedAt": _iso(p.decided_at), "history": p.history,
    }


def _detected_providers(records: list[ProviderRecord]) -> list[dict]:
    """Providers this deployment is configured to call that nobody has registered."""
    registered = {p.config_key for p in records if p.config_key}
    out = [{"configKey": p["key"], "name": p["name"], "category": "ai_model", "service": p["purpose"]}
           for p in operations.model_providers() if p["configured"] and p["key"] not in registered]
    out += [{"configKey": f"data:{d['name']}", "name": d["name"], "category": "content", "service": d["category"]}
            for d in operations.data_sources()
            if d["configured"] and d["access"] == "API key" and f"data:{d['name']}" not in registered]
    return out


async def provider_register(db: AsyncSession, tenant_id: str) -> dict:
    now = _now()
    records = list((await db.execute(select(ProviderRecord).where(ProviderRecord.tenant_id == tenant_id)
                                     .order_by(ProviderRecord.ref.desc()))).scalars().all())
    ids = {p.owner_user_id for p in records} | {p.created_by for p in records} | {p.decided_by for p in records}
    for p in records:
        ids |= {(g or {}).get("by") for g in p.gates.values()}
    names = await _names(db, tenant_id, ids)
    configured = {p["key"] for p in operations.model_providers() if p["configured"]} | {
        f"data:{d['name']}" for d in operations.data_sources() if d["configured"]}
    views = [_provider_view(p, names, configured, now) for p in records]
    critical = [v for v in views if v["criticality"] == "critical"]
    exit_ok = [v for v in critical if next(g for g in v["gates"] if g["key"] == "exit_plan")["status"] == "pass"]
    return {
        "providers": views,
        "detected": _detected_providers(records),
        "summary": {
            "registered": len(views),
            "approved": sum(v["decision"] == "approved_scoped" for v in views),
            "inReview": sum(v["decision"] in {"conditional", "under_review"} for v in views),
            "conditional": sum(v["decision"] == "conditional" for v in views),
            "underReview": sum(v["decision"] == "under_review" for v in views),
            "blocked": sum(v["decision"] in {"on_hold", "suspended"} for v in views),
            "reviewActions": sum(v["reviewDue"] for v in views),
        },
        "resilience": {"critical": len(critical), "fallbackDocumented": len(exit_ok),
                       "untestedExits": len(critical) - len(exit_ok)},
        "categories": PROVIDER_CATEGORIES,
        "generatedAt": now.isoformat(),
    }


async def create_provider(db: AsyncSession, actor: User, data: dict) -> ProviderRecord:
    _check_choice(data.get("category"), PROVIDER_CATEGORIES, "category")
    _check_choice(data.get("criticality"), LEVELS, "criticality")
    await _owner_ok(db, actor.tenant_id, data.get("owner_user_id"))
    if data.get("config_key") and (await db.execute(select(ProviderRecord.id).where(
            ProviderRecord.tenant_id == actor.tenant_id, ProviderRecord.config_key == data["config_key"]))).first():
        raise RegisterError("This provider is already registered")
    record = ProviderRecord(
        tenant_id=actor.tenant_id, ref=await _next_ref(db, ProviderRecord, actor.tenant_id, "PRV"),
        decision="under_review", gates=_blank_gates(PROVIDER_GATES), created_by=actor.id,
        history=[_entry("registered", actor)], **data,
    )
    db.add(record)
    await db.flush()
    await _audit(db, actor, "provider_registered", "provider_record", record, {"name": record.name})
    return record


_PROVIDER_FIELDS = {"name", "category", "service", "criticality", "region", "approved_use", "data_classification",
                    "contract_state", "owner_user_id", "next_review_at"}


async def _get(db: AsyncSession, model, tenant_id: str, record_id: str):
    record = (await db.execute(select(model).where(model.id == record_id, model.tenant_id == tenant_id))).scalar_one_or_none()
    if record is None:
        raise LookupError("Record not found")
    return record


async def update_provider(db: AsyncSession, actor: User, record_id: str, data: dict) -> ProviderRecord:
    record = await _get(db, ProviderRecord, actor.tenant_id, record_id)
    _check_choice(data.get("category"), PROVIDER_CATEGORIES, "category")
    _check_choice(data.get("criticality"), LEVELS, "criticality")
    if "owner_user_id" in data:
        await _owner_ok(db, actor.tenant_id, data["owner_user_id"])
    changed = {k: v for k, v in data.items() if k in _PROVIDER_FIELDS and getattr(record, k) != v}
    for k, v in changed.items():
        setattr(record, k, v)
    if changed:
        record.updated_at = _now()
        record.history = [*record.history, _entry("updated", actor, ", ".join(sorted(changed)))]
        await db.flush()
        await _audit(db, actor, "provider_updated", "provider_record", record, {"fields": sorted(changed)})
    return record


def _set_gate(record, gates: dict, key: str, status: str, note: str, actor: User) -> None:
    if key not in gates:
        raise RegisterError("Unknown gate")
    if status not in GATE_STATUSES:
        raise RegisterError("Unknown gate status")
    if status == "fail" and not note.strip():
        raise RegisterError("Explain why the gate fails")
    record.gates = {**record.gates, key: {"status": status, "note": note.strip(), "by": actor.id,
                                         "at": _now().isoformat()}}
    record.updated_at = _now()
    record.history = [*record.history, _entry(f"gate:{key}", actor, f"{status}{': ' + note.strip() if note.strip() else ''}")]


async def set_provider_gate(db: AsyncSession, actor: User, record_id: str, key: str, status: str, note: str) -> ProviderRecord:
    record = await _get(db, ProviderRecord, actor.tenant_id, record_id)
    _set_gate(record, PROVIDER_GATES, key, status, note, actor)
    # A failed gate takes an approved provider out of approval.
    if status != "pass" and record.decision == "approved_scoped":
        record.decision = "conditional"
        record.history = [*record.history, _entry("decision:conditional", actor, "Gate no longer passing")]
    await db.flush()
    await _audit(db, actor, "provider_gate_recorded", "provider_record", record, {"gate": key, "status": status})
    return record


async def decide_provider(db: AsyncSession, actor: User, record_id: str, decision: str, note: str) -> ProviderRecord:
    record = await _get(db, ProviderRecord, actor.tenant_id, record_id)
    _check_choice(decision, PROVIDER_DECISIONS, "decision")
    if decision == "approved_scoped":
        open_gates = [PROVIDER_GATES[k][0] for k in PROVIDER_GATES if (record.gates.get(k) or {}).get("status") != "pass"]
        if open_gates:
            raise RegisterError("Every assurance gate must pass before approval: " + ", ".join(open_gates))
        if record.created_by == actor.id:
            raise RegisterError("Approval must come from someone other than the person who registered the provider")
        if not record.approved_use.strip():
            raise RegisterError("Record the approved use before approving")
    elif decision != "under_review" and not note.strip():
        raise RegisterError("A note is required for this decision")
    record.decision, record.decided_by, record.decided_at = decision, actor.id, _now()
    record.updated_at = _now()
    record.history = [*record.history, _entry(f"decision:{decision}", actor, note.strip())]
    await db.flush()
    await _audit(db, actor, "provider_decision_recorded", "provider_record", record, {"decision": decision})
    return record


# ── Integrations ───────────────────────────────────────────────────────────

async def _latest_health(db: AsyncSession, keys: set[str]) -> dict[str, ServiceHealthSample]:
    if not keys:
        return {}
    latest = (select(ServiceHealthSample.service_key, func.max(ServiceHealthSample.checked_at).label("at"))
              .where(ServiceHealthSample.service_key.in_(keys)).group_by(ServiceHealthSample.service_key).subquery())
    rows = (await db.execute(select(ServiceHealthSample).join(
        latest, (ServiceHealthSample.service_key == latest.c.service_key)
        & (ServiceHealthSample.checked_at == latest.c.at)))).scalars().all()
    return {r.service_key: r for r in rows}


def _derived_gates(record: IntegrationRecord, provider: ProviderRecord | None) -> dict:
    if provider is None:
        provider_gate = {"status": "open", "note": "No provider linked"}
    elif provider.decision == "approved_scoped":
        provider_gate = {"status": "pass", "note": f"{provider.ref} approved for scoped use"}
    elif provider.decision in {"on_hold", "suspended"}:
        provider_gate = {"status": "fail", "note": f"{provider.ref} is {provider.decision.replace('_', ' ')}"}
    else:
        provider_gate = {"status": "open", "note": f"{provider.ref} is {provider.decision.replace('_', ' ')}"}
    excess = sorted(set(record.scopes_requested) - set(record.scopes_approved))
    if not record.scopes_requested:
        scope_gate = {"status": "open", "note": "No scopes recorded"}
    elif excess:
        scope_gate = {"status": "fail", "note": "Requested beyond approved: " + ", ".join(excess)}
    else:
        scope_gate = {"status": "pass", "note": "Requested scopes are within the approved scope"}
    return {"provider_approval": provider_gate, "least_privilege": scope_gate}


def _integration_view(r: IntegrationRecord, provider: ProviderRecord | None, health: ServiceHealthSample | None,
                      names: dict[str, str]) -> dict:
    derived = _derived_gates(r, provider)
    gates = []
    for key, (label, kind) in INTEGRATION_GATES.items():
        value = derived[key] if kind == "derived" else (r.gates.get(key) or {"status": "open"})
        gates.append({"key": key, "label": label, "derived": kind == "derived", "status": value["status"],
                      "note": value.get("note", ""), "byName": names.get(value.get("by") or ""), "at": value.get("at")})
    if health is not None and health.state != "not_configured":
        health_state, health_detail = health.state, health.detail
    elif r.authorization != "approved_scoped":
        health_state, health_detail = "not_enabled", "Not enabled until authorized"
    else:
        health_state, health_detail = "not_monitored", "No live check linked"
    return {
        "id": r.id, "ref": r.ref, "name": r.name, "category": r.category,
        "categoryLabel": INTEGRATION_CATEGORIES.get(r.category, r.category),
        "providerId": r.provider_id, "provider": f"{provider.ref} · {provider.name}" if provider else None,
        "healthKey": r.health_key, "health": health_state, "healthDetail": health_detail,
        "healthCheckedAt": _iso(health.checked_at) if health else None,
        "authorization": r.authorization, "dataFlow": r.data_flow, "region": r.region, "riskTier": r.risk_tier,
        "authMethod": r.auth_method, "scopesRequested": r.scopes_requested, "scopesApproved": r.scopes_approved,
        "ownerId": r.owner_user_id, "owner": names.get(r.owner_user_id or ""),
        "gates": gates, "gatesPassed": sum(g["status"] == "pass" for g in gates), "gatesTotal": len(gates),
        "scopeException": derived["least_privilege"]["status"] == "fail",
        "createdBy": names.get(r.created_by), "createdAt": _iso(r.created_at),
        "decidedBy": names.get(r.decided_by or ""), "decidedAt": _iso(r.decided_at), "history": r.history,
    }


def _ratio(views: list[dict], key: str) -> dict:
    statuses = [next(g for g in v["gates"] if g["key"] == key)["status"] for v in views]
    return {"passed": statuses.count("pass"), "total": len(statuses)}


async def integration_register(db: AsyncSession, tenant_id: str) -> dict:
    now = _now()
    records = list((await db.execute(select(IntegrationRecord).where(IntegrationRecord.tenant_id == tenant_id)
                                     .order_by(IntegrationRecord.ref.desc()))).scalars().all())
    providers = {p.id: p for p in (await db.execute(
        select(ProviderRecord).where(ProviderRecord.tenant_id == tenant_id))).scalars().all()}
    health = await _latest_health(db, {r.health_key for r in records if r.health_key})
    ids = {r.owner_user_id for r in records} | {r.created_by for r in records} | {r.decided_by for r in records}
    for r in records:
        ids |= {(g or {}).get("by") for g in r.gates.values()}
    names = await _names(db, tenant_id, ids)
    views = [_integration_view(r, providers.get(r.provider_id or ""), health.get(r.health_key or ""), names)
             for r in records]

    exceptions = []
    for v in views:
        failing = [g for g in v["gates"] if g["status"] == "fail"]
        if v["authorization"] == "suspended":
            exceptions.append({"id": v["id"], "ref": v["ref"], "title": f"{v['name']} suspended", "action": "BLOCK"})
        elif v["authorization"] == "on_hold" or v["scopeException"]:
            reason = "requests scopes beyond approval" if v["scopeException"] else "on hold"
            exceptions.append({"id": v["id"], "ref": v["ref"], "title": f"{v['name']} {reason}", "action": "HOLD"})
        elif failing or v["health"] == "down":
            reason = "is unavailable" if v["health"] == "down" else f"fails {failing[0]['label'].lower()}"
            exceptions.append({"id": v["id"], "ref": v["ref"], "title": f"{v['name']} {reason}", "action": "REVIEW"})

    registered_keys = {r.health_key for r in records if r.health_key}
    detected = [{"healthKey": key, "name": operations.SERVICE_NAMES[key], "category": "infrastructure"
                 if key in {"database", "supabase_auth", "redis", "kroki"} else
                 ("ai_tools" if key in {"groq", "google", "openai", "anthropic"} else "source_feeds")}
                for key, _, _, _ in operations.SERVICES
                if key not in {"api"} | registered_keys and key in _configured_service_keys()]
    return {
        "integrations": views,
        "detected": detected,
        "summary": {
            "registered": len(views),
            "approved": sum(v["authorization"] == "approved_scoped" for v in views),
            "pending": sum(v["authorization"] in {"pending", "under_review"} for v in views),
            "degraded": sum(v["health"] in {"down", "degraded"} for v in views),
            "blocked": sum(v["authorization"] in {"on_hold", "suspended"} for v in views),
            "scopeExceptions": sum(v["scopeException"] for v in views),
        },
        "controls": {key: _ratio(views, key) for key in
                     ("least_privilege", "secret_vault", "replay_idempotency", "residency_privacy")},
        "exceptions": exceptions,
        "categories": INTEGRATION_CATEGORIES,
        "providers": [{"id": p.id, "label": f"{p.ref} · {p.name}"} for p in providers.values()],
        "generatedAt": now.isoformat(),
    }


def _configured_service_keys() -> set[str]:
    keys = {p["key"] for p in operations.model_providers() if p["configured"]}
    keys |= {"database"}
    by_name = {i["name"]: i["configured"] for i in operations.integrations()}
    if by_name.get("Supabase Auth"):
        keys.add("supabase_auth")
    if by_name.get("SearXNG"):
        keys.add("searxng")
    if by_name.get("Kroki"):
        keys.add("kroki")
    if by_name.get("Redis / Celery"):
        keys.add("redis")
    return keys


_INTEGRATION_FIELDS = {"name", "category", "provider_id", "health_key", "data_flow", "region", "risk_tier",
                       "auth_method", "scopes_requested", "scopes_approved", "owner_user_id"}


async def _validate_integration(db: AsyncSession, actor: User, data: dict) -> None:
    _check_choice(data.get("category"), INTEGRATION_CATEGORIES, "category")
    _check_choice(data.get("data_flow"), DATA_FLOWS, "data flow")
    _check_choice(data.get("risk_tier"), LEVELS, "risk tier")
    if data.get("health_key") and data["health_key"] not in operations.SERVICE_NAMES:
        raise RegisterError("Unknown health check")
    if data.get("provider_id"):
        await _get(db, ProviderRecord, actor.tenant_id, data["provider_id"])
    if "owner_user_id" in data:
        await _owner_ok(db, actor.tenant_id, data["owner_user_id"])
    for key in ("scopes_requested", "scopes_approved"):
        if key in data:
            data[key] = sorted({s.strip() for s in data[key] if s and s.strip()})


async def create_integration(db: AsyncSession, actor: User, data: dict) -> IntegrationRecord:
    await _validate_integration(db, actor, data)
    record = IntegrationRecord(
        tenant_id=actor.tenant_id, ref=await _next_ref(db, IntegrationRecord, actor.tenant_id, "INT"),
        authorization="pending",
        gates=_blank_gates(k for k, (_, kind) in INTEGRATION_GATES.items() if kind == "manual"),
        created_by=actor.id, history=[_entry("registered", actor)], **data,
    )
    db.add(record)
    await db.flush()
    await _audit(db, actor, "integration_registered", "integration_record", record, {"name": record.name})
    return record


async def update_integration(db: AsyncSession, actor: User, record_id: str, data: dict) -> IntegrationRecord:
    record = await _get(db, IntegrationRecord, actor.tenant_id, record_id)
    await _validate_integration(db, actor, data)
    changed = {k: v for k, v in data.items() if k in _INTEGRATION_FIELDS and getattr(record, k) != v}
    for k, v in changed.items():
        setattr(record, k, v)
    if changed:
        record.updated_at = _now()
        record.history = [*record.history, _entry("updated", actor, ", ".join(sorted(changed)))]
        # Widening scopes or changing the provider re-opens approval.
        if record.authorization == "approved_scoped" and changed.keys() & {"scopes_requested", "scopes_approved", "provider_id"}:
            record.authorization = "under_review"
            record.history = [*record.history, _entry("authorization:under_review", actor, "Scope or provider changed")]
        await db.flush()
        await _audit(db, actor, "integration_updated", "integration_record", record, {"fields": sorted(changed)})
    return record


async def set_integration_gate(db: AsyncSession, actor: User, record_id: str, key: str, status: str, note: str) -> IntegrationRecord:
    record = await _get(db, IntegrationRecord, actor.tenant_id, record_id)
    if INTEGRATION_GATES.get(key, ("", ""))[1] == "derived":
        raise RegisterError("This gate is derived from other records and cannot be set by hand")
    manual = {k for k, (_, kind) in INTEGRATION_GATES.items() if kind == "manual"}
    _set_gate(record, {k: None for k in manual}, key, status, note, actor)
    if status != "pass" and record.authorization == "approved_scoped":
        record.authorization = "under_review"
        record.history = [*record.history, _entry("authorization:under_review", actor, "Gate no longer passing")]
    await db.flush()
    await _audit(db, actor, "integration_gate_recorded", "integration_record", record, {"gate": key, "status": status})
    return record


async def decide_integration(db: AsyncSession, actor: User, record_id: str, decision: str, note: str) -> IntegrationRecord:
    record = await _get(db, IntegrationRecord, actor.tenant_id, record_id)
    _check_choice(decision, INTEGRATION_STATES, "authorization")
    if decision == "approved_scoped":
        provider = await db.get(ProviderRecord, record.provider_id) if record.provider_id else None
        view = _integration_view(record, provider, None, {})
        open_gates = [g["label"] for g in view["gates"] if g["status"] != "pass"]
        if open_gates:
            raise RegisterError("Every release gate must pass before enabling: " + ", ".join(open_gates))
        if record.created_by == actor.id:
            raise RegisterError("Authorization must come from someone other than the person who registered the connection")
    elif decision not in {"pending", "under_review"} and not note.strip():
        raise RegisterError("A note is required for this decision")
    record.authorization, record.decided_by, record.decided_at = decision, actor.id, _now()
    record.updated_at = _now()
    record.history = [*record.history, _entry(f"authorization:{decision}", actor, note.strip())]
    await db.flush()
    await _audit(db, actor, "integration_authorization_recorded", "integration_record", record, {"authorization": decision})
    return record


async def provider_view(db: AsyncSession, tenant_id: str, record_id: str) -> dict:
    data = await provider_register(db, tenant_id)
    return next(p for p in data["providers"] if p["id"] == record_id)


async def integration_view(db: AsyncSession, tenant_id: str, record_id: str) -> dict:
    data = await integration_register(db, tenant_id)
    return next(i for i in data["integrations"] if i["id"] == record_id)
