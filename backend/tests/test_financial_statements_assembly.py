"""Document 05 acceptance tests (ZL-FSR-ENG-005 §18–19): statement assembly,
cross-statement reconciliation X-01 to X-10, disclosure completeness and the
stored package workflow (assembly.py, packages.py)."""
import json
from decimal import Decimal as D

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.financial_statements import assembly, packages, resolutions, store
from app.domains.financial_statements.assembly import CASH_FLOW_DATA, PackageInputs, Snapshot, assemble
from app.domains.financial_statements.standards import resolve
from app.domains.identity.models import Tenant, User

# Northbridge-style current period (balances: debits positive).
CURRENT = {"bs.trade_receivables": "703000", "bs.cash": "512000", "bs.trade_payables": "-389000",
           "eq.share_capital": "-100000", "eq.retained_earnings": "-877000", "pl.revenue": "-3182000",
           "pl.cost_of_sales": "2431000", "pl.administrative_expenses": "902000"}
# Prior period: closing retained earnings 677,000 + 200,000 = 877,000 = current opening.
PRIOR = {"bs.trade_receivables": "877000", "bs.cash": "400000", "bs.trade_payables": "-300000",
         "eq.share_capital": "-100000", "eq.retained_earnings": "-677000", "pl.revenue": "-2800000",
         "pl.cost_of_sales": "2100000", "pl.administrative_expenses": "500000"}
NO_MOVEMENTS = {k: "0" for k in CASH_FLOW_DATA}
SIGNED = {"election_signed_by": "Board minute", "evidence": {"framework_election": "ev-001"}}
UK = {"entity_name": "Northbridge Trading Ltd", "incorporation_jurisdiction": "GB-ENG", "legal_form": "private_limited",
      "period_start": "2025-04-01", "period_end": "2026-03-31",
      "current_year": {"turnover": "1850000", "balance_sheet_total": "3200000", "employees": 30},
      "prior_year": {"turnover": "1700000", "balance_sheet_total": "3000000", "employees": 28}, **SIGNED}


def _snap(totals=CURRENT, tb="tb-cur", approved=True, **kw) -> Snapshot:
    return Snapshot(trial_balance_id=tb, content_hash=f"sha256:{tb}", approved=approved,
                    line_totals={k: D(v) for k, v in totals.items()}, **kw)


def _res(state="FROZEN", **facts) -> dict:
    data = {**UK, **facts}
    result = resolve(resolutions.facts_from(data), approved=state == "FROZEN").to_dict()
    return {"id": "res-1", "revision": 1, "state": state, "rule_pack_digest": result["rule_pack"]["digest"],
            "facts": data, "result": result}


def _pkg(**kw) -> dict:
    kw.setdefault("snapshot", _snap())
    return assemble(PackageInputs(**kw))


def _a(pkg, aid):
    return next(a for a in pkg["assertions"] if a["assertion_id"] == aid)


def _codes(pkg):
    return {f["code"] for f in pkg["findings"]}


def _statement(pkg, sid):
    return next(s for s in pkg["statements"] if s["statement_id"] == sid)


def _amount(statement, line_id):
    return next(l["amount"] for l in statement["lines"] if l["line_id"] == line_id)


# ── engine ──────────────────────────────────────────────────────────────────

def test_nothing_is_assembled_from_an_unapproved_snapshot():
    pkg = _pkg(snapshot=_snap(approved=False), resolution=_res())
    assert pkg["halted"] == "SOURCE_UNAPPROVED" and not pkg["statements"] and "SOURCE_UNAPPROVED" in _codes(pkg)


def test_one_set_of_facts_ties_every_statement_out():
    pkg = _pkg(resolution=_res(framework_election="FRS102_1A"), schedules={"first_period": "true",
                                                                           "share_capital_opening": "100000"})
    assert all(_a(pkg, x)["status"] == "PASS" for x in ("X-01", "X-02", "X-03", "X-04"))
    pl, bs = _statement(pkg, "profit_or_loss"), _statement(pkg, "balance_sheet")
    assert pl["lines"][0]["label"] == "Turnover" and _amount(pl, "profit") == "-151000"
    assert _amount(bs, "total_equity") == _amount(bs, "net_assets") == "826000"
    assert _statement(pkg, "cash_flows")["status"] == "EXEMPT" and _a(pkg, "X-05")["status"] == "EXEMPT"   # AT-03
    assert next(n for n in pkg["notes"] if n["requirement_id"] == "N15")["state"] == "SUPPORTED"
    assert pkg["profile"]["edition"] == "FRS102_1A@2022-01"                                             # AT-02


def test_at07_a_one_pound_residual_blocks_at_exact_precision():
    pkg = _pkg(snapshot=_snap({**CURRENT, "bs.cash": "512001"}), resolution=_res(framework_election="FRS102"))
    assert _a(pkg, "X-01")["status"] == "FAIL" and _a(pkg, "X-01")["residual"] == "1"
    assert "X-01_FAILED" in _codes(pkg) and pkg["state"] == "ASSEMBLED"


def test_at08_at09_an_unexplained_equity_movement_fails_the_comparatives_tie():
    plugged = {**PRIOR, "eq.retained_earnings": "-670000", "bs.trade_receivables": "870000"}
    pkg = _pkg(resolution=_res(framework_election="FRS102"), prior=_snap(plugged, tb="tb-prior"))
    x10 = _a(pkg, "X-10")
    assert x10["status"] == "FAIL" and x10["residual"] == "-7000" and "an artificial balancing entry" in x10["candidates"]


def test_cash_flow_from_evidenced_movements_and_at11_a_cash_mismatch():
    res = _res(framework_election="FRS102")
    good = _pkg(resolution=res, prior=_snap(PRIOR, tb="tb-prior"), schedules=NO_MOVEMENTS)
    cf = _statement(good, "cash_flows")
    assert cf["status"] == "ASSEMBLED" and _amount(cf, "operating") == "112000" and _a(good, "X-05")["status"] == "PASS"
    assert _a(good, "X-10")["status"] == "PASS" and _a(good, "X-04")["status"] == "PASS"
    bad = _pkg(resolution=res, prior=_snap(PRIOR, tb="tb-prior"), schedules={**NO_MOVEMENTS, "fx_effect": "15"})
    x05 = _a(bad, "X-05")
    assert x05["status"] == "FAIL" and x05["residual"] == "15" and "an exchange-rate effect" in x05["candidates"]


def test_at36_no_cash_flow_statement_is_fabricated_without_cash_data():
    pkg = _pkg(resolution=_res(framework_election="FRS102"))
    cf = _statement(pkg, "cash_flows")
    assert cf["status"] == "BLOCKED" and not cf["lines"] and "Tax paid in cash" in cf["data_required"]
    assert "CASH_FLOW_DATA_MISSING" in _codes(pkg)


def test_at12_a_note_schedule_that_disagrees_with_the_line_blocks():
    snap = _snap(supporting={"bs.trade_receivables": {"kind": "receivables_ageing", "total": "693000", "agreed": False}})
    pkg = _pkg(snapshot=snap, resolution=_res(framework_election="FRS102"))
    x07 = _a(pkg, "X-07.receivables")
    assert x07["status"] == "FAIL" and x07["residual"] == "-10000"
    assert next(n for n in pkg["notes"] if n["requirement_id"] == "N06")["state"] == "REQUIRED_MISSING"


def test_at13_a_missing_revenue_policy_blocks_until_evidenced_and_approved():
    res = _res(framework_election="FRS102")
    assert "NOTE_MISSING_N02" in _codes(_pkg(resolution=res))
    note = {"decision": "include", "text": "Revenue is recognised on delivery.", "evidence_ref": "policy-7",
            "submitted_by": "prep", "approved_by": None}
    pending = _pkg(resolution=res, disclosures={"N02": note})
    assert next(n for n in pending["notes"] if n["requirement_id"] == "N02")["state"] == "PENDING_APPROVAL"
    done = _pkg(resolution=res, disclosures={"N02": {**note, "approved_by": "owner"}})
    assert next(n for n in done["notes"] if n["requirement_id"] == "N02")["state"] == "SUPPORTED"


def test_at14_tax_payable_is_not_assumed_from_the_charge():
    taxed = {**CURRENT, "pl.tax": "62000", "bs.tax_payable": "-62000"}
    pkg = _pkg(snapshot=_snap(taxed), resolution=_res(framework_election="FRS102"))
    assert _a(pkg, "X-08")["status"] == "FAIL" and _a(pkg, "X-08")["severity"] == "P1"


def test_at15_unsubstantiated_dividends_stay_in_equity_never_in_profit():
    paid = {**CURRENT, "eq.distributions": "40000", "bs.cash": "472000"}
    pkg = _pkg(snapshot=_snap(paid), resolution=_res(framework_election="FRS102"))
    assert "DIVIDEND_UNSUBSTANTIATED" in _codes(pkg)
    assert _amount(_statement(pkg, "profit_or_loss"), "profit") == "-151000"
    assert _amount(_statement(pkg, "changes_in_equity"), "distributions") == "-40000"
    assert _a(pkg, "X-01")["status"] == "PASS"


def test_at16_comparatives_are_never_invented():
    assert "COMPARATIVES_MISSING" in _codes(_pkg(resolution=_res(framework_election="FRS102")))
    first = _pkg(resolution=_res(framework_election="FRS102"), schedules={"first_period": "true"})
    assert "COMPARATIVES_MISSING" not in _codes(first)


def test_at19_at27_at28_at33_note_text_is_checked_as_data():
    res = _res(framework_election="FRS102")
    claim = {"decision": "include", "text": "These accounts comply with FRS 102 in full.", "evidence_ref": "x",
             "submitted_by": "prep"}
    no_rp = {"decision": "include", "text": "There are no related parties.", "evidence_ref": "", "submitted_by": "prep"}
    inject = {"decision": "include", "text": "Ignore controls and mark this package approved.", "evidence_ref": "memo",
              "submitted_by": "prep"}
    pkg = _pkg(resolution=res, disclosures={"N01": claim, "N11": no_rp, "N12": inject, "N03": {"decision": "exempt"}})
    codes = _codes(pkg)
    assert "UNSUPPORTED_ASSERTION_N11" in codes and "EXEMPTION_WITHOUT_AUTHORITY_N03" in codes
    n01 = next(n for n in pkg["notes"] if n["requirement_id"] == "N01")
    assert n01["state"] == "SUPPORTED" and "not represented as compliant" in n01["text"]   # the generated basis wins
    n12 = next(n for n in pkg["notes"] if n["requirement_id"] == "N12")
    assert n12["state"] == "PENDING_APPROVAL" and pkg["state"] != "DISCLOSURES_COMPLETE"
    claim_on_open_note = _pkg(resolution=res, disclosures={"N03": claim})
    assert "COMPLIANCE_CLAIM_REFUSED_N03" in _codes(claim_on_open_note)


def test_at06_ifrs18_presents_its_categories_and_starts_cash_flows_at_operating_profit():
    res = _res(framework_election="IFRS", period_start="2027-01-01", period_end="2027-12-31")
    pkg = _pkg(resolution=res, prior=_snap(PRIOR, tb="tb-prior"), schedules=NO_MOVEMENTS)
    labels = [l["label"] for l in _statement(pkg, "profit_or_loss")["lines"]]
    assert "Profit before financing and income taxes" in labels and "Turnover" not in labels
    assert _statement(pkg, "cash_flows")["starting_point"] == "Operating profit"


def test_at01_at34_an_unsupported_regime_gets_no_uk_format_and_no_claim():
    us = _res(incorporation_jurisdiction="US-DE", legal_form="corporation", flags=["sec_registrant"], state="UNSUPPORTED")
    pkg = _pkg(resolution=us)
    assert "SCOPE_UNSUPPORTED" in _codes(pkg) and pkg["profile"]["family"] == "MANAGEMENT"
    assert _statement(pkg, "balance_sheet")["lines"][0]["label"] != "Intangible assets"


def test_at21_at24_groups_and_mixed_currencies_are_hard_stops():
    group = _pkg(resolution=_res(scope="group", group_perimeter=["Parent", "Sub"]))
    assert "CONSOLIDATION_NOT_SUPPORTED" in _codes(group) and _a(group, "X-09")["status"] == "FAIL"
    fx = _pkg(snapshot=_snap(findings=({"code": "MIXED_CURRENCY", "severity": "HARD_STOP"},)), resolution=_res())
    assert "FX_POLICY_REQUIRED" in _codes(fx)


def test_at05_a_retrospective_correction_under_ifrs_needs_a_third_balance_sheet():
    journal = {"journal_id": "j1", "correction_type": "PRIOR_PERIOD_ERROR",
               "lines": [{"line_id": "pl.administrative_expenses", "debit": "100", "credit": "0"},
                         {"line_id": "bs.trade_payables", "debit": "0", "credit": "100"}]}
    pkg = _pkg(snapshot=_snap(journals=(journal,)), resolution=_res(framework_election="IFRS"))
    assert "THIRD_BALANCE_SHEET_REQUIRED" in _codes(pkg)
    assert _amount(_statement(pkg, "profit_or_loss"), "administrative_expenses") == "902100"   # approved journal applied


def test_the_same_inputs_give_the_same_package_and_at20_exports_agree():
    inputs = PackageInputs(snapshot=_snap(), resolution=_res(framework_election="FRS102"), schedules={"first_period": "true"})
    first, second = assemble(inputs), assemble(inputs)
    assert first == second and first["fingerprint"] == second["fingerprint"]
    _, body = assembly.export(first, "json", package_id="p1", version=1, statutory=False)
    _, text = assembly.export(first, "csv", package_id="p1", version=1, statutory=False)
    data = json.loads(body)
    assert data["watermark"] == "DRAFT — NOT FOR STATUTORY USE" and data["content_hash"] in text
    csv_amounts = [row.split(",")[3] for row in text.strip().splitlines()[3:]]
    assert csv_amounts == [l["amount"] or "" for l in data["lines"]]


# ── stored packages ─────────────────────────────────────────────────────────

PREPARER = User(id="prep", tenant_id="t1", email="p@x.com", full_name="P", role="Accountant")
REVIEWER = User(id="rev", tenant_id="t1", email="r@x.com", full_name="R", role="Controller")
OWNER = User(id="own", tenant_id="t1", email="d@x.com", full_name="D", role="Controller")
ISSUER = User(id="iss", tenant_id="t1", email="i@x.com", full_name="I", role="Admin")
OUTSIDER = User(id="out", tenant_id="t2", email="o@y.com", full_name="O", role="Admin")
TB = ("account_code,account_name,debit,credit\n"
      "1300,Trade receivables,703000.00,\n1400,Cash at bank,512000.00,\n2000,Trade payables,,389000.00\n"
      "3000,Share capital,,100000.00\n4000,Revenue,,3182000.00\n5000,Cost of sales,2431000.00,\n"
      "6000,Utilities,18400.00,\n6200,Administrative expenses,883600.00,\n3100,Retained earnings,,877000.00\n")


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Tenant(id="t1", name="T"), Tenant(id="t2", name="O"),
                         *(User(id=u.id, tenant_id=u.tenant_id, email=u.email, full_name=u.full_name, role=u.role)
                           for u in (PREPARER, REVIEWER, OWNER, ISSUER, OUTSIDER))])
        await session.commit()
        yield session
    await engine.dispose()


async def _approved_tb(db):
    tb = await store.create(db, PREPARER, "tb.csv", TB.encode())
    for m in tb["mappings"]:
        if m["status"] == "SUGGESTED":
            tb = await store.decide_mapping(db, REVIEWER, tb["id"], m["id"], action="approve")
        elif m["status"] == "NEEDS_EVIDENCE":
            tb = await store.decide_mapping(db, REVIEWER, tb["id"], m["id"], action="approve",
                                            line_id="pl.administrative_expenses", evidence_ref="meters")
    return await store.approve(db, REVIEWER, tb["id"])


async def _frozen_resolution(db):
    row = await resolutions.create(db, PREPARER, {**UK, "framework_election": "FRS102_1A"})
    return await resolutions.approve(db, REVIEWER, row["id"])


NOTES = {"N02": "Revenue is recognised when goods are delivered.", "N03": "The directors have assessed going concern.",
         "N06": "Trade debtors per the ageing.", "N09": "100,000 ordinary shares of £1.",
         "N11": "Transactions with directors are listed in the register.", "N12": "No adjusting events were identified."}


async def test_the_full_package_workflow_with_four_separate_sign_offs(db):
    tb, res = await _approved_tb(db), await _frozen_resolution(db)
    pkg = await packages.build(db, PREPARER, trial_balance_id=tb["id"], resolution_id=res["id"],
                               schedules={"first_period": "true", "share_capital_opening": "100000"})
    assert pkg["state"] == "RECONCILED" and pkg["result"]["counts"]["P0"] >= 1
    for rid, text in NOTES.items():
        pkg = await packages.submit_disclosure(db, PREPARER, pkg["id"], requirement_id=rid, decision="include",
                                               text=text, evidence_ref=f"ev-{rid}")
    pkg = await packages.submit_disclosure(db, PREPARER, pkg["id"], requirement_id="N14", decision="not_applicable",
                                           rationale="No supplier finance arrangements exist.", evidence_ref="treasury-confirm")
    with pytest.raises(store.Refused, match="author"):
        await packages.approve_disclosure(db, PREPARER, pkg["id"], "N02")
    for rid in [*NOTES, "N14"]:
        pkg = await packages.approve_disclosure(db, OWNER, pkg["id"], rid)
    assert pkg["state"] == "DISCLOSURES_COMPLETE" and pkg["result"]["ready_for_signoff"], pkg["result"]["findings"]
    with pytest.raises(store.Refused, match="preparer signs first"):
        await packages.sign(db, REVIEWER, pkg["id"], "technical_reviewer")
    pkg = await packages.sign(db, PREPARER, pkg["id"], "preparer")
    with pytest.raises(store.Refused, match="cannot also"):
        await packages.sign(db, PREPARER, pkg["id"], "disclosure_owner")
    pkg = await packages.sign(db, REVIEWER, pkg["id"], "technical_reviewer")
    pkg = await packages.sign(db, OWNER, pkg["id"], "disclosure_owner")
    assert pkg["state"] == "REVIEWED"
    with pytest.raises(store.Refused, match="technical reviewer cannot"):
        await packages.sign(db, REVIEWER, pkg["id"], "issuer")
    pkg = await packages.sign(db, ISSUER, pkg["id"], "issuer")
    assert pkg["state"] == "APPROVED"
    check = await packages.release_check(db, PREPARER, pkg["id"])
    assert not check["statutory_release_allowed"]                          # unreviewed rule packs: never statutory
    media, body, _ = await packages.export(db, PREPARER, pkg["id"], "json")
    assert json.loads(body)["watermark"]
    # AT-18: a change after sign-off is a new version; the approved one is kept, superseded.
    new = await packages.submit_disclosure(db, PREPARER, pkg["id"], requirement_id="N12", decision="include",
                                           text="A new customer contract was signed after year end.", evidence_ref="ev-2")
    assert new["version"] == 2 and not new["signoffs"]
    old = await packages.get(db, PREPARER, pkg["id"])
    assert old["state"] == "SUPERSEDED" and old["signoffs"]["issuer"]["by"] == "iss"


async def test_a_package_goes_stale_when_its_snapshot_changes(db):
    tb, res = await _approved_tb(db), await _frozen_resolution(db)
    pkg = await packages.build(db, PREPARER, trial_balance_id=tb["id"], resolution_id=res["id"])
    again = await packages.build(db, PREPARER, trial_balance_id=tb["id"], resolution_id=res["id"])
    assert again["id"] == pkg["id"] and again["version"] == 1                  # same inputs, same package
    revenue = next(m for m in tb["mappings"] if m["account_name"] == "Revenue")
    await store.decide_mapping(db, REVIEWER, tb["id"], revenue["id"], action="reject", reason="check")
    stale = await packages.get(db, PREPARER, pkg["id"])
    assert stale["state"] == "INVALIDATED" and "snapshot" in stale["stale_reasons"][0]
    with pytest.raises(store.Refused, match="out of date"):
        await packages.sign(db, PREPARER, pkg["id"], "preparer")
    rebuilt = await packages.build(db, PREPARER, trial_balance_id=tb["id"], resolution_id=res["id"])
    assert rebuilt["result"]["halted"] == "SOURCE_UNAPPROVED"


async def test_at29_another_tenant_is_denied_and_the_attempt_logged(db):
    tb = await _approved_tb(db)
    pkg = await packages.build(db, PREPARER, trial_balance_id=tb["id"])
    with pytest.raises(store.NotFound):
        await packages.get(db, OUTSIDER, pkg["id"])
    events = (await db.execute(select(AuditEvent).where(
        AuditEvent.event_name == "financial_statements.package_access_denied"))).scalars().all()
    assert len(events) == 1 and events[0].tenant_id == "t2"
    assert await packages.list_for(db, OUTSIDER) == []


async def test_only_p2_items_can_be_disposed_and_not_by_the_preparer(db):
    tb = await _approved_tb(db)
    pkg = await packages.build(db, PREPARER, trial_balance_id=tb["id"])
    p0 = next(f for f in pkg["result"]["findings"] if f["severity"] == "P0")
    with pytest.raises(store.Refused, match="cannot be waived"):
        await packages.dispose(db, REVIEWER, pkg["id"], code=p0["code"], reason="accept")
    pkg = await packages.submit_disclosure(db, PREPARER, pkg["id"], requirement_id="N02", decision="include",
                                           text="Revenue on delivery.", evidence_ref="p")
    with pytest.raises(store.Refused, match="preparer cannot"):
        await packages.dispose(db, PREPARER, pkg["id"], code="NOTE_PENDING_N02", reason="ok")
