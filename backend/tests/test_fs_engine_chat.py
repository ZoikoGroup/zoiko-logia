"""Kriton chat on the Financial Statements engine (fs_engine_chat.py).

Cases from review ZL-FSR-COR-20261103 (NB26-xx) and Supplement A (SA-Txx),
run against the engine's own Northbridge seed and the suspense trial balance.
"""
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestration import fs_engine_chat
from app.orchestration.fs_engine_chat import build, facts_block, statement_notes

GOLDEN = json.loads((Path(__file__).resolve().parents[1] / "app" / "domains" / "financial_statements" / "golden"
                     / "nb_synthetic_2026.json").read_text(encoding="utf-8"))
NORTHBRIDGE = GOLDEN["tb_csv"].encode()
SUSPENSE = (
    "account_code,account_name,debit,credit\n1000,\"Property, plant and equipment\",1265000.00,\n"
    "1100,Intangible assets,340000.00,\n1200,Inventory,418000.00,\n1300,Trade receivables,703000.00,\n"
    "1400,Cash at bank,512000.00,\n2000,Trade payables,,389000.00\n2100,Accruals,,146000.00\n"
    "2200,Deferred tax liability,,87000.00\n2300,Corporation tax payable,,196750.00\n3000,Share capital,,100000.00\n"
    "3100,Retained earnings,,1925750.00\n4000,Revenue,,4182000.00\n5000,Cost of sales,2431000.00,\n"
    "6000,Administrative expenses,902000.00,\n6100,Interest payable,62000.00,\n7000,Corporation tax charge,196750.00,\n"
    "8000,Suspense,196750.00,\n").encode()


def test_nb26_01_the_reference_route_gives_operating_profit_218600():
    s = build("northbridge.csv", NORTHBRIDGE)
    f = s.figures
    assert (f["revenue"], f["gross_profit"], f["operating_expenses"]) == (Decimal("1850000"), Decimal("795500"), Decimal("576900"))
    assert f["operating_profit"] == Decimal("218600") and f["net_finance"] == Decimal("-2200")
    assert (f["profit_before_tax"], f["profit_for_the_year"]) == (Decimal("216400"), Decimal("154400"))
    assert s.residual == 0 and not s.unmapped


def test_nb26_02_03_the_open_classification_shows_both_operating_profits():
    s = build("northbridge.csv", NORTHBRIDGE)
    assert {c.account for c in s.choices} == {"Bank charges", "Interest received"}
    block, notes = facts_block(s), statement_notes(s)
    assert "operating profit is 233,500 (a difference of 14,900); profit before tax is unchanged" in block
    assert any("Operating profit is 218,600 as shown, 233,500 under the alternative (difference 14,900)" in n
               for n in notes)


def test_nb26_04_an_unbalanced_trial_balance_is_reported_with_its_difference():
    s = build("northbridge.csv", NORTHBRIDGE.replace(b"4000,Revenue,,1850000.00", b"4000,Revenue,,1850001.00"))
    assert s.total_credits - s.total_debits == Decimal("1")
    assert any("ARITHMETIC_FAIL" in n and "difference -1" in n for n in statement_notes(s))


def test_nb26_06_dividends_stay_outside_profit():
    s = build("northbridge.csv", NORTHBRIDGE)
    assert s.figures["profit_for_the_year"] == Decimal("154400") and s.dividends == [("Dividends paid", Decimal("40000"))]
    assert "whether declared, paid or proposed is not established" in facts_block(s)


def test_nb26_07_tax_equal_to_payable_is_an_incomplete_reconciliation():
    block = facts_block(build("northbridge.csv", NORTHBRIDGE))
    assert "the tax reconciliation is incomplete; never conclude from equal amounts that no tax was paid" in block
    assert "effective tax rate 28.65% (does not validate the tax charge)" in block


def test_sa_t01_t02_the_suspense_residual_stays_beside_a_balanced_trial_balance():
    s = build("kriton-test-trial-balance.csv", SUSPENSE)
    assert s.balanced and s.total_debits == Decimal("7026500.00")
    assert s.residual == Decimal("-196750.00") and s.unmapped == [("Suspense", Decimal("196750.00"))]
    assert s.figures["profit_for_the_year"] == Decimal("590250.00")
    notes = statement_notes(s)
    assert any("residual of -196,750" in n and "Suspense 196,750" in n and "RECONCILIATION_UNRESOLVED" in n for n in notes)
    assert "an investigation lead, not an explanation; do not propose a correcting entry" in facts_block(s)


def test_sa_t07_interest_payable_is_flagged_by_its_caption():
    assert any(flag.startswith("Interest payable (62,000)") for flag in build("tb.csv", SUSPENSE).caption_flags)


def test_nb26_11_sa_t10_a_file_without_a_period_says_so():
    assert "Period end: not stated in the file (head the statement: reporting period not confirmed)" in \
        facts_block(build("tb.csv", SUSPENSE))
    assert "Period end: 2026-03-31." not in facts_block(build("tb.csv", SUSPENSE))


def test_accumulated_depreciation_reduces_ppe_not_profit():
    # Engine gap: the name matches the needs-evidence "depreciation" rule.
    csv = NORTHBRIDGE.replace(b"1000,Property plant and equipment,640000.00,",
                              b"1000,Property plant and equipment,700000.00,\n1090,Accumulated depreciation,,60000.00")
    s = build("northbridge.csv", csv)
    assert s.figures["profit_for_the_year"] == Decimal("154400") and s.residual == 0
    assert "Accumulated depreciation" not in [n for n, _ in s.cost_of_sales_candidates]


def test_a_file_that_is_not_a_trial_balance_is_left_to_the_previous_path():
    assert build("notes.csv", b"Quarter,Revenue\nQ1,2100\nQ2,2300\n") is None


def test_the_engine_path_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("KRITON_FS_ENGINE_CHAT", "0")
    assert not fs_engine_chat.enabled()
    monkeypatch.setenv("KRITON_FS_ENGINE_CHAT", "1")
    assert fs_engine_chat.enabled()


async def test_a_statement_request_uses_the_engine_figures_not_the_chat_calculation(monkeypatch):
    from app.domains.kriton_workspace import documents
    from app.orchestration import service
    from app.orchestration.websearch import WebSource

    monkeypatch.setattr(documents, "stored_spreadsheets", AsyncMock(return_value=[("kriton-test-trial-balance.csv", SUSPENSE)]))
    db = MagicMock()
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    chunk = WebSource(title="kriton-test-trial-balance.csv — 'kriton-test-trial-balance'!1:18", url="",
                      snippet=SUSPENSE.decode().replace(",", "\t"), provider="uploaded_document")
    block = await service._verified_document_figures_context(
        db, "Generate the income statement from this trial balance", ["d1"], [chunk],
        SimpleNamespace(retrieval_mode="full_document"), "t", "u")
    assert "Statement figures from the Financial Statements engine" in block
    assert "Trial balance 'kriton-test-trial-balance.csv" not in block      # no second set of numbers
    assert fs_engine_chat.current_statement.get().residual == Decimal("-196750.00")
    # Not a statement request: the previous calculation, no engine block.
    plain = await service._verified_document_figures_context(
        db, "What is the total revenue?", ["d1"], [chunk], SimpleNamespace(retrieval_mode="full_document"), "t", "u")
    assert "Financial Statements engine" not in plain and fs_engine_chat.current_statement.get() is None


def test_dc_01_02_each_choice_on_its_own_gives_the_intermediate_operating_profits():
    # Decision ZL-FSR-DEC-20261104 D-01: scenarios B and C between A and D.
    s = build("northbridge.csv", NORTHBRIDGE)
    alone = {c.account: x for c, x in s.sensitivities}
    assert (alone["Interest received"]["operating_profit"], alone["Interest received"]["net_finance"]) == \
        (Decimal("230600"), Decimal("-14200"))                                   # B
    assert (alone["Bank charges"]["operating_profit"], alone["Bank charges"]["net_finance"]) == \
        (Decimal("221500"), Decimal("-5100"))                                    # C
    assert all(x["profit_before_tax"] == Decimal("216400") for x in alone.values())
    block = facts_block(s)
    assert "moving only Bank charges to interest payable and similar expenses: operating profit 221,500, net finance -5,100" in block
    assert "operating profit 230,600, net finance -14,200" in block and "Show all 4 operating profits" in block
    note = next(n for n in statement_notes(s) if "CLASSIFICATION_REVIEW" in n)
    assert "221,500 with only Bank charges moved" in note and "230,600 with only Interest received moved" in note


async def test_dc_11_an_engine_failure_is_said_not_hidden(monkeypatch):
    from app.domains.kriton_workspace import documents
    from app.orchestration import service
    from app.orchestration.websearch import WebSource

    monkeypatch.setattr(documents, "stored_spreadsheets", AsyncMock(return_value=[("tb.csv", SUSPENSE)]))
    monkeypatch.setattr(fs_engine_chat, "build", MagicMock(side_effect=RuntimeError("engine down")))
    db = MagicMock()
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    chunk = WebSource(title="tb.csv — 'tb'!1:18", url="", snippet=SUSPENSE.decode().replace(",", "\t"),
                      provider="uploaded_document")
    block = await service._verified_document_figures_context(
        db, "Generate the income statement from this trial balance", ["d1"], [chunk],
        SimpleNamespace(retrieval_mode="full_document"), "t", "u")
    assert "The Financial Statements engine did not run for tb.csv" in block
    assert fs_engine_chat.current_statement.get() is None and fs_engine_chat.engine_failure.get() == "tb.csv"
    assert "ENGINE_FAILED" in fs_engine_chat.failure_note("tb.csv")


def test_dc_12_the_statement_checks_are_kept_apart_from_the_sources():
    from app.orchestration.verification_service import verification_breakdown

    northbridge = verification_breakdown(completeness="complete", citations=2,
                                         limitations=statement_notes(build("northbridge.csv", NORTHBRIDGE)))
    assert (northbridge.classification, northbridge.reconciliation) == ("needs_evidence", "not_applicable")
    assert northbridge.overall != "fully_verified"
    suspense = verification_breakdown(completeness="complete", citations=2,
                                      limitations=statement_notes(build("tb.csv", SUSPENSE)))
    assert suspense.reconciliation == "unresolved"
    failed = verification_breakdown(completeness="complete", citations=0, limitations=[fs_engine_chat.failure_note("tb.csv")])
    assert failed.reconciliation == "not_run" and failed.overall == "not_verified"
    plain = verification_breakdown(completeness="complete", citations=1, limitations=[])
    assert (plain.classification, plain.reconciliation) == ("not_applicable", "not_applicable")


def test_dc_12_an_open_statement_is_not_called_verified_or_reconciled():
    from app.orchestration.statement_rules import remove_verification_claims

    text = ("Operating profit is 218,600.\nThe statements are fully verified and reconcile to the trial balance. "
            "Profit before tax is 216,400.\nThe statements do not reconcile until the suspense balance is cleared.\n"
            "| Line | Amount |\n|---|---|\n| Verified total | 1 |")
    kept, removed = remove_verification_claims(text)
    assert removed == ["The statements are fully verified and reconcile to the trial balance."]
    assert "Profit before tax is 216,400." in kept and "do not reconcile until" in kept and "| Verified total | 1 |" in kept


def test_the_alternative_statement_is_computed_line_by_line():
    # Retest of 4 Nov: the model's own alternative table said operating expenses 573,000.
    s = build("northbridge.csv", NORTHBRIDGE)
    a = s.alternative
    assert a["operating_expenses"] == Decimal("574000") and a["other_operating_income"] == Decimal("12000")
    assert a["operating_profit"] == Decimal("233500") and a["finance_income"] == 0
    assert a["finance_costs"] == Decimal("17100") and a["net_finance"] == Decimal("-17100")
    assert (a["profit_before_tax"], a["profit_for_the_year"]) == (Decimal("216400"), Decimal("154400"))
    block = facts_block(s)
    assert ("other operating income 12,000; operating expenses 574,000; operating profit 233,500; finance income 0; "
            "finance costs 17,100; net finance -17,100") in block
    assert "copy these; do not recompute" in block
    # A second table listed Bank charges under operating expenses beside a 574,000 total.
    assert "Bank charges 2,900 from administrative expenses to interest payable and similar expenses" in block
    assert "Interest received 12,000 from interest receivable and similar income to other operating income" in block
    assert "The rows under each heading must add up to its subtotal" in block
