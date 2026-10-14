"""Evidence packs (kriton_workspace/evidence_pack.py) and the rule-based
Compliance Calendar (kriton_workspace/compliance_calendar.py)."""
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Tenant, User
from app.domains.kriton_workspace.compliance_calendar import upcoming_deadlines
from app.domains.kriton_workspace.evidence_pack import build_evidence_pack
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.domains.kriton_workspace.router import download_evidence_pack
from app.orchestration.models import AnswerFeedback, QueryAnswerRecord, ReviewCase

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="T"),
            SavedAnswer(id="sa1", tenant_id="t1", user_id="u1", query_id="q1", query_text="What is the UK VAT threshold?",
                        answer_text="It is £90,000.", risk_level="LOW"),
            QueryAnswerRecord(query_id="q1", tenant_id="t1", user_id="u1", question="What is the UK VAT threshold?", answer_text="x",
                              external_evidence=[{"title": "Register for VAT", "url": "https://www.gov.uk/register-for-vat",
                                                  "content": "You must register if your taxable turnover is over £90,000."}]),
            ReviewCase(id="r1", query_id="q1", correlation_id="c", tenant_id="t1", query_text="q", risk_level="LOW",
                       confidence_state="HIGH", reason="User reported", status="resolved", source="user_feedback",
                       reviewer_decision="approve", reviewer_id="u9", review_note="Checked against HMRC"),
            AnswerFeedback(id="f1", tenant_id="t1", user_id="u1", query_id="q1", rating="down", reasons=["outdated"], comment="?"),
            Draft(id="d1", tenant_id="t1", user_id="u1", title="VAT memo", content="Edited memo", status="Final", saved_answer_id="sa1"),
            Draft(id="d-blank", tenant_id="t1", user_id="u1", title="Blank memo", content="", status="Draft"),
            SavedAnswer(id="sa-other", tenant_id="t1", user_id="u2", query_id="q2", query_text="Not mine", answer_text="x", risk_level="LOW"),
        ])
        await session.commit()
        await record_event_async(session, tenant_id="t1", event_name="query_received", emitting_service="orchestration",
                                 actor_id="u1", subject_type="query", subject_id="q1", payload={})
        yield session
    await engine.dispose()


def _user(user_id="u1") -> User:
    return User(id=user_id, tenant_id="t1", email=f"{user_id}@example.com", full_name=user_id, role="Admin")


def _unzip(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


async def test_saved_answer_pack_holds_the_answer_sources_review_feedback_and_audit(db):
    content, filename, manifest = await build_evidence_pack(db, _user(), "saved-answer", "sa1", NOW)
    files = _unzip(content)
    assert filename == "Evidence pack - What is the UK VAT threshold.zip"
    assert set(files) == {"answer.md", "sources.md", "sources.json", "review.json", "feedback.json", "audit.json", "manifest.json"}
    assert "£90,000" in files["answer.md"].decode()
    assert json.loads(files["sources.json"])[0]["url"] == "https://www.gov.uk/register-for-vat"
    assert json.loads(files["review.json"])[0]["decision"] == "approve"
    assert json.loads(files["feedback.json"])[0]["reasons"] == ["outdated"]
    assert json.loads(files["audit.json"])[0]["event"] == "query_received"
    assert manifest["counts"] == {"sources": 1, "review_cases": 1, "feedback": 1, "audit_events": 1}


async def test_manifest_hashes_let_a_recipient_check_every_file(db):
    content, _, _ = await build_evidence_pack(db, _user(), "saved-answer", "sa1", NOW)
    files = _unzip(content)
    manifest = json.loads(files["manifest.json"])
    for name, meta in manifest["files"].items():
        assert hashlib.sha256(files[name]).hexdigest() == meta["sha256"], name


async def test_draft_pack_uses_the_answer_it_came_from_and_a_blank_draft_says_so(db):
    files = _unzip((await build_evidence_pack(db, _user(), "draft", "d1", NOW))[0])
    assert "Edited memo" in files["draft.md"].decode() and "£90,000" in files["original-answer.md"].decode()
    assert json.loads(files["sources.json"])
    _, _, manifest = await build_evidence_pack(db, _user(), "draft", "d-blank", NOW)
    assert manifest["query_id"] is None and manifest["notes"]


async def test_another_users_item_or_an_unknown_kind_is_not_found(db):
    for kind, item in (("saved-answer", "sa-other"), ("draft", "nope"), ("workpaper", "sa1")):
        with pytest.raises(HTTPException) as err:
            await build_evidence_pack(db, _user(), kind, item, NOW)
        assert err.value.status_code == 404


async def test_download_endpoint_records_the_export_with_the_file_hashes(db):
    response = await download_evidence_pack("saved-answer", "sa1", db=db, current_user=_user())
    assert response.media_type == "application/zip"
    event = (await db.execute(select(AuditEvent).where(AuditEvent.event_name == "kriton_workspace.evidence_pack_exported"))).scalar_one()
    assert event.subject_id == "sa1" and "answer.md" in event.payload["files"]


# ── Compliance Calendar ──────────────────────────────────────────────────

def _due(result, rule):
    return [d["dueDate"] for d in result["deadlines"] if d["rule"] == rule]


def test_monthly_rules_follow_their_published_day():
    result = upcoming_deadlines(date(2026, 10, 14), 70)              # to 23 December
    assert _due(result, "in-gstr1") == ["2026-11-11", "2026-12-11"]
    assert _due(result, "in-gstr3b") == ["2026-10-20", "2026-11-20", "2026-12-20"]
    assert _due(result, "uk-paye") == ["2026-10-22", "2026-11-22", "2026-12-22"]


def test_march_tds_is_due_on_30_april_not_7_april():
    result = upcoming_deadlines(date(2027, 3, 20), 50)               # to 9 May
    assert _due(result, "in-tds-deposit") == ["2027-04-30", "2027-05-07"]   # March's, then April's


def test_quarterly_and_annual_rules_cross_the_year_end():
    result = upcoming_deadlines(date(2026, 12, 1), 110)              # to 21 March
    assert _due(result, "uk-vat") == ["2027-02-07"]
    assert _due(result, "uk-sa-jan") == ["2027-01-31"]
    assert _due(result, "us-1040es") == ["2027-01-15"]
    assert _due(result, "in-advance-tax") == ["2026-12-15", "2027-03-15"]


def test_weekend_dates_are_flagged_with_the_authoritys_rule():
    # 15 January 2028 is a Saturday.
    item = next(d for d in upcoming_deadlines(date(2028, 1, 1), 30, "US")["deadlines"] if d["rule"] == "us-1040es")
    assert item["dueDate"] == "2028-01-15" and "next business day" in item["weekendNote"]


def test_jurisdiction_filter_order_and_validation():
    result = upcoming_deadlines(date(2026, 10, 14), 90, "India")
    assert {d["jurisdiction"] for d in result["deadlines"]} == {"India"}
    dates = [d["dueDate"] for d in result["deadlines"]]
    assert dates == sorted(dates) and all(d["source"].startswith("https://") for d in result["deadlines"])
    for kwargs in ({"days": 0}, {"days": 400}, {"jurisdiction": "Mars"}):
        with pytest.raises(HTTPException):
            upcoming_deadlines(date(2026, 10, 14), **{"days": 90, "jurisdiction": "", **kwargs})
