"""Trial-balance and ledger integrity (Document 04 stage P3, rules SD-013
to SD-020, SD-024).

A balanced trial balance is necessary, never sufficient: passing these checks
proves only the arithmetic, not recognition, completeness or classification.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from .findings import HARD_STOP, INFO, REVIEW, Finding
from .normalize import LEDGER, ZERO, NormalizedTB

_SUSPENSE = re.compile(r"suspense|clearing|unallocated|unknown", re.I)
# Accounts whose normal balance is a debit / a credit, by name. A balance on
# the other side is not wrong by itself (an overdrawn bank, a debtor in
# credit) but needs a look: it is also how a reversed sign shows (SRC-04).
_NORMALLY_DEBIT = re.compile(r"\b(?:cash|bank|receivables?|debtors|inventor|stock|prepayments?|"
                             r"property|plant|equipment|vehicles?|cost\s+of\s+sales|expenses?|wages|salar|rent|"
                             # UK P&L names: "Interest payable" is an expense, "Tax charge" a debit.
                             r"interest\s+payable|charges?)\b", re.I)
_NORMALLY_CREDIT = re.compile(r"\b(?:payables?|creditors|accruals?|revenue|sales|turnover|share\s+capital|"
                              r"retained\s+earnings|loans?)\b", re.I)
_CONTRA = re.compile(r"accumulated|allowance|provision\s+for|overdraft|drawings|dividends?|returns|discounts?", re.I)
_MANUAL = re.compile(r"^(?:MJ|MAN|ADJ)\b|manual|adjust|correction|reversal|write[- ]?off", re.I)
ROUND_SUM_FLOOR = Decimal("10000")


@dataclass
class IntegrityReport:
    total_debits: Decimal = ZERO
    total_credits: Decimal = ZERO
    basis: str = "debit and credit columns"
    findings: list[Finding] = field(default_factory=list)

    @property
    def difference(self) -> Decimal:
        return self.total_debits - self.total_credits

    @property
    def balanced(self) -> bool:
        return self.difference == 0

    def to_dict(self) -> dict:
        return {"total_debits": str(self.total_debits), "total_credits": str(self.total_credits),
                "difference": str(self.difference), "balanced": self.balanced, "basis": self.basis,
                "note": "Debits equal credits proves the arithmetic only, not that the accounting is correct."}


def _amount_findings(tb: NormalizedTB, findings: list[Finding]) -> None:
    for line in tb.lines:
        for side, amount in (("debit", line.debit), ("credit", line.credit), ("opening", line.opening),
                             ("closing", line.closing)):
            if amount.status in ("INVALID", "LOCALE_AMBIGUOUS"):
                findings.append(Finding(
                    "INVALID_AMOUNT" if amount.status == "INVALID" else "LOCALE_AMBIGUOUS", HARD_STOP,
                    f"{line.account_name}: the {side} '{amount.raw}' is not a readable amount"
                    + (" (it looks like a comma-decimal number; confirm the number format)"
                       if amount.status == "LOCALE_AMBIGUOUS" else "") + ". It was not converted.",
                    "SD-008", (line.ref,)))


def _rollforward(tb: NormalizedTB, report: IntegrityReport) -> None:
    """SD-014: opening + period movements = closing, for every account."""
    report.basis = "closing balances"
    for line in tb.lines:
        if line.opening.value is None or line.closing.value is None:
            continue
        expected = line.opening.value + line.movement
        if expected != line.closing.value:
            report.findings.append(Finding(
                "ROLLFORWARD_MISMATCH", HARD_STOP,
                f"{line.account_name}: opening {line.opening.value} + movements {line.movement} = {expected}, but the "
                f"closing balance is {line.closing.value} (difference {line.closing.value - expected}).",
                "SD-014", (line.ref,)))
    report.total_debits = sum((l.net_debit for l in tb.lines if l.net_debit > 0), ZERO)
    report.total_credits = sum((-l.net_debit for l in tb.lines if l.net_debit < 0), ZERO)


def _ledger_checks(tb: NormalizedTB, findings: list[Finding]) -> None:
    """SD-018: vouchers balance; entries after the period end; round sums and
    manual journals named for review."""
    by_voucher: dict[str, list] = defaultdict(list)
    for line in tb.lines:
        if line.reference:
            by_voucher[line.reference].append(line)
    for reference, lines in by_voucher.items():
        net = sum((l.movement for l in lines), ZERO)
        if net != 0:
            findings.append(Finding("VOUCHER_UNBALANCED", HARD_STOP,
                                    f"Voucher {reference} does not balance (net {net}).", "SD-018",
                                    tuple(l.ref for l in lines)))
    if tb.period_end:
        late = [l for l in tb.lines if l.posted_on and l.posted_on > tb.period_end]
        if late:
            findings.append(Finding("CUTOFF_AFTER_PERIOD_END", REVIEW,
                                    f"{len(late)} entr{'y is' if len(late) == 1 else 'ies are'} dated after the period "
                                    f"end {tb.period_end.isoformat()}; check cut-off.", "SD-018",
                                    tuple(l.ref for l in late[:20])))
    round_sums = [l for l in tb.lines if abs(l.movement) >= ROUND_SUM_FLOOR and abs(l.movement) % 1000 == 0]
    if round_sums:
        findings.append(Finding("ROUND_SUM_ENTRIES", INFO,
                                f"{len(round_sums)} entr{'y is' if len(round_sums) == 1 else 'ies are'} round sums of "
                                f"{ROUND_SUM_FLOOR} or more; they are worth a look.", "SD-018",
                                tuple(l.ref for l in round_sums[:20])))
    manual = [l for l in tb.lines if _MANUAL.search(l.reference) or _MANUAL.search(l.narrative)]
    if manual:
        findings.append(Finding("MANUAL_JOURNALS", INFO,
                                f"{len(manual)} entr{'y looks' if len(manual) == 1 else 'ies look'} like manual "
                                f"journals or adjustments; check their support.", "SD-018",
                                tuple(l.ref for l in manual[:20])))


def check(tb: NormalizedTB) -> IntegrityReport:
    report = IntegrityReport()
    findings = report.findings
    _amount_findings(tb, findings)
    if not tb.lines:
        findings.append(Finding("NO_LINES", HARD_STOP, "No account lines were found.", "SD-020"))
        return report
    if tb.has_rollforward:
        _rollforward(tb, report)
    else:
        report.total_debits = sum((l.debit.value or ZERO for l in tb.lines), ZERO)
        report.total_credits = sum((l.credit.value or ZERO for l in tb.lines), ZERO)
    if not report.balanced:
        findings.append(Finding("UNBALANCED", HARD_STOP,
                                f"Debits ({report.total_debits}) and credits ({report.total_credits}) differ by "
                                f"{abs(report.difference)} ({report.basis}).", "SD-013"))
    for ref, debit, credit in tb.control_totals:
        if not tb.has_rollforward and (
                debit.value is not None and debit.value != report.total_debits
                or credit.value is not None and credit.value != report.total_credits):
            findings.append(Finding("CONTROL_TOTAL_MISMATCH", HARD_STOP,
                                    f"The sheet's own total row ({debit.raw or '-'} / {credit.raw or '-'}) does not "
                                    f"match the lines ({report.total_debits} / {report.total_credits}).", "SD-020", (ref,)))

    if tb.kind == LEDGER:
        _ledger_checks(tb, findings)
    else:
        by_key: dict[str, list] = defaultdict(list)
        for line in tb.lines:
            by_key[line.key.lower()].append(line)
        for lines in by_key.values():
            if len(lines) > 1:
                findings.append(Finding("DUPLICATE_ACCOUNT", HARD_STOP,
                                        f"Account '{lines[0].key}' appears {len(lines)} times; duplicates are never "
                                        f"merged silently.", "SD-015", tuple(l.ref for l in lines)))
    if any(l.account_code for l in tb.lines):
        missing = [l for l in tb.lines if not l.account_code]
        if missing:
            findings.append(Finding("MISSING_ACCOUNT_CODE", REVIEW,
                                    f"{len(missing)} line(s) have no account code: "
                                    + ", ".join(l.account_name for l in missing[:6]) + ".", "SD-016",
                                    tuple(l.ref for l in missing)))
    for line in tb.account_lines():
        balance = line.net_debit
        if balance == 0:
            continue
        if _SUSPENSE.search(line.account_name):
            findings.append(Finding("SUSPENSE_BALANCE", REVIEW,
                                    f"{line.account_name} holds {abs(balance)}; it must be investigated and cleared.",
                                    "SD-016", (line.ref,)))
            continue
        if _CONTRA.search(line.account_name):
            continue
        if balance < 0 and _NORMALLY_DEBIT.search(line.account_name) and not _NORMALLY_CREDIT.search(line.account_name):
            findings.append(Finding("SIGN_ANOMALY", REVIEW,
                                    f"{line.account_name} has a credit balance ({abs(balance)}); it normally has a "
                                    f"debit balance. Check the sign.", "SD-016", (line.ref,)))
        elif balance > 0 and _NORMALLY_CREDIT.search(line.account_name) and not _NORMALLY_DEBIT.search(line.account_name):
            findings.append(Finding("SIGN_ANOMALY", REVIEW,
                                    f"{line.account_name} has a debit balance ({balance}); it normally has a credit "
                                    f"balance. Check the sign.", "SD-016", (line.ref,)))
    if len(tb.year_columns) < 2:
        findings.append(Finding("COMPARATIVE_MISSING", REVIEW,
                                "No prior-year figures are in the file. They are never invented; statutory statements "
                                "will need them.", "SD-008"))
    if any(l.hidden for l in tb.lines):
        findings.append(Finding("HIDDEN_LINES_INCLUDED", INFO,
                                "Some lines come from hidden rows or sheets and are included.", "SD-003"))
    return report
