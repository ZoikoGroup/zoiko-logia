"""Notification bell: ledger events become notifications for the right
people, once; "needs your action" counts open work; settings validate."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Tenant, User
from app.domains.identity.rbac import get_current_user
from app.domains.notifications_workflow import service
from app.domains.notifications_workflow.models import Notification, UserSettings
from app.domains.notifications_workflow.router import router
from app.orchestration.models import ReviewCase

NOW = datetime.now(timezone.utc)


def _event(n: int, name: str, actor: str, payload: dict, subject: str = "q-1", tenant: str = "t1") -> AuditEvent:
    return AuditEvent(
        id=f"ev-{n}", event_name=name, emitting_service="test", tenant_id=tenant, actor_id=actor,
        subject_type="query", subject_id=subject, payload=payload, payload_hash="h", chain_hash=f"c{n}",
        event_time=NOW - timedelta(minutes=10 - n), ingested_at=NOW - timedelta(minutes=10 - n),
    )


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add_all([Tenant(id="t1", name="Acme"), Tenant(id="t2", name="Other")])
        await session.flush()
        for uid, role, tenant in [("asker", "CFO", "t1"), ("reviewer", "SME Reviewer", "t1"),
                                  ("risk", "Risk Admin", "t1"), ("srcadmin", "Source Admin", "t1"),
                                  ("admin", "Admin", "t1"), ("other-reviewer", "SME Reviewer", "t2")]:
            session.add(User(id=uid, tenant_id=tenant, email=f"{uid}@x.test", full_name=uid, role=role))
        await session.commit()
        service._last_sync.clear()
        yield session
    await engine.dispose()


async def _notified(db, kind: str) -> set[str]:
    rows = await db.execute(select(Notification.user_id).where(Notification.kind == kind))
    return set(rows.scalars())


async def test_review_events_reach_reviewers_and_the_asker_once(db):
    db.add_all([
        _event(1, "query_received", "asker", {}),
        _event(2, "human_review_created", "asker", {"review_case_id": "rc-1"}),
        _event(3, "human_review_resolved", "reviewer", {"review_case_id": "rc-1", "decision": "APPROVED"}),
    ])
    await db.commit()

    created = await service.sync_tenant(db, "t1", force=True)
    # Reviewers in this tenant only, never the other tenant's reviewer.
    assert await _notified(db, "review_assigned") == {"reviewer", "risk", "admin"}
    # The asker hears the outcome; the reviewer who acted does not.
    assert await _notified(db, "question_reviewed") == {"asker"}
    assert created == 4

    # A second sweep over the same events creates nothing new.
    assert await service.sync_tenant(db, "t1", force=True) == 0


async def test_source_submission_and_muted_kinds(db):
    db.add(UserSettings(user_id="admin", tenant_id="t1", preferences={"muted_notifications": ["source_submitted"]}))
    db.add_all([
        _event(1, "source_ingestion_event", "srcadmin", {"title": "IFRS 16", "status": "PROPOSED"}),
        _event(2, "source_ingestion_event", "srcadmin", {"title": "Old", "status": "APPROVED"}),
    ])
    await db.commit()
    await service.sync_tenant(db, "t1", force=True)
    # Submitter excluded, Admin muted it; approved-at-upload sources don't notify.
    notified = list((await db.execute(select(Notification).where(Notification.kind == "source_submitted"))).scalars())
    assert [(n.user_id, n.body) for n in notified] == []


async def test_source_submission_reaches_other_source_managers(db):
    db.add(_event(1, "source_ingestion_event", "srcadmin", {"title": "IFRS 16", "status": "PROPOSED"}))
    await db.commit()
    await service.sync_tenant(db, "t1", force=True)
    assert await _notified(db, "source_submitted") == {"admin"}


@pytest.fixture
def app_for(db):
    def build(user_id: str) -> FastAPI:
        app = FastAPI()
        app.include_router(router)

        async def same_db():
            yield db

        app.dependency_overrides[get_db] = same_db

        async def current():
            return await db.get(User, user_id)

        app.dependency_overrides[get_current_user] = current
        return app
    return build


async def _call(app, method, path, json=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, json=json)


async def test_bell_summary_list_and_mark_read(db, app_for, monkeypatch):
    async def sweep(tenant_id):
        await service.sync_tenant(db, tenant_id, force=True)

    monkeypatch.setattr(service, "sync_tenant_safely", sweep)
    db.add_all([_event(1, "query_received", "asker", {}), _event(2, "human_review_created", "asker", {})])
    db.add(ReviewCase(id="rc-1", query_id="q-1", correlation_id="c", tenant_id="t1", risk_level="HIGH",
                      confidence_state="limited", reason="test", status="open"))
    await db.commit()

    app = app_for("reviewer")
    # The first check starts the ledger sweep after responding; the next one
    # shows what it created.
    await _call(app, "GET", "/notifications/summary")
    summary = (await _call(app, "GET", "/notifications/summary")).json()
    assert summary["unread"] == 1
    assert summary["action_items"] == [{"key": "reviews", "count": 1, "label": "1 question waiting for review",
                                        "link": "/review-tasks", "severity": "warn"}]

    items = (await _call(app, "GET", "/notifications")).json()
    assert [(i["kind"], i["read"], i["link"]) for i in items] == [("review_assigned", False, "/review-tasks")]
    assert (await _call(app, "POST", f"/notifications/{items[0]['id']}/read")).json() == {"updated": 1}
    assert (await _call(app, "GET", "/notifications/summary")).json()["unread"] == 0

    # Another user's notification can't be marked read by this user.
    asker_app = app_for("asker")
    assert (await _call(asker_app, "POST", f"/notifications/{items[0]['id']}/read")).json() == {"updated": 0}


async def test_settings_round_trip_and_validation(db, app_for):
    app = app_for("asker")
    initial = (await _call(app, "GET", "/me/settings")).json()
    assert initial["default_jurisdiction"] == "" and initial["muted_notifications"] == []
    assert {"kind": "question_reviewed", "label": "Your question has been reviewed"} in initial["notification_kinds"]

    saved = (await _call(app, "PATCH", "/me/settings", {"default_jurisdiction": "UK",
                                                         "muted_notifications": ["incident_opened"]})).json()
    assert saved["default_jurisdiction"] == "UK" and saved["muted_notifications"] == ["incident_opened"]
    assert (await _call(app, "PATCH", "/me/settings", {"muted_notifications": ["nope"]})).status_code == 422
    assert (await _call(app, "PATCH", "/me/settings", {"default_jurisdiction": "Mars"})).status_code == 422
    assert (await _call(app, "GET", "/me/settings")).json()["default_jurisdiction"] == "UK"
