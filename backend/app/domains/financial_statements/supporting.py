"""Control accounts agreed to supporting records (Document 04 rule SD-017).

A receivables ageing, a bank reconciliation, an inventory listing or a fixed
asset register is uploaded beside the trial balance. Its total is compared,
exactly, with the trial-balance line it supports; a difference is a hard
stop, an agreement is recorded. Nothing is adjusted to make them agree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .findings import HARD_STOP, INFO, Finding
from .intake import receive
from .normalize import ZERO, parse_amount

KINDS: dict[str, tuple[str, str]] = {
    "receivables_ageing": ("bs.trade_receivables", "Trade and other receivables"),
    "bank_reconciliation": ("bs.cash", "Cash at bank and in hand"),
    "inventory_listing": ("bs.inventories", "Inventories"),
    "fixed_asset_register": ("bs.ppe", "Property, plant and equipment"),
}
_AMOUNT_HEADER = re.compile(r"\b(?:total|balance|amount|outstanding|closing|net\s+book\s+value|nbv|carrying|value)\b", re.I)
_TOTAL_ROW = re.compile(r"^\s*(?:grand\s+)?(?:sub)?totals?\b", re.I)
# A bank reconciliation states the reconciled balance on a labelled row.
_BANK_BALANCE = re.compile(r"balance\s+per\s+(?:cash\s+book|ledger|books)|adjusted\s+(?:cash\s+book\s+)?balance", re.I)


@dataclass(frozen=True)
class SupportingTotal:
    kind: str
    filename: str
    sha256: str
    total: Decimal | None
    basis: str


def total_of(kind: str, filename: str, content: bytes) -> tuple[SupportingTotal, list[Finding]]:
    parsed = receive(filename, content, "supporting")
    if parsed.rejected:
        return SupportingTotal(kind, filename, parsed.manifest.sha256, None, "rejected"), list(parsed.findings)
    rows = [[c.text for c in row] for row in parsed.rows]
    if kind == "bank_reconciliation":
        for row in rows:
            label = " ".join(row)
            if _BANK_BALANCE.search(label):
                amounts = [parse_amount(t) for t in row]
                values = [a.value for a in amounts if a.value is not None]
                if values:
                    return SupportingTotal(kind, filename, parsed.manifest.sha256, values[-1],
                                           f"row '{label.strip()[:60]}'"), []
    header_index = next((i for i, row in enumerate(rows[:25]) if any(_AMOUNT_HEADER.search(t) for t in row)), None)
    if header_index is None:
        return SupportingTotal(kind, filename, parsed.manifest.sha256, None, "no amount column"), [Finding(
            "SUPPORTING_UNREADABLE", HARD_STOP, f"{filename}: no total, balance or amount column was found.", "SD-017")]
    header = rows[header_index]
    column = max(i for i, t in enumerate(header) if _AMOUNT_HEADER.search(t))   # the right-most amount column
    total, invalid = ZERO, 0
    for row in rows[header_index + 1:]:
        if column >= len(row) or _TOTAL_ROW.match(row[0] if row else ""):
            continue
        amount = parse_amount(row[column])
        if amount.status in ("INVALID", "LOCALE_AMBIGUOUS"):
            invalid += 1
        total += amount.value or ZERO
    findings = [Finding("SUPPORTING_INVALID_AMOUNTS", HARD_STOP,
                        f"{filename}: {invalid} amount(s) could not be read.", "SD-017")] if invalid else []
    return SupportingTotal(kind, filename, parsed.manifest.sha256, total, f"sum of column '{header[column]}'"), findings


def reconcile(kind: str, supporting: SupportingTotal, line_totals: dict[str, Decimal]) -> Finding:
    """The supporting record's total against the trial-balance line, exactly."""
    line_id, label = KINDS[kind]
    ledger = line_totals.get(line_id, ZERO)
    if supporting.total is None:
        return Finding("SUPPORTING_UNREADABLE", HARD_STOP, f"{supporting.filename}: no total could be read.", "SD-017")
    if supporting.total == ledger:
        return Finding("SUPPORTING_AGREED", INFO,
                       f"{label}: {supporting.filename} ({supporting.basis}) agrees with the trial balance at {ledger}.",
                       "SD-017")
    return Finding("SUBLEDGER_MISMATCH", HARD_STOP,
                   f"{label}: the trial balance shows {ledger}, {supporting.filename} shows {supporting.total} "
                   f"({supporting.basis}); difference {ledger - supporting.total}.", "SD-017")
