"""Operations console: measured health history, alert lifecycle and the
provider / integration registers.

Pins that health numbers come only from stored samples and real request
timings, that alerts follow their live condition (raised, cleared, recurred)
with their owner and history kept, that alert and register rules hold
(separation of duties, Admin-only suppression, gate-checked approval), that
derived gates cannot be typed in, and that tenants stay isolated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.identity.models import Tenant, User
from app.domains.operations import alerts, health, registers, telemetry
from app.domains.operations import service as operations
from app.domains.operations.models import OperationsAlert, ServiceHealthSample
from app.domains.operations.router import require_register_editor, require_responder

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def _user(uid, tenant, role):
    return User(id=uid, tenant_id=tenant, email=f"{uid}@example.com", first_name=uid, last_name="",
                full_name=uid.title(), role=role, is_active=True)


@pytest.fixture
async def db(monkeypatch):
    # Audit events are written to the ledger; keep them, but no live services.
    async def _no_checks(_db):
        return []
    monkeypatch.setattr(operations, "dependency_checks", _no_checks)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="Acme"), Tenant(id="t2", name="Other"),
            _user("admin", "t1", "Admin"), _user("risk", "t1", "Risk Admin"),
            _user("auditor", "t1", "System Auditor"), _user("ops", "t1", "Governance Ops Lead"),
            _user("b-admin", "t2", "Admin"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


async def _get(db, uid):
    return await db.get(User, uid)


def _sample(key, state, minutes_ago, latency=None, **extra):
    return ServiceHealthSample(service_key=key, state=state, latency_ms=latency,
                               checked_at=NOW - timedelta(minutes=minutes_ago), detail=extra.pop("detail", ""), **extra)


# ── Telemetry and Status & Health ──────────────────────────────────────────

def test_api_summary_is_measured_from_real_requests(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "recorder", telemetry._RequestRecorder())
    assert telemetry.api_summary(300)["latencyMs"] is None, "no requests: no latency claimed"
    for ms in (10, 20, 30, 40, 1000):
        telemetry.recorder.record(ms, 200)
    telemetry.recorder.record(50, 503)
    summary = telemetry.api_summary(300)
    assert summary["requests"] == 6 and summary["errors"] == 1
    assert summary["latencyMs"] == 1000
    assert summary["state"] == "degraded", "1 in 6 server errors is above the 5% threshold"


async def test_status_history_comes_only_from_samples(db, monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "api_summary", lambda _s: {
        "key": "api", "name": "Kriton API", "state": "operational", "latencyMs": 120, "p50Ms": 40,
        "requests": 10, "errors": 0, "detail": ""})
    db.add_all([
        _sample("searxng", "operational", 120, 80), _sample("searxng", "down", 60, detail="ConnectError"),
        _sample("searxng", "down", 30, detail="ConnectError"), _sample("searxng", "operational", 5, 90),
        _sample("api", "operational", 30, 300, p50_ms=50, requests=20, errors=0),
        _sample("database", "operational", 30, 12),
        _sample("searxng", "down", 60 * 30, detail="older than a day"),
    ])
    await db.commit()

    async def _live(_db):
        return [{"key": "database", "name": "Database", "state": "operational", "latencyMs": 9, "detail": "ok"},
                {"key": "searxng", "name": "Web search", "state": "operational", "latencyMs": 70, "detail": "HTTP 200"},
                {"key": "kroki", "name": "Diagrams", "state": "not_configured", "latencyMs": None, "detail": ""}]
    monkeypatch.setattr(operations, "dependency_checks", _live)

    status = await health.build_status(db, await _get(db, "admin"), now=NOW)
    services = {s["key"]: s for s in status["services"]}
    assert "kroki" not in services, "a never-configured service is not listed as monitored"
    # 4 stored samples in 24h plus the live check this view just recorded: 2 of 5 down.
    assert services["searxng"]["availability24h"] == 60.0
    assert services["searxng"]["samples24h"] == 5
    assert status["summary"]["apiP95Ms"] == 300
    transitions = [(e["from"], e["to"]) for e in status["events"] if e["serviceKey"] == "searxng"]
    assert transitions == [("down", "operational"), ("operational", "down")]
    assert status["dependencyMap"]["key"] == "api"
    assert status["summary"]["platformState"] == "operational"


# ── Alerts ─────────────────────────────────────────────────────────────────

def _condition(key="gov:esc-overdue", severity="High"):
    return {"source_key": key, "origin": "governance", "category": "AI safety", "severity": severity,
            "title": "2 escalations past SLA", "detail": "", "href": "/escalation-queue", "service_key": None}


async def test_alert_follows_its_condition_and_keeps_its_history(db) -> None:
    await alerts.sync(db, "t1", [_condition()], NOW)
    view = await alerts.list_alerts(db, "t1", safety_blocks=0, now=NOW)
    alert = view["alerts"][0]
    assert alert["ref"] == "ALT-2026-0001" and alert["state"] == "unacknowledged"
    assert view["summary"]["unacknowledged"] == 1

    admin = await _get(db, "admin")
    await alerts.act(db, admin, alert["id"], "acknowledge")
    await alerts.sync(db, "t1", [], NOW + timedelta(minutes=5))
    row = await db.get(OperationsAlert, alert["id"])
    assert row.state == "resolved" and row.resolved_by is None, "a cleared condition resolves itself"

    await alerts.sync(db, "t1", [_condition()], NOW + timedelta(minutes=10))
    await db.refresh(row)
    assert row.state == "unacknowledged" and row.ref == "ALT-2026-0001", "a recurrence reopens the same alert"
    assert [h["action"] for h in row.history] == ["detected", "acknowledge", "cleared", "recurred"]

    other = await alerts.list_alerts(db, "t2", safety_blocks=0, now=NOW)
    assert other["alerts"] == [], "alerts are per tenant"


async def test_alert_rules(db) -> None:
    risk, admin, ops = await _get(db, "risk"), await _get(db, "admin"), await _get(db, "ops")
    manual = await alerts.create_manual(db, risk, title="Ledger export stalled", severity="Medium",
                                        category="Platform operations", detail="", service_key=None)
    with pytest.raises(alerts.AlertActionError, match="Only an Admin"):
        await alerts.act(db, risk, manual.id, "suppress", note="noise")
    await alerts.act(db, risk, manual.id, "escalate")
    assert manual.severity == "High"
    with pytest.raises(alerts.AlertActionError, match="someone other"):
        await alerts.act(db, risk, manual.id, "resolve", note="fixed")
    await alerts.act(db, ops, manual.id, "resolve", note="Export job restarted")
    assert manual.state == "resolved"

    await alerts.sync(db, "t1", [_condition()], NOW)
    automatic = (await alerts.list_alerts(db, "t1", safety_blocks=0, now=NOW))["alerts"][0]
    with pytest.raises(alerts.AlertActionError, match="resolves automatically"):
        await alerts.act(db, admin, automatic["id"], "resolve", note="x")
    await alerts.act(db, admin, automatic["id"], "assign", owner_user_id="risk")
    with pytest.raises(alerts.AlertActionError, match="active user in this workspace"):
        await alerts.act(db, admin, automatic["id"], "assign", owner_user_id="b-admin")


async def test_system_auditor_reads_but_cannot_act(db) -> None:
    with pytest.raises(HTTPException) as exc:
        await require_responder(await _get(db, "auditor"))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        await require_register_editor(await _get(db, "auditor"), db)


# ── Registers ──────────────────────────────────────────────────────────────

async def test_provider_approval_needs_every_gate_and_a_second_person(db, monkeypatch) -> None:
    monkeypatch.delenv("MODEL_GATEWAY_APPROVED_PROVIDERS", raising=False)
    risk, admin = await _get(db, "risk"), await _get(db, "admin")
    record = await registers.create_provider(db, risk, {
        "name": "Groq", "category": "ai_model", "service": "AI inference", "config_key": "groq",
        "criticality": "critical", "approved_use": "Answer composition"})
    assert record.ref == "PRV-001" and record.decision == "under_review"
    with pytest.raises(registers.RegisterError, match="Every assurance gate"):
        await registers.decide_provider(db, admin, record.id, "approved_scoped", "")
    for gate in registers.PROVIDER_GATES:
        await registers.set_provider_gate(db, risk, record.id, gate, "pass", "")
    with pytest.raises(registers.RegisterError, match="someone other"):
        await registers.decide_provider(db, risk, record.id, "approved_scoped", "")
    await registers.decide_provider(db, admin, record.id, "approved_scoped", "")
    assert record.decision == "approved_scoped"

    await registers.set_provider_gate(db, risk, record.id, "no_training", "fail", "Clause removed in renewal")
    assert record.decision == "conditional", "a failing gate withdraws approval"
    with pytest.raises(registers.RegisterError, match="already registered"):
        await registers.create_provider(db, risk, {"name": "Groq again", "category": "ai_model", "config_key": "groq"})

    view = await registers.provider_register(db, "t1")
    assert view["summary"] == {"registered": 1, "approved": 0, "inReview": 1, "conditional": 1,
                               "underReview": 0, "blocked": 0, "reviewActions": 0}
    assert view["resilience"] == {"critical": 1, "fallbackDocumented": 1, "untestedExits": 0}
    assert (await registers.provider_register(db, "t2"))["providers"] == []


async def test_integration_gates_are_derived_where_they_can_be(db) -> None:
    risk, admin = await _get(db, "risk"), await _get(db, "admin")
    provider = await registers.create_provider(db, risk, {"name": "Ledger Co", "category": "other"})
    record = await registers.create_integration(db, risk, {
        "name": "General ledger", "category": "accounting", "provider_id": provider.id,
        "scopes_requested": ["read:ledger", "write:journal"], "scopes_approved": ["read:ledger"]})
    view = await registers.integration_view(db, "t1", record.id)
    gates = {g["key"]: g for g in view["gates"]}
    assert gates["least_privilege"]["status"] == "fail" and "write:journal" in gates["least_privilege"]["note"]
    assert gates["provider_approval"]["status"] == "open"
    assert view["scopeException"] and view["health"] == "not_enabled"
    with pytest.raises(registers.RegisterError, match="derived"):
        await registers.set_integration_gate(db, admin, record.id, "least_privilege", "pass", "")

    register = await registers.integration_register(db, "t1")
    assert register["summary"]["scopeExceptions"] == 1
    assert register["exceptions"][0]["action"] == "HOLD"
    with pytest.raises(registers.RegisterError, match="Every release gate"):
        await registers.decide_integration(db, admin, record.id, "approved_scoped", "")
