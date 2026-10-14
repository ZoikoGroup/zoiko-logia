"""Reports & Insights aggregates the tenant's own records in a time window
(app/domains/kriton_workspace/insights.py)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Tenant, User
from app.domains.kriton_workspace.insights import build_insights
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.domains.learning_cpd.models import CPDEntry
from app.orchestration.models import AnswerFeedback, QueryAnswerRecord, ReviewCase

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def _event(n, name, payload, tenant="t1", days_ago=1):
    at = NOW - timedelta(days=days_ago)
    return AuditEvent(id=f"e{n}", event_name=name, emitting_service="orchestration", tenant_id=tenant,
                      subject_type="query", subject_id=f"q{n}", payload=payload, payload_hash="h",
                      chain_hash=f"c{n}", event_time=at, ingested_at=at)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="T"), Tenant(id="t2", name="Other"),
            # three questions this window (two yesterday, one today) and one old
            _event(1, "query_received", {}, days_ago=1), _event(2, "query_received", {}, days_ago=1),
            _event(3, "query_received", {}, days_ago=0), _event(4, "query_received", {}, days_ago=60),
            _event(5, "query_received", {}, tenant="t2"),
            _event(6, "response_finalised", {"outcome": "answered", "route": "LLM"}),
            _event(7, "response_finalised", {"outcome": "answered", "route": "LLM"}),
            _event(8, "response_finalised", {"outcome": "refused", "route": "REFUSAL"}),
            _event(9, "risk_classified", {"risk_level": "LOW"}),
            _event(10, "risk_classified", {"risk_level": "HIGH"}),
            _event(11, "response_returned", {"latency_ms": 1000.0}),
            _event(12, "response_returned", {"latency_ms": 3000.0}),
            QueryAnswerRecord(query_id="a1", tenant_id="t1", user_id="u1", question="What is the UK VAT threshold?",
                              answer_text="x", created_at=NOW - timedelta(days=1),
                              external_evidence=[{"url": "https://www.gov.uk/vat"}, {"url": "https://www.gov.uk/vat-rates"}]),
            QueryAnswerRecord(query_id="a2", tenant_id="t1", user_id="u1", question="Explain IFRS 16 lease accounting",
                              answer_text="x", created_at=NOW - timedelta(days=2),
                              external_evidence=[{"url": "https://www.ifrs.org/ifrs-16"}]),
            ReviewCase(id="r1", query_id="q", correlation_id="c", tenant_id="t1", query_text="q", risk_level="HIGH",
                       confidence_state="LOW", reason="r", status="open", source="user_feedback", created_at=NOW - timedelta(days=1)),
            ReviewCase(id="r2", query_id="q", correlation_id="c", tenant_id="t1", query_text="q", risk_level="HIGH",
                       confidence_state="LOW", reason="r", status="resolved", source="escalation", created_at=NOW - timedelta(days=1)),
            AnswerFeedback(id="f1", tenant_id="t1", user_id="u1", query_id="q1", rating="up", created_at=NOW - timedelta(days=1)),
            AnswerFeedback(id="f2", tenant_id="t1", user_id="u1", query_id="q2", rating="down", created_at=NOW - timedelta(days=1)),
            SavedAnswer(id="s1", tenant_id="t1", user_id="u1", query_id="q", query_text="q", answer_text="a",
                        risk_level="LOW", created_at=NOW - timedelta(days=1)),
            Draft(id="d1", tenant_id="t1", user_id="u1", title="Memo", status="Final",
                  created_at=NOW - timedelta(days=1), updated_at=NOW - timedelta(days=1)),
            CPDEntry(id="c1", tenant_id="t1", user_id="u1", topic="VAT", minutes=45, logged_at=NOW - timedelta(days=1)),
        ])
        await session.commit()
        yield session
    await engine.dispose()


def _user(tenant="t1") -> User:
    return User(id="u1", tenant_id=tenant, email="u1@example.com", full_name="U1", role="Admin")


async def test_counts_cover_the_window_and_tenant_only(db):
    report = await build_insights(db, _user(), 30, NOW)
    assert report["totalQuestions"] == 3                       # the 60-day-old and other-tenant ones are out
    assert [d["count"] for d in report["questionsPerDay"]] == [2, 1]
    assert report["outcomes"] == [{"label": "answered", "count": 2}, {"label": "refused", "count": 1}]
    assert {r["label"] for r in report["routes"]} == {"LLM", "REFUSAL"}
    assert {r["label"]: r["count"] for r in report["riskLevels"]} == {"LOW": 1, "HIGH": 1}
    assert report["latency"] == {"averageMs": 2000, "maxMs": 3000, "measured": 2}
    assert report["unavailable"] == []


async def test_topics_and_source_sites_are_counts_not_text(db):
    answers = (await build_insights(db, _user(), 30, NOW))["answers"]
    assert answers["answersSampled"] == 2
    assert {t["label"] for t in answers["topics"]} >= {"tax", "accounting"}
    # gov.uk is counted once per answer, not once per page.
    assert answers["sourceSites"][0] == {"label": "gov.uk", "count": 1}
    assert "VAT threshold" not in str(answers)


async def test_reviews_feedback_and_workspace_output(db):
    report = await build_insights(db, _user(), 30, NOW)
    assert report["reviews"] == {"byStatus": {"open": 1, "resolved": 1}, "bySource": {"user_feedback": 1, "escalation": 1}, "total": 2}
    assert report["feedback"] == {"up": 1, "down": 1}
    assert report["workspace"] == {"savedAnswers": 1, "draftsByStatus": {"Final": 1}, "cpdMinutes": 45, "cpdEntries": 1}


async def test_window_is_clamped_and_another_tenant_sees_nothing_of_t1(db):
    assert (await build_insights(db, _user(), 9999, NOW))["windowDays"] == 90
    other = await build_insights(db, _user("t2"), 30, NOW)
    assert other["totalQuestions"] == 1 and other["outcomes"] == [] and other["feedback"] == {}


async def test_a_failed_section_is_reported_unavailable_not_raised(db, monkeypatch):
    real = db.execute

    async def flaky(statement, *args, **kwargs):
        if "answer_feedback" in str(statement):
            raise TimeoutError("statement timeout")
        return await real(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", flaky)
    report = await build_insights(db, _user(), 30, NOW)
    assert report["feedback"] is None and report["unavailable"] == ["feedback"]
    assert report["totalQuestions"] == 3
