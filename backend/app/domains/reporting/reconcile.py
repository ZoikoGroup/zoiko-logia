"""Accounting invariants (ZL-RPT-007 §7 table, §15.2 mutation suite).

Each reconciler recomputes what it needs from the sealed snapshot or from the
presented statement lines — it never trusts a total the compiler stored. A
failure records the exact delta; nothing posts a balancing plug or rounds a
residual away.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .compiler import ZERO, CompiledReport

RULES = ("TB-001", "BS-001", "PL-001", "CF-001", "EQ-001")


@dataclass(frozen=True)
class ReconcilerOutcome:
    rule_id: str
    passed: bool
    delta: Decimal
    detail: str


def _ledger_journals(report: CompiledReport):
    end = report.snapshot.period_end
    return [j for j in report.snapshot.journals if j.posted_on <= end]


def _lines(report: CompiledReport, statement: str, section: str) -> list:
    return [l for l in report.statements.get(statement, []) if l.section == section and not l.is_total]


def _sum(lines) -> Decimal:
    return sum((l.value for l in lines), ZERO)


def check_trial_balance(report: CompiledReport) -> ReconcilerOutcome:
    unbalanced, debits, credits = [], ZERO, ZERO
    for journal in _ledger_journals(report):
        d = sum((l.debit for l in journal.lines), ZERO)
        c = sum((l.credit for l in journal.lines), ZERO)
        debits, credits = debits + d, credits + c
        if d != c:
            unbalanced.append(f"{journal.source_id} ({d - c:+})")
    delta = debits - credits
    if delta == ZERO and not unbalanced:
        return ReconcilerOutcome("TB-001", True, ZERO, f"debits = credits = {debits} {report.snapshot.currency}")
    return ReconcilerOutcome("TB-001", False, delta,
                             f"debits {debits} vs credits {credits}; unbalanced journals: {', '.join(unbalanced) or 'none'}")


def check_balance_sheet(report: CompiledReport) -> ReconcilerOutcome:
    assets = _sum(_lines(report, "balance_sheet", "assets"))
    liabilities = _sum(_lines(report, "balance_sheet", "liabilities"))
    equity = _sum(_lines(report, "balance_sheet", "equity"))
    delta = assets - liabilities - equity
    stale = [section for section, value in (("assets", assets), ("liabilities", liabilities), ("equity", equity))
             if report.line("balance_sheet", f"bs.total_{section}").value != value]
    if delta == ZERO and not stale:
        return ReconcilerOutcome("BS-001", True, ZERO, f"assets {assets} = liabilities {liabilities} + equity {equity}")
    detail = f"assets {assets} - liabilities {liabilities} - equity {equity} = {delta}"
    if stale:
        detail += f"; presented totals disagree with their lines: {', '.join(stale)}"
    return ReconcilerOutcome("BS-001", False, delta, detail)


def check_profit_or_loss(report: CompiledReport) -> ReconcilerOutcome:
    from_lines = _sum(_lines(report, "profit_or_loss", "revenue")) - _sum(_lines(report, "profit_or_loss", "expenses"))
    presented = report.line("profit_or_loss", "pl.net_result").value
    snap = report.snapshot
    types = {code: a.type for code, a in snap.accounts.items()}
    from_ledger = -sum((l.net_debit for j in _ledger_journals(report) if j.posted_on >= snap.period_start
                        for l in j.lines if types[l.account] in ("revenue", "expense")), ZERO)
    delta = presented - from_ledger
    if from_lines == presented == from_ledger:
        return ReconcilerOutcome("PL-001", True, ZERO, f"net result {presented} agrees with lines and ledger")
    return ReconcilerOutcome("PL-001", False, delta,
                             f"presented {presented}, sum of lines {from_lines}, ledger {from_ledger}")


def check_cash_flow(report: CompiledReport) -> ReconcilerOutcome:
    get = lambda concept: report.line("cash_flow", concept).value  # noqa: E731
    rolled = get("cf.cash.opening") + get("cf.operating") + get("cf.investing") + get("cf.financing") + get("cf.fx_effect")
    closing = get("cf.cash.closing")
    snap = report.snapshot
    cash_codes = {code for code, a in snap.accounts.items() if a.is_cash}
    ledger_closing = sum((l.net_debit for j in _ledger_journals(report) for l in j.lines if l.account in cash_codes), ZERO)
    cash_lines = {report.account_map.lines[c].line for c in cash_codes if c in report.account_map.lines}
    balance_sheet_cash = _sum(l for l in _lines(report, "balance_sheet", "assets") if l.concept in cash_lines)
    delta = rolled - closing
    if delta == ZERO and closing == ledger_closing == balance_sheet_cash:
        return ReconcilerOutcome("CF-001", True, ZERO, f"opening + flows = closing cash {closing}")
    return ReconcilerOutcome("CF-001", False, delta if delta != ZERO else closing - balance_sheet_cash,
                             f"rollforward {rolled} vs closing {closing}; ledger cash {ledger_closing}; "
                             f"balance-sheet cash {balance_sheet_cash}")


def check_equity(report: CompiledReport) -> ReconcilerOutcome:
    rolled = report.line("changes_in_equity", "eq.opening").value + _sum(_lines(report, "changes_in_equity", "movements"))
    closing = report.line("changes_in_equity", "eq.closing").value
    balance_sheet_equity = _sum(_lines(report, "balance_sheet", "equity"))
    delta = rolled - closing
    if delta == ZERO and closing == balance_sheet_equity:
        return ReconcilerOutcome("EQ-001", True, ZERO, f"equity rollforward = balance-sheet equity {closing}")
    return ReconcilerOutcome("EQ-001", False, delta if delta != ZERO else closing - balance_sheet_equity,
                             f"rollforward {rolled} vs closing {closing}; balance-sheet equity {balance_sheet_equity}")


def reconcile(report: CompiledReport) -> list[ReconcilerOutcome]:
    return [check(report) for check in (check_trial_balance, check_balance_sheet, check_profit_or_loss,
                                        check_cash_flow, check_equity)]
