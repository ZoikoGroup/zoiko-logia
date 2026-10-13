"""Command Center / My Workspace show the signed-in user's real data.

The page used to greet everyone as "Lennox" with invented matters, deadlines
and recent work. Pins that the view now comes only from the user's own
records, stays inside their tenant, and gives Learners no governance view.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.command_center.router import get_command_center
from app.domains.identity.models import BreakGlassGrant, Engagement, EngagementMembership, Tenant, User
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.domains.support_incident.models import SecurityIncident
from app.orchestration.models import QueryAnswerRecord

NOW = datetime.now(timezone.utc)


def _user(uid, tenant, role, first=""):
    return User(id=uid, tenant_id=tenant, email=f"{uid}@example.com", first_name=first, last_name="",
                full_name=f"{first} Test".strip(), role=role, is_active=True)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="Acme Ltd"), Tenant(id="t2", name="Other Co"),
            _user("asha", "t1", "Admin", "Asha"), _user("ravi", "t1", "Source Admin", "Ravi"),
            _user("lea", "t1", "Learner", "Lea"), _user("zed", "t2", "Admin", "Zed"),
            QueryAnswerRecord(query_id="q-old", tenant_id="t1", user_id="asha", question="Old question",
                              created_at=NOW - timedelta(days=10)),
            QueryAnswerRecord(query_id="q-new", tenant_id="t1", user_id="asha", question="What is the VAT rate?",
                              created_at=NOW - timedelta(hours=1)),
            QueryAnswerRecord(query_id="q-ravi", tenant_id="t1", user_id="ravi", question="Ravi's private question",
                              created_at=NOW),
            SavedAnswer(id="sa-1", tenant_id="t1", user_id="asha", query_id="q-new", query_text="VAT rate",
                        answer_text="20%", risk_level="LOW", created_at=NOW - timedelta(minutes=30)),
            Draft(id="d-1", tenant_id="t1", user_id="asha", title="Lease memo", status="Draft",
                  updated_at=NOW - timedelta(minutes=5)),
            Engagement(id="e-1", tenant_id="t1", name="FY26 audit — Acme"),
            Engagement(id="e-2", tenant_id="t1", name="Not mine"),
            EngagementMembership(id="m-1", tenant_id="t1", engagement_id="e-1", user_id="asha", engagement_role="lead"),
            SecurityIncident(id="inc-1", tenant_id="t1", title="Prompt bypass attempt", severity="Critical",
                             source="CONTROL_BYPASS"),
            BreakGlassGrant(id="bg-1", tenant_id="t1", user_id="asha", permissions=["audit.correct"], reason="x",
                            duration_minutes=60, status="active", expires_at=NOW + timedelta(minutes=45)),
        ])
        await session.commit()
        yield session
    await engine.dispose()


async def _home(db, uid):
    return await get_command_center(db=db, current_user=await db.get(User, uid))


async def test_greets_the_real_user_in_their_workspace(db) -> None:
    model = await _home(db, "asha")
    assert model["user"]["firstName"] == "Asha"
    assert model["workspace"]["name"] == "Acme Ltd"
    assert "Lennox" not in repr(model)


async def test_recent_work_is_the_users_own_newest_first(db) -> None:
    model = await _home(db, "asha")
    titles = [item["title"] for item in model["recentWork"]]
    assert titles[:3] == ["Lease memo", "VAT rate", "What is the VAT rate?"]
    assert "Ravi's private question" not in titles
    assert model["counts"]["questionsLast7Days"] == 1
    assert model["counts"]["savedAnswers"] == 1 and model["counts"]["drafts"] == 1


async def test_active_matters_are_the_users_engagements(db) -> None:
    matters = (await _home(db, "asha"))["activeMatters"]
    assert [m["name"] for m in matters] == ["FY26 audit — Acme"]
    assert matters[0]["myRole"] == "lead"
    assert (await _home(db, "ravi"))["activeMatters"] == []


async def test_attention_and_deadlines_come_from_live_conditions(db) -> None:
    model = await _home(db, "asha")
    assert any(item["id"] == "incident:inc-1" for item in model["attentionItems"])
    assert any(d["title"] == "Your emergency access ends" for d in model["deadlines"])
    assert model["assurance"]["overallState"] == "critical"


async def test_other_tenants_see_none_of_it(db) -> None:
    model = await _home(db, "zed")
    assert model["recentWork"] == [] and model["activeMatters"] == []
    assert model["attentionItems"] == []
    assert model["workspace"]["name"] == "Other Co"


async def test_learners_get_their_work_but_no_governance_view(db) -> None:
    model = await _home(db, "lea")
    assert model["attentionItems"] == [] and model["reviewQueue"] == []
    assert model["assurance"] is None
