"""ZL-RPT-007 gates G1 + G2 — golden route 001 and the §15.2 mutation suite.

Expected amounts below were derived by hand from the fixture's journals, not
by running the compiler, so a compiler bug cannot also bless its own output:

  P&L   revenue 500,000 − opex 300,000 − depreciation 40,000 = 160,000
  Cash  150,000 + operating 140,000 − investing 50,000 − financing 40,000 = 200,000
        (operating = 470,000 collected − 330,000 paid; financing = 25,000 loan + 15,000 dividend)
  BS    cash 200,000 + receivables 110,000 + PPE 470,000 = 780,000
        = payables 30,000 + borrowings 175,000
        + share capital 250,000 + retained earnings 165,000 + result 160,000
  EQ    430,000 + 160,000 − 15,000 = 575,000
"""
import ast
import copy
import dataclasses
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.reporting.pipeline import build_draft
from app.domains.reporting.reconcile import reconcile
from app.domains.reporting.states import ReportState

REPORTING = Path(__file__).resolve().parents[1] / "app" / "domains" / "reporting"
FIXTURE = json.loads((REPORTING / "fixtures" / "golden_route_001.json").read_text())

EXPECTED = {
    "profit_or_loss": {
        "pl.revenue": "500000", "pl.operating_expenses": "300000", "pl.depreciation": "40000",
        "pl.net_result": "160000",
    },
    "balance_sheet": {
        "bs.cash": "200000", "bs.trade_receivables": "110000", "bs.ppe": "470000", "bs.total_assets": "780000",
        "bs.trade_payables": "30000", "bs.borrowings": "175000", "bs.total_liabilities": "205000",
        "bs.share_capital": "250000", "bs.retained_earnings": "165000", "bs.current_period_result": "160000",
        "bs.total_equity": "575000",
    },
    "cash_flow": {
        "cf.cash.opening": "150000", "cf.operating": "140000", "cf.investing": "-50000",
        "cf.financing": "-40000", "cf.fx_effect": "0", "cf.cash.closing": "200000",
    },
    "changes_in_equity": {
        "eq.opening": "430000", "eq.result": "160000", "eq.distributions": "-15000", "eq.closing": "575000",
    },
}


def _inputs():
    return copy.deepcopy(FIXTURE["ledger"]), copy.deepcopy(FIXTURE["account_map"])


def _journal(ledger, source_id):
    return next(j for j in ledger["journals"] if j["source_id"] == source_id)


def _outcome(draft, rule_id):
    return next(o for o in draft.outcomes if o.rule_id == rule_id)


def _tamper(draft, statement, concept, delta):
    """Change one presented amount after compilation, as a faulty renderer or edit would."""
    lines = draft.compiled.statements[statement]
    index = next(i for i, line in enumerate(lines) if line.concept == concept)
    lines[index] = dataclasses.replace(lines[index], value=lines[index].value + Decimal(delta))
    return {o.rule_id: o for o in reconcile(draft.compiled)}


# ── Golden route ────────────────────────────────────────────────────────────

def test_golden_route_reconciles_to_hand_derived_amounts():
    draft = build_draft(*_inputs())
    assert draft.state == ReportState.DRAFT_RECONCILED, (draft.error_code, draft.exceptions, draft.outcomes)
    assert draft.exceptions == []
    assert all(o.passed and o.delta == 0 for o in draft.outcomes), draft.outcomes
    for statement, expected in EXPECTED.items():
        for concept, value in expected.items():
            assert draft.compiled.line(statement, concept).value == Decimal(value), (statement, concept)


def test_after_cutoff_journal_is_excluded_and_counted():
    draft = build_draft(*_inputs())
    assert draft.receipt.after_cutoff == ("JNL-901",)
    assert draft.receipt.accepted == 9 and draft.receipt.received == 10


def test_every_presented_amount_is_a_traceable_fact():
    draft = build_draft(*_inputs())
    facts = draft.compiled.facts
    for statement, lines in draft.compiled.statements.items():
        for line in lines:
            fact = facts[line.fact_id]
            assert fact.value == line.value and isinstance(fact.value, Decimal)
            assert fact.snapshot_hash == draft.snapshot_hash
            assert fact.mapping_version == "golden-route-001/map-v1"
            assert fact.lineage
            if line.value != 0:
                assert fact.source_refs, (statement, line.concept)
    assert len(facts) == sum(len(lines) for lines in draft.compiled.statements.values())


# ── Determinism (§6.1 exit gate, §17 manifest_replay_match) ─────────────────

def test_reimport_yields_identical_snapshot_hash_and_fact_ids():
    first, second = build_draft(*_inputs()), build_draft(*_inputs())
    assert first.snapshot_hash == second.snapshot_hash
    assert set(first.compiled.facts) == set(second.compiled.facts)


def test_journal_order_and_decimal_spelling_do_not_change_the_hash():
    baseline = build_draft(*_inputs()).snapshot_hash
    ledger, account_map = _inputs()
    ledger["journals"].reverse()
    _journal(ledger, "JNL-001")["lines"][0]["debit"] = "500000"
    _journal(ledger, "JNL-001")["lines"][1]["credit"] = "5.0E+5"
    assert build_draft(ledger, account_map).snapshot_hash == baseline


# ── §15.2 mutation suite ────────────────────────────────────────────────────

def test_unmatched_debit_of_one_dollar_fails_tb001_with_exact_delta():
    ledger, account_map = _inputs()
    _journal(ledger, "JNL-001")["lines"].append({"account": "1100", "debit": "1.00"})
    draft = build_draft(ledger, account_map)
    assert draft.state == ReportState.DRAFT_INCOMPLETE and draft.error_code == "reconciliation_failed"
    tb = _outcome(draft, "TB-001")
    assert not tb.passed and tb.delta == Decimal("1") and "JNL-001" in tb.detail


def test_assets_780000_presented_as_779999_fails_bs001():
    draft = build_draft(*_inputs())
    outcomes = _tamper(draft, "balance_sheet", "bs.ppe", "-1")
    assert not outcomes["BS-001"].passed and outcomes["BS-001"].delta == Decimal("-1")


def test_duplicate_journal_on_retry_is_not_double_counted():
    baseline = build_draft(*_inputs())
    ledger, account_map = _inputs()
    ledger["journals"].append(copy.deepcopy(_journal(ledger, "JNL-002")))
    draft = build_draft(ledger, account_map)
    assert draft.state == ReportState.DRAFT_RECONCILED
    assert draft.receipt.duplicates_ignored == 1
    assert draft.snapshot_hash == baseline.snapshot_hash
    assert draft.compiled.line("cash_flow", "cf.operating").value == Decimal("140000")


def test_same_version_with_different_content_is_a_blocking_conflict():
    ledger, account_map = _inputs()
    retry = copy.deepcopy(_journal(ledger, "JNL-002"))
    retry["lines"][0]["debit"] = retry["lines"][1]["credit"] = "470001.00"
    ledger["journals"].append(retry)
    draft = build_draft(ledger, account_map)
    assert draft.state == ReportState.DRAFT_INCOMPLETE and draft.error_code == "duplicate_conflict"
    assert draft.compiled is None


def test_later_version_supersedes_and_is_recorded():
    ledger, account_map = _inputs()
    revised = copy.deepcopy(_journal(ledger, "JNL-001"))
    revised["version"] = 2
    revised["lines"][0]["debit"] = revised["lines"][1]["credit"] = "500001.00"
    ledger["journals"].append(revised)
    draft = build_draft(ledger, account_map)
    assert draft.state == ReportState.DRAFT_RECONCILED
    assert draft.receipt.superseded == ("JNL-001@1",)
    assert draft.compiled.line("profit_or_loss", "pl.net_result").value == Decimal("160001")


def test_unavailable_receivable_is_never_treated_as_zero():
    for missing in ("", None, 470000.0):
        ledger, account_map = _inputs()
        _journal(ledger, "JNL-002")["lines"][1]["credit"] = missing
        draft = build_draft(ledger, account_map)
        assert draft.state == ReportState.DRAFT_INCOMPLETE and draft.error_code == "amount_invalid", missing
        assert draft.compiled is None


def test_broken_fx_reconciling_line_blocks_the_cash_statement():
    draft = build_draft(*_inputs())
    outcomes = _tamper(draft, "cash_flow", "cf.fx_effect", "1")
    assert not outcomes["CF-001"].passed and outcomes["CF-001"].delta == Decimal("1")


def test_tampered_equity_movement_fails_eq001():
    draft = build_draft(*_inputs())
    outcomes = _tamper(draft, "changes_in_equity", "eq.distributions", "-1")
    assert not outcomes["EQ-001"].passed and outcomes["EQ-001"].delta == Decimal("-1")


def test_tampered_net_result_fails_pl001():
    draft = build_draft(*_inputs())
    outcomes = _tamper(draft, "profit_or_loss", "pl.net_result", "1")
    assert not outcomes["PL-001"].passed


# ── Fail-closed inputs (§1, §5, §6.2) ───────────────────────────────────────

def test_unmapped_account_is_an_exception_not_other():
    ledger, account_map = _inputs()
    del account_map["accounts"]["5100"]
    draft = build_draft(ledger, account_map)
    assert draft.state == ReportState.DRAFT_INCOMPLETE and draft.error_code == "snapshot_incomplete"
    assert any(e["code"] == "account_unmapped" and e["account"] == "5100" for e in draft.exceptions)
    assert not any("other" in line.concept for lines in draft.compiled.statements.values() for line in lines)


def test_cash_journal_with_mixed_counterpart_classes_is_not_guessed():
    ledger, account_map = _inputs()
    ledger["journals"].append({
        "source_id": "JNL-050", "version": 1, "posted_on": "2026-05-01", "description": "Mixed receipt",
        "lines": [{"account": "1000", "debit": "100.00"}, {"account": "4000", "credit": "50.00"},
                  {"account": "2500", "credit": "50.00"}],
    })
    draft = build_draft(ledger, account_map)
    assert draft.state == ReportState.DRAFT_INCOMPLETE
    assert any(e["code"] == "cash_classification_ambiguous" and e["journal"] == "JNL-050" for e in draft.exceptions)
    assert not _outcome(draft, "CF-001").passed


def test_unknown_account_and_orphan_reversal_stop_the_import():
    ledger, account_map = _inputs()
    _journal(ledger, "JNL-003")["lines"][0]["account"] = "9999"
    assert build_draft(ledger, account_map).error_code == "account_unknown"

    ledger, account_map = _inputs()
    _journal(ledger, "JNL-007")["reverses"] = "JNL-404"
    assert build_draft(ledger, account_map).error_code == "reversal_orphan"


def test_mixed_currency_ledger_is_unavailable_not_converted():
    ledger, account_map = _inputs()
    ledger["currencies"] = ["USD", "EUR"]
    draft = build_draft(ledger, account_map)
    assert draft.state == ReportState.UNAVAILABLE and draft.error_code == "fx_missing_or_inapplicable"


def test_pipeline_never_reaches_a_reviewed_or_issued_state():
    draft = build_draft(*_inputs())
    assert draft.state not in (ReportState.REVIEWED, ReportState.APPROVED_FOR_ISSUE, ReportState.ISSUED)


def test_reporting_code_never_uses_binary_floating_point():
    """No `float` name and no float literal anywhere in reporting code (docstrings may say the word)."""
    for path in REPORTING.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            assert not (isinstance(node, ast.Name) and node.id == "float"), f"{path.name}:{node.lineno} uses float"
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), \
                f"{path.name}:{node.lineno} has a float literal"
