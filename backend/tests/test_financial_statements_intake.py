"""Document 04 acceptance tests (ZL-FSR-ENG-004 §14) for the trial-balance
intake: app/domains/financial_statements."""
import hashlib
import io
import zipfile
from decimal import Decimal

import pytest

from app.domains.financial_statements import journals, mapping, workflow
from app.domains.financial_statements.normalize import parse_amount
from app.domains.financial_statements.service import run_intake

TB = ("account_code,account_name,debit,credit\n"
      "1000,Property plant and equipment,1265000.00,\n1300,Trade receivables,703000.00,\n"
      "1400,Cash at bank,512000.00,\n2000,Trade payables,,389000.00\n3000,Share capital,,100000.00\n"
      "4000,Revenue,,4182000.00\n5000,Cost of sales,2431000.00,\n6000,Utilities,18400.00,\n"
      "6100,Bank charges,2900.00,\n6200,Administrative expenses,880700.00,\n3100,Retained earnings,,1142000.00\n")


def _codes(result):
    return {f.code for f in result.findings}


def _csv(text):
    return run_intake("tb.csv", text.encode(), "preparer-1")


def _xlsx(build) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    build(wb)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_at01_the_original_bytes_are_fingerprinted_and_kept_with_the_uploader():
    result = _csv(TB)
    assert result.manifest.sha256 == hashlib.sha256(TB.encode()).hexdigest()
    assert result.manifest.uploaded_by == "preparer-1" and result.manifest.size_bytes == len(TB.encode())


def test_at02_a_workbook_with_macros_is_rejected_without_being_opened():
    plain = _xlsx(lambda wb: wb.active.append(["account_name", "debit", "credit"]))
    buffer = io.BytesIO(plain)
    with zipfile.ZipFile(buffer, "a") as archive:
        archive.writestr("xl/vbaProject.bin", b"macro")
    result = run_intake("tb.xlsx", buffer.getvalue(), "u")
    assert result.state == workflow.REJECTED_SOURCE and "ACTIVE_CONTENT" in _codes(result)
    assert run_intake("tb.xlsm", plain, "u").state == workflow.REJECTED_SOURCE


def test_at03_a_hidden_sheet_holding_balances_is_reported_and_included():
    def build(wb):
        ws = wb.active
        ws.append(["account_name", "debit", "credit"])
        ws.append(["Revenue", None, 100])
        ws.append(["Cash at bank", 100, None])
        hidden = wb.create_sheet("Old")
        hidden.append(["note", "x"])
        hidden.sheet_state = "hidden"
    result = run_intake("tb.xlsx", _xlsx(build), "u")
    assert "HIDDEN_CONTENT" in _codes(result) and result.manifest.hidden_sheets == ("Old",)


def test_at04_a_signed_balance_column_without_a_convention_blocks():
    result = _csv("account_name,balance\nRevenue,-100\nCash at bank,100\n")
    assert "SIGN_UNRESOLVED" in _codes(result) and result.state == workflow.RECONCILIATION_FAILED


def test_at05_a_comma_decimal_number_is_not_converted():
    assert parse_amount("1.234,56").status == "LOCALE_AMBIGUOUS"
    result = _csv('account_name,debit,credit\nRevenue,,"1.234,56"\nCash at bank,"1.234,56",\n')
    assert "LOCALE_AMBIGUOUS" in _codes(result) and result.state == workflow.RECONCILIATION_FAILED


def test_at06_mixed_currencies_are_not_summed():
    result = _csv("account_name,currency,debit,credit\nRevenue,GBP,,100\nCash at bank,USD,100,\n")
    assert "MIXED_CURRENCY" in _codes(result)


def test_at07_a_duplicated_account_is_flagged_not_merged():
    result = _csv("account_code,account_name,debit,credit\n4000,Revenue,,100\n4000,Revenue,,50\n1400,Cash at bank,150,\n")
    assert "DUPLICATE_ACCOUNT" in _codes(result) and len(result.tb.lines) == 3


def test_at08_a_missing_account_code_is_kept_and_flagged():
    result = _csv("account_code,account_name,debit,credit\n4000,Revenue,,100\n,Cash at bank,100,\n")
    assert "MISSING_ACCOUNT_CODE" in _codes(result) and len(result.tb.lines) == 2


def test_at09_debits_not_equal_to_credits_block_at_full_precision():
    result = _csv("account_name,debit,credit\nRevenue,,100.00\nCash at bank,99.99,\n")
    assert "UNBALANCED" in _codes(result) and result.report.difference == Decimal("-0.01")
    assert result.state == workflow.RECONCILIATION_FAILED


def test_at10_a_balanced_trial_balance_proves_arithmetic_only():
    result = _csv(TB)
    assert result.report.balanced and result.state == workflow.MAPPING_REVIEW   # not approved by balancing
    assert "arithmetic only" in result.report.to_dict()["note"]


def test_at11_no_prior_year_is_flagged_never_invented():
    assert "COMPARATIVE_MISSING" in _codes(_csv(TB))
    assert "COMPARATIVE_MISSING" not in _codes(_csv("account_name,debit 2026,credit 2026,debit 2025\nRevenue,,1,\n"))


def test_at12_utilities_needs_evidence_and_gets_no_line():
    utilities = next(m for m in _csv(TB).mappings if m.account_name == "Utilities")
    assert utilities.status == mapping.NEEDS_EVIDENCE and utilities.line_id is None
    assert "cost centres" in utilities.evidence_required and len(utilities.candidates) == 3
    with pytest.raises(mapping.MappingError):
        mapping.approve(utilities, reviewer="r", line_id="pl.administrative_expenses")   # no evidence given


def test_at13_at14_utilities_approved_with_evidence_or_split_exactly():
    utilities = next(m for m in _csv(TB).mappings if m.account_name == "Utilities")
    single = mapping.approve(utilities, reviewer="r", line_id="pl.administrative_expenses", evidence_ref="INV-77")
    assert single.status == mapping.APPROVED and "INV-77" in single.basis
    split = mapping.approve(utilities, reviewer="r", evidence_ref="meters",
                            allocations=[("pl.cost_of_sales", Decimal("8000")), ("pl.administrative_expenses", Decimal("10400"))])
    assert sum(a.amount for a in split.allocations) == Decimal("18400")
    with pytest.raises(mapping.MappingError):
        mapping.approve(utilities, reviewer="r", evidence_ref="m",
                        allocations=[("pl.cost_of_sales", Decimal("8000")), ("pl.administrative_expenses", Decimal("10000"))])


def test_at15_bank_charges_are_not_defaulted():
    bank = next(m for m in _csv(TB).mappings if m.account_name == "Bank charges")
    assert bank.status == mapping.NEEDS_EVIDENCE and "pl.finance_costs" in bank.candidates


def _approved(result, reviewer="reviewer-1"):
    out = []
    for m in result.mappings:
        if m.status == mapping.SUGGESTED:
            out.append(mapping.approve(m, reviewer=reviewer))
        elif m.status == mapping.NEEDS_EVIDENCE:
            out.append(mapping.approve(m, reviewer=reviewer, line_id=m.candidates[-1], evidence_ref="EV-1"))
    return out


def test_at17_a_reclassification_changes_gross_profit_not_profit_before_tax():
    approved = _approved(_csv(TB))
    journal = journals.propose_journal(kind=journals.RECLASSIFICATION, reason="Factory share of utilities",
                                       lines=[("pl.cost_of_sales", Decimal("8000"), 0),
                                              ("pl.administrative_expenses", 0, Decimal("8000"))],
                                       created_by="preparer-1", evidence_refs=["meters"])
    effect = journals.simulate(approved, journal)
    assert effect["profit_before_tax_before"] == effect["profit_before_tax_after"]
    assert effect["posting_status"] == "NOT_POSTED"
    assert {l["line_id"] for l in effect["lines"]} == {"pl.cost_of_sales", "pl.administrative_expenses"}


def test_at18_an_unbalanced_journal_is_rejected():
    with pytest.raises(journals.JournalError):
        journals.propose_journal(kind=journals.ADJUSTMENT, reason="x", created_by="p",
                                 lines=[("pl.cost_of_sales", Decimal("100"), 0), ("bs.trade_payables", 0, Decimal("90"))])


def test_at19_the_preparer_cannot_approve_their_own_work():
    result = _csv(TB)
    approved = _approved(result)
    with pytest.raises(workflow.ApprovalError):
        workflow.approve_snapshot(source_sha256=result.manifest.sha256, tb=result.tb, findings=result.findings,
                                  mappings=approved, journals=[], preparer="preparer-1", approver="preparer-1")
    journal = journals.propose_journal(kind=journals.ADJUSTMENT, reason="Accrual", created_by="p",
                                       lines=[("pl.administrative_expenses", Decimal("5"), 0), ("bs.trade_payables", 0, Decimal("5"))])
    with pytest.raises(journals.JournalError):
        journals.review_journal(journal, reviewer="p", approve=True)


def test_at20_a_changed_source_invalidates_the_approved_snapshot():
    result = _csv(TB)
    approved = _approved(result)
    snapshot = workflow.approve_snapshot(source_sha256=result.manifest.sha256, tb=result.tb, findings=result.findings,
                                         mappings=approved, journals=[], preparer="preparer-1", approver="reviewer-1")
    assert snapshot.content_hash.startswith("sha256:")
    assert workflow.still_valid(snapshot, source_sha256=result.manifest.sha256, tb=result.tb, mappings=approved, journals=[])
    changed = _csv(TB.replace("18400.00", "18500.00").replace("880700.00", "880600.00"))
    assert not workflow.still_valid(snapshot, source_sha256=changed.manifest.sha256, tb=changed.tb,
                                    mappings=_approved(changed), journals=[])


def test_approval_is_refused_while_hard_stops_or_unapproved_mappings_remain():
    result = _csv(TB)
    with pytest.raises(workflow.ApprovalError, match="not mapped and approved"):
        workflow.approve_snapshot(source_sha256=result.manifest.sha256, tb=result.tb, findings=result.findings,
                                  mappings=result.mappings, journals=[], preparer="p", approver="r")
    broken = _csv("account_name,debit,credit\nRevenue,,100\nCash at bank,90,\n")
    with pytest.raises(workflow.ApprovalError, match="UNBALANCED"):
        workflow.approve_snapshot(source_sha256=broken.manifest.sha256, tb=broken.tb, findings=broken.findings,
                                  mappings=_approved(broken), journals=[], preparer="p", approver="r")


def test_at27_suggestions_stay_suggestions_until_approved():
    result = _csv(TB)
    assert all(m.status != mapping.APPROVED for m in result.mappings)
    assert "Proposals only" in result.to_dict()["status_note"]


def test_at31_every_line_traces_to_its_source_row():
    revenue = next(l for l in _csv(TB).tb.lines if l.account_name == "Revenue")
    assert revenue.ref == "CSV!R7" and revenue.to_dict()["source"] == "CSV!R7"


def test_suspense_sign_anomaly_and_control_total_checks():
    text = ("account_name,debit,credit\nTrade receivables,,50\nRevenue,,100\nCash at bank,120,\nSuspense,30,\n"
            "Total,150,140\n")
    codes = _codes(_csv(text))
    assert {"SUSPENSE_BALANCE", "SIGN_ANOMALY", "CONTROL_TOTAL_MISMATCH"} <= codes


def test_the_intake_route_is_registered():
    from fastapi.routing import APIRoute
    from app.main import app

    def walk(routes, prefix=""):   # included routers are nested (as in test_manual_test_server)
        for route in routes:
            if isinstance(route, APIRoute):
                yield prefix + route.path
            elif type(route).__name__ == "_IncludedRouter":
                yield from walk(route.original_router.routes, prefix + (getattr(route.include_context, "prefix", "") or ""))
    assert "/api/v1/financial-statements/intake" in set(walk(app.routes))
