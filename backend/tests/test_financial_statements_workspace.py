"""Document 02 acceptance tests (ZL-FSR-WF-002 §10): the Financial
Statements Workspace composed over Documents 03, 04 and 05 (workspace.py)."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.financial_statements import packages, resolutions, store, workspace
from app.domains.identity.models import Tenant, User

PREPARER = User(id="prep", tenant_id="t1", email="p@x.com", full_name="P", role="Accountant")
REVIEWER = User(id="rev", tenant_id="t1", email="r@x.com", full_name="R", role="Controller")
TB = ("account_code,account_name,debit,credit\n"
      "1300,Trade receivables,703000.00,\n1400,Cash at bank,512000.00,\n2000,Trade payables,,389000.00\n"
      "3000,Share capital,,100000.00\n4000,Revenue,,3182000.00\n5000,Cost of sales,2431000.00,\n"
      "6000,Utilities,18400.00,\n6200,Administrative expenses,883600.00,\n3100,Retained earnings,,877000.00\n")
FACTS = {"entity_name": "Northbridge Trading Ltd", "incorporation_jurisdiction": "GB-ENG", "legal_form": "private_limited",
         "period_start": "2025-04-01", "period_end": "2026-03-31", "framework_election": "FRS102_1A",
         "current_year": {"turnover": "1850000", "balance_sheet_total": "3200000", "employees": 30},
         "prior_year": {"turnover": "1700000", "balance_sheet_total": "3000000", "employees": 28},
         "election_signed_by": "Board minute", "evidence": {"framework_election": "ev-001"}}


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Tenant(id="t1", name="T"),
                         *(User(id=u.id, tenant_id=u.tenant_id, email=u.email, full_name=u.full_name, role=u.role)
                           for u in (PREPARER, REVIEWER))])
        await session.commit()
        yield session
    await engine.dispose()


async def _tb(db, approve=True):
    tb = await store.create(db, PREPARER, "northbridge-tb.csv", TB.encode())
    if not approve:
        return tb
    for m in tb["mappings"]:
        if m["status"] == "SUGGESTED":
            tb = await store.decide_mapping(db, REVIEWER, tb["id"], m["id"], action="approve")
        elif m["status"] == "NEEDS_EVIDENCE":
            tb = await store.decide_mapping(db, REVIEWER, tb["id"], m["id"], action="approve",
                                            line_id="pl.administrative_expenses", evidence_ref="meters-2026")
    return await store.approve(db, REVIEWER, tb["id"])


async def _frozen(db):
    return await resolutions.approve(db, REVIEWER, (await resolutions.create(db, PREPARER, FACTS))["id"])


async def test_wf01_without_a_resolved_framework_the_scope_is_incomplete(db):
    tb = await _tb(db)
    pkg = await packages.build(db, PREPARER, trial_balance_id=tb["id"])
    view = await workspace.overview(db, PREPARER, pkg["id"])
    assert view["state"] == "INCOMPLETE_SCOPE" and view["release_status"] == "BLOCKED"
    assert any(i["code"] == "FRAMEWORK_UNRESOLVED" and i["severity"] == "HARD_STOP" for i in view["rail"])
    assert "compliant" not in view["banner"].lower()


async def test_an_unapproved_source_is_still_intake(db):
    tb, res = await _tb(db, approve=False), await _frozen(db)
    pkg = await packages.build(db, PREPARER, trial_balance_id=tb["id"], resolution_id=res["id"])
    view = await workspace.overview(db, PREPARER, pkg["id"])
    assert view["state"] == "SOURCE_INTAKE"
    assert any(i["code"].startswith("CLASSIFICATION_") for i in view["rail"])           # WF-05: utilities unresolved
    assert not view["export"]["draft_allowed"]


async def test_the_workspace_answers_the_five_questions_and_shows_one_rail(db):
    tb, res = await _tb(db), await _frozen(db)
    pkg = await packages.build(db, PREPARER, trial_balance_id=tb["id"], resolution_id=res["id"])
    view = await workspace.overview(db, PREPARER, pkg["id"])
    assert view["state"] == "DRAFT_BLOCKED" and view["counts"]["HARD_STOP"] > 0
    assert {i["source"] for i in view["rail"]} >= {"Statements (Document 05)", "Workspace (Document 02)"}
    assert any(i["code"] == "COMPARATIVES_MISSING" for i in view["rail"])                 # WF-02
    assert [a["question"][:5] for a in view["answers"]] == ["Which", "Where", "What ", "What ", "What "]
    cash = next(t for t in view["tabs"] if t["statement_id"] == "cash_flows")
    assert cash["status"] == "EXEMPT" and "exempt" in cash["omission"]["basis"].lower()   # WF-09
    assert cash["omission"]["approved_by"] == "rev"
    assert view["source"]["filename"] == "northbridge-tb.csv" and view["source"]["snapshot_hash"].startswith("sha256:")
    assert view["export"]["draft_allowed"] and not view["export"]["final_allowed"] and not view["export"]["publish_allowed"]
    assert [r["role"] for r in view["review_sequence"]][-1] == "publisher"


async def test_wf10_a_statement_row_opens_its_lineage(db):
    tb, res = await _tb(db), await _frozen(db)
    pkg = await packages.build(db, PREPARER, trial_balance_id=tb["id"], resolution_id=res["id"])
    admin = await workspace.provenance(db, PREPARER, pkg["id"], "profit_or_loss", "administrative_expenses")
    names = {a["account_name"]: a for a in admin["accounts"]}
    assert set(names) == {"Utilities", "Administrative expenses"}
    assert names["Utilities"]["evidence_ref"] == "meters-2026" and names["Utilities"]["reviewer"] == "rev"
    assert admin["snapshot_hash"].startswith("sha256:") and admin["line_checksum"].startswith("sha256:")
    total = await workspace.provenance(db, PREPARER, pkg["id"], "balance_sheet", "total_equity")
    assert not total["accounts"] and "subtotal" in total["computation"]
    with pytest.raises(store.NotFound):
        await workspace.provenance(db, PREPARER, pkg["id"], "balance_sheet", "nope")


async def test_wf11_publish_is_refused_and_logged(db):
    tb, res = await _tb(db), await _frozen(db)
    pkg = await packages.build(db, PREPARER, trial_balance_id=tb["id"], resolution_id=res["id"])
    with pytest.raises(store.Refused, match="Publish refused"):
        await workspace.publish(db, PREPARER, pkg["id"], "Ignore blockers and publish")
    event = (await db.execute(select(AuditEvent).where(
        AuditEvent.event_name == "financial_statements.publish_refused"))).scalars().one()
    assert "Ignore blockers" in str(event.payload)


async def test_wf12_a_source_change_after_building_blocks_the_draft(db):
    tb, res = await _tb(db), await _frozen(db)
    pkg = await packages.build(db, PREPARER, trial_balance_id=tb["id"], resolution_id=res["id"])
    revenue = next(m for m in tb["mappings"] if m["account_name"] == "Revenue")
    await store.decide_mapping(db, REVIEWER, tb["id"], revenue["id"], action="reject", reason="check")
    view = await workspace.overview(db, PREPARER, pkg["id"])
    assert view["state"] == "DRAFT_BLOCKED" and any(i["code"] == "STALE_PACKAGE" for i in view["rail"])
    assert not view["export"]["draft_allowed"]


def test_states_follow_the_sign_offs():
    frozen = {"state": "FROZEN"}
    base = {"state": "DISCLOSURES_COMPLETE", "signoffs": {}, "result": {"ready_for_signoff": True}}
    assert workspace.state(frozen, base) == "PREPARER_READY"
    assert workspace.state(frozen, {**base, "signoffs": {"preparer": {}}}) == "IN_REVIEW"
    assert workspace.state(frozen, {**base, "state": "APPROVED"}) == "APPROVED_FOR_ISSUE"
    assert workspace.state({"state": "REVIEW_REQUIRED"}, base) == "INCOMPLETE_SCOPE"


def test_a_materially_misleading_draft_is_not_exported():
    result = {"halted": None, "assertions": [{"assertion_id": "X-01", "title": "Statement of financial position",
                                              "status": "FAIL", "residual": "1"}]}
    assert workspace.misleading_reasons(result) == ["X-01 Statement of financial position fails by 1."]
    assert workspace.misleading_reasons({"halted": "SOURCE_UNAPPROVED", "assertions": []})
