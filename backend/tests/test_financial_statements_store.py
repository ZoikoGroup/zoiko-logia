"""Document 04 stored workflow: upload, tenant scope, maker-checker decisions,
journals, supporting records, approval, supersession and lineage
(app/domains/financial_statements/store.py + router)."""
import time
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.financial_statements import intake, journals, router as api, store
from app.domains.financial_statements.integrity import check
from app.domains.financial_statements.normalize import normalize
from app.domains.financial_statements.service import run_intake
from app.domains.identity.models import Tenant, User

PREPARER = User(id="prep", tenant_id="t1", email="p@x.com", full_name="Priya Preparer", role="Accountant")
REVIEWER = User(id="rev", tenant_id="t1", email="r@x.com", full_name="Ravi Reviewer", role="Controller")
OUTSIDER = User(id="out", tenant_id="t2", email="o@y.com", full_name="Other Tenant", role="Admin")

TB = ("account_code,account_name,debit,credit\n"
      "1300,Trade receivables,703000.00,\n1400,Cash at bank,512000.00,\n2000,Trade payables,,389000.00\n"
      "3000,Share capital,,100000.00\n4000,Revenue,,3182000.00\n5000,Cost of sales,2431000.00,\n"
      "6000,Utilities,18400.00,\n6200,Administrative expenses,883600.00,\n3100,Retained earnings,,877000.00\n")
# Debits 4,548,000 = credits 4,548,000.


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Tenant(id="t1", name="T"), Tenant(id="t2", name="Other"),
                         *(User(id=u.id, tenant_id=u.tenant_id, email=u.email, full_name=u.full_name, role=u.role)
                           for u in (PREPARER, REVIEWER, OUTSIDER))])
        await session.commit()
        yield session
    await engine.dispose()


async def _upload(db, text=TB, **kw):
    return await store.create(db, PREPARER, "tb.csv", text.encode(), **kw)


async def _approve_all(db, tb):
    for m in tb["mappings"]:
        if m["status"] == "SUGGESTED":
            tb = await store.decide_mapping(db, REVIEWER, tb["id"], m["id"], action="approve")
        elif m["status"] == "NEEDS_EVIDENCE":
            tb = await store.decide_mapping(db, REVIEWER, tb["id"], m["id"], action="approve",
                                            line_id=m["candidates"][-1]["line_id"], evidence_ref="INV-1")
    return tb


async def test_an_upload_keeps_the_original_bytes_hash_history_and_audit(db):
    tb = await _upload(db)
    filename, _, content = await store.original(db, PREPARER, tb["id"])
    assert content == TB.encode() and tb["state"] == "MAPPING_REVIEW" and tb["version"] == 1
    assert [h["action"] for h in tb["history"]] == ["uploaded"]
    events = (await db.execute(select(AuditEvent.event_name))).scalars().all()
    assert "financial_statements.uploaded" in events


async def test_another_tenant_cannot_see_the_trial_balance(db):
    tb = await _upload(db)
    with pytest.raises(store.NotFound):
        await store.detail(db, OUTSIDER, tb["id"])
    assert await store.list_trial_balances(db, OUTSIDER) == []
    with pytest.raises(HTTPException) as error:
        await api.get_trial_balance(tb["id"], db=db, user=OUTSIDER)
    assert error.value.status_code == 404


async def test_mappings_need_a_reviewer_other_than_the_uploader_and_evidence_where_named(db):
    tb = await _upload(db)
    revenue = next(m for m in tb["mappings"] if m["account_name"] == "Revenue")
    with pytest.raises(store.Refused, match="cannot approve"):
        await store.decide_mapping(db, PREPARER, tb["id"], revenue["id"], action="approve")
    utilities = next(m for m in tb["mappings"] if m["account_name"] == "Utilities")
    with pytest.raises(store.Refused, match="evidence"):
        await store.decide_mapping(db, REVIEWER, tb["id"], utilities["id"], action="approve",
                                   line_id="pl.administrative_expenses")
    tb = await store.decide_mapping(db, REVIEWER, tb["id"], utilities["id"], action="reject", reason="Need meters")
    with pytest.raises(store.Refused, match="evidence"):       # rejected, still needs its evidence
        await store.decide_mapping(db, REVIEWER, tb["id"], utilities["id"], action="approve",
                                   line_id="pl.administrative_expenses")
    tb = await store.decide_mapping(db, REVIEWER, tb["id"], utilities["id"], action="approve", evidence_ref="meters",
                                    allocations=[("pl.cost_of_sales", "8000"), ("pl.administrative_expenses", "10400")])
    decided = next(m for m in tb["mappings"] if m["account_name"] == "Utilities")
    assert decided["status"] == "APPROVED" and decided["reviewer"] == "rev" and decided["evidence_ref"] == "meters"


async def test_journals_are_proposed_reviewed_by_someone_else_and_never_posted(db):
    tb = await _approve_all(db, await _upload(db))
    result = await store.add_journal(db, PREPARER, tb["id"], kind="RECLASSIFICATION", reason="Factory utilities",
                                     lines=[("pl.cost_of_sales", "5000", "0"), ("pl.administrative_expenses", "0", "5000")])
    assert result["effect"]["profit_before_tax_before"] == result["effect"]["profit_before_tax_after"]
    journal = result["journals"][0]
    assert journal["posting_status"] == "NOT_POSTED" and result["state"] == "ADJUSTMENT_PENDING"
    with pytest.raises(store.Refused, match="cannot review"):
        await store.review_journal(db, PREPARER, tb["id"], journal["journal_id"], approve=True)
    tb = await store.review_journal(db, REVIEWER, tb["id"], journal["journal_id"], approve=True)
    assert tb["journals"][0]["review_status"] == "APPROVED" and tb["journals"][0]["posting_status"] == "NOT_POSTED"
    with pytest.raises(store.Refused, match="cannot change profit"):
        await store.add_journal(db, PREPARER, tb["id"], kind="RECLASSIFICATION", reason="x",
                                lines=[("pl.cost_of_sales", "5", "0"), ("bs.trade_payables", "0", "5")])


async def test_approval_needs_everything_resolved_and_an_independent_approver(db):
    tb = await _upload(db)
    with pytest.raises(store.Refused, match="not mapped and approved"):
        await store.approve(db, REVIEWER, tb["id"])
    tb = await _approve_all(db, tb)
    with pytest.raises(store.Refused, match="preparer cannot approve"):
        await store.approve(db, PREPARER, tb["id"])
    tb = await store.approve(db, REVIEWER, tb["id"])
    assert tb["state"] == "APPROVED_SNAPSHOT" and tb["snapshots"][0]["content_hash"].startswith("sha256:")


async def test_a_change_after_approval_supersedes_the_snapshot(db):
    tb = await store.approve(db, REVIEWER, (await _approve_all(db, await _upload(db)))["id"])
    revenue = next(m for m in tb["mappings"] if m["account_name"] == "Revenue")
    tb = await store.decide_mapping(db, REVIEWER, tb["id"], revenue["id"], action="reject", reason="check")
    assert tb["snapshots"][0]["status"] == "SUPERSEDED" and tb["state"] == "MAPPING_REVIEW"
    assert "snapshot_superseded" in [h["action"] for h in tb["history"]]


async def test_a_corrected_upload_is_a_new_version_and_the_old_one_is_kept(db):
    old = await store.approve(db, REVIEWER, (await _approve_all(db, await _upload(db)))["id"])
    new = await _upload(db, TB.replace("18400.00", "18500.00").replace("883600.00", "883500.00"), supersedes_id=old["id"])
    assert new["version"] == 2 and new["supersedes_id"] == old["id"]
    old = await store.detail(db, PREPARER, old["id"])
    assert old["state"] == "SUPERSEDED" and old["snapshots"][0]["status"] == "SUPERSEDED"
    with pytest.raises(store.Refused, match="superseded"):
        await store.add_journal(db, PREPARER, old["id"], kind="ADJUSTMENT", reason="x",
                                lines=[("pl.cost_of_sales", "5", "0"), ("bs.trade_payables", "0", "5")])


async def test_supporting_records_agree_or_block(db):
    tb = await _upload(db)
    ageing = "customer,invoice,outstanding\nAlder,1,500000.00\nBirch,2,203000.00\nTotal,,703000.00\n"
    tb = await store.add_supporting(db, PREPARER, tb["id"], kind="receivables_ageing", filename="ageing.csv",
                                    content=ageing.encode())
    assert tb["supporting"][0]["finding"]["code"] == "SUPPORTING_AGREED"
    bank = "item,amount\nBalance per bank statement,515000\nUnpresented cheques,-2000\nBalance per cash book,513000\n"
    tb = await store.add_supporting(db, PREPARER, tb["id"], kind="bank_reconciliation", filename="bankrec.csv",
                                    content=bank.encode())
    mismatch = tb["supporting"][1]["finding"]
    assert mismatch["code"] == "SUBLEDGER_MISMATCH" and "-1000" in mismatch["message"]
    tb = await _approve_all(db, tb)
    with pytest.raises(store.Refused, match="SUBLEDGER_MISMATCH"):
        await store.approve(db, REVIEWER, tb["id"])


async def test_lineage_traces_an_account_to_its_source_row(db):
    tb = await _approve_all(db, await _upload(db))
    revenue = next(m for m in tb["mappings"] if m["account_name"] == "Revenue")
    trace = await store.lineage(db, PREPARER, tb["id"], revenue["account_key"])
    assert trace["source_rows"][0]["source"] == "CSV!R6" and trace["mapping"]["line_id"] == "pl.revenue"
    assert trace["source_file"]["sha256"] == tb["sha256"]


# ── engine checks added with the stored workflow ─────────────────────────

def _check(text):
    return {f.code for f in check(normalize(intake.receive("x.csv", text.encode(), "u"))).findings}


def test_sd014_opening_plus_movements_must_equal_closing():
    ok = "account_name,opening balance,debit,credit,closing balance\nCash at bank,100,50,20,130\nRevenue,-100,20,50,-130\n"
    assert "ROLLFORWARD_MISMATCH" not in _check(ok) and "UNBALANCED" not in _check(ok)
    wrong = "account_name,opening balance,debit,credit,closing balance\nCash at bank,100,50,20,131\nRevenue,-100,20,50,-130\n"
    assert {"ROLLFORWARD_MISMATCH", "UNBALANCED"} <= _check(wrong)


def test_sd018_ledger_vouchers_cutoff_round_sums_and_manual_journals():
    ledger = ("Ledger for the year ended 31 March 2026\nDate,Voucher,Account,Description,Debit,Credit\n"
              "2026-03-30,JV-1,Cash at bank,Sale,50000,\n2026-03-30,JV-1,Revenue,Sale,,50000\n"
              "2026-04-02,JV-2,Cash at bank,Late sale,100,\n2026-04-02,JV-2,Revenue,Late sale,,90\n"
              "2026-03-31,MJ-3,Cash at bank,Manual adjustment,5,\n2026-03-31,MJ-3,Revenue,Manual adjustment,,5\n")
    codes = _check(ledger)
    assert {"VOUCHER_UNBALANCED", "CUTOFF_AFTER_PERIOD_END", "ROUND_SUM_ENTRIES", "MANUAL_JOURNALS"} <= codes
    assert "DUPLICATE_ACCOUNT" not in codes                     # repeated accounts are normal in a ledger


def test_at16_at22_at23_correction_types_decide_the_treatment():
    estimate = journals.propose_journal(kind="ADJUSTMENT", reason="Useful life revised", created_by="p",
                                        correction_type="ESTIMATE_CHANGE",
                                        lines=[("pl.administrative_expenses", Decimal("10"), 0), ("bs.ppe", 0, Decimal("10"))])
    assert not estimate.requires_restatement and "prospectively" in estimate.to_dict()["treatment"]
    error = journals.propose_journal(kind="ADJUSTMENT", reason="Prior year revenue overstated", created_by="p",
                                     correction_type="PRIOR_PERIOD_ERROR",
                                     lines=[("eq.retained_earnings", Decimal("10"), 0), ("bs.trade_receivables", 0, Decimal("10"))])
    assert error.requires_restatement and "restated comparatives" in error.to_dict()["treatment"]
    interest = next(m for m in run_intake("t.csv", b"account_name,debit,credit\nInterest income,,12000\nCash at bank,12000,\n",
                                          "u").mappings if m.account_name == "Interest income")
    assert interest.status == "NEEDS_EVIDENCE"                  # AT-16: not defaulted to other operating income


def test_a_malware_scanner_can_reject_an_upload(monkeypatch):
    monkeypatch.setattr(intake, "scan_upload", lambda content: "test signature found" if b"EICAR" in content else None)
    assert run_intake("x.csv", b"EICAR,1\n", "u").state == "REJECTED"
    assert run_intake("x.csv", TB.encode(), "u").state != "REJECTED"


def test_performance_50k_rows_validate_within_the_document_04_target():
    rows = ["account_code,account_name,debit,credit"]
    for i in range(25000):
        rows.append(f"{10000 + i},Expense {i},{i % 997}.25,")
        rows.append(f"{50000 + i},Revenue {i},,{i % 997}.25")
    started = time.perf_counter()
    result = run_intake("big.csv", "\n".join(rows).encode(), "u")
    assert result.report.balanced and len(result.tb.lines) == 50000
    assert time.perf_counter() - started < 30


def test_the_migration_creates_exactly_the_model_tables_and_columns():
    """The b7u8v9w0x1y2 migration, run on its own against the other tables,
    matches the models column for column, and downgrade removes it."""
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.db.base import Base

    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    migrations = []
    for name in ("b7u8v9w0x1y2_financial_statements_intake.py", "c8v9w0x1y2z3_financial_statements_resolutions.py"):
        spec = importlib.util.spec_from_file_location(name[:-3], versions / name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        migrations.append(module)
    ours = [t for t in Base.metadata.sorted_tables if t.name.startswith("fs_")]
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection, tables=[t for t in Base.metadata.sorted_tables if t not in ours])
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            for migration in migrations:
                migration.upgrade()
            inspector = sa.inspect(connection)
            for table in ours:
                assert {c["name"] for c in inspector.get_columns(table.name)} == {c.name for c in table.columns}, table.name
            for migration in reversed(migrations):
                migration.downgrade()
        assert not [t for t in sa.inspect(connection).get_table_names() if t.startswith("fs_")]
    assert migrations[0].down_revision == "a6t7u8v9w0x1" and migrations[1].down_revision == migrations[0].revision
