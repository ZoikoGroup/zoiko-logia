"""My Workspace shows the signed-in user's own activity and the tasks waiting
on them (app/domains/command_center/workspace.py)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.command_center.workspace import build_my_workspace
from app.domains.identity.models import Tenant, User
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.domains.model_gateway.models import PromptTemplate
from app.domains.risk_safety.models import EscalationCase, EscalationStatus, RiskLevel
from app.domains.source_library.models import Source, SourceVersion
from app.orchestration.models import ReviewCase

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Tenant(id="t1", name="T"), Tenant(id="t2", name="Other")])
        await session.commit()
        yield session
    await engine.dispose()


def _user(user_id="u1", role="Admin", tenant_id="t1") -> User:
    return User(id=user_id, tenant_id=tenant_id, email=f"{user_id}@example.com", full_name=user_id, role=role)


async def test_activity_is_the_users_own_work_newest_first(db):
    user = _user()
    db.add_all([
        user, _user("u2"),
        SavedAnswer(id="a1", tenant_id="t1", user_id="u1", query_id="q", query_text="UK VAT threshold",
                    answer_text="a", risk_level="LOW", created_at=NOW - timedelta(days=2)),
        SavedAnswer(id="a-other", tenant_id="t1", user_id="u2", query_id="q", query_text="Not mine",
                    answer_text="a", risk_level="LOW", created_at=NOW),
        Draft(id="d1", tenant_id="t1", user_id="u1", title="Q2 summary", status="Draft",
              created_at=NOW - timedelta(hours=1), updated_at=NOW - timedelta(hours=1)),
        ReviewCase(id="rc1", query_id="q", correlation_id="c", tenant_id="t1", query_text="VAT on vouchers?",
                   risk_level="HIGH", confidence_state="LOW", reason="r", status="resolved",
                   reviewer_id="u1", reviewer_decision="approve", resolved_at=NOW - timedelta(hours=3)),
    ])
    await db.commit()
    await record_event_async(db, tenant_id="t1", event_name="kriton_workspace.attachment_uploaded",
                             emitting_service="test", actor_id="u1", subject_type="document", subject_id="doc1", payload={})
    await record_event_async(db, tenant_id="t1", event_name="command_center.opened",   # page views are not activity
                             emitting_service="test", actor_id="u1", subject_type="workspace", subject_id="t1", payload={})

    view = await build_my_workspace(db, user, NOW)

    ids = [item["id"] for item in view["recentActivity"]]
    assert ids[:1][0].startswith("audit:")                       # just recorded, so newest
    assert ids[1:] == ["draft:d1", "review:rc1", "answer:a1"]
    assert not any("a-other" in i for i in ids)
    assert sum(1 for item in view["recentActivity"] if item["kind"] == "audit") == 1
    assert view["recentActivity"][0]["label"] == "Uploaded a document"


async def test_pending_tasks_follow_permissions_and_maker_checker(db):
    admin = _user()
    db.add_all([
        admin,
        ReviewCase(id="rc-open", query_id="q", correlation_id="c", tenant_id="t1", query_text="Lease or service?",
                   risk_level="HIGH", confidence_state="LOW", reason="r", status="open"),
        EscalationCase(id="esc-late", tenant_id="t1", query_id="q", query_text="q", topic="Audit advice",
                       risk_level=RiskLevel.HIGH, status=EscalationStatus.PENDING,
                       sla_deadline=(NOW - timedelta(hours=1)).replace(tzinfo=None)),
        Draft(id="d-final", tenant_id="t1", user_id="u1", title="Done", status="Final"),
        Draft(id="d-open", tenant_id="t1", user_id="u1", title="Board memo", status="In Review"),
        Source(id="s1", tenant_id="t1", category="Tax", title="HMRC VAT manual", source_class="primary"),
        SourceVersion(id="v-mine", tenant_id="t1", source_id="s1", status="PROPOSED", submitted_by="u1", version_label="v2"),
        SourceVersion(id="v-theirs", tenant_id="t1", source_id="s1", status="PROPOSED", submitted_by="u2", version_label="v3"),
        PromptTemplate(id="p-theirs", name="tax_answer", version="v2", status="PendingReview", submitted_by="u2"),
        PromptTemplate(id="p-mine", name="mine", version="v1", status="PendingReview", submitted_by="u1"),
    ])
    await db.commit()

    tasks = (await build_my_workspace(db, admin, NOW))["pendingTasks"]

    ids = {t["id"] for t in tasks}
    assert ids == {"review:rc-open", "escalation:esc-late", "draft:d-open", "source:v-theirs", "prompt:p-theirs"}
    late = next(t for t in tasks if t["id"] == "escalation:esc-late")
    assert late["status"] == "SLA breached" and late["tone"] == "bad"
    assert tasks[0]["tone"] == "bad"                              # most urgent first


async def test_a_role_without_manage_permissions_only_gets_its_own_drafts(db):
    user = _user(role="CFO")
    db.add_all([
        user,
        ReviewCase(id="rc", query_id="q", correlation_id="c", tenant_id="t1", query_text="q",
                   risk_level="HIGH", confidence_state="LOW", reason="r", status="open"),
        Draft(id="d1", tenant_id="t1", user_id="u1", title="My memo", status="Draft"),
    ])
    await db.commit()

    tasks = (await build_my_workspace(db, user, NOW))["pendingTasks"]

    assert [t["id"] for t in tasks] == ["draft:d1"]


async def test_another_tenant_sees_nothing(db):
    db.add_all([
        _user(),
        SavedAnswer(id="a1", tenant_id="t1", user_id="u1", query_id="q", query_text="x", answer_text="a", risk_level="LOW"),
        Draft(id="d1", tenant_id="t1", user_id="u1", title="x", status="Draft"),
    ])
    await db.commit()

    view = await build_my_workspace(db, _user("u9", tenant_id="t2"), NOW)

    assert view["recentActivity"] == [] and view["pendingTasks"] == []
