"""Account-to-statement-line classification (Document 04 stage P4, rules
SD-025 to SD-036).

Every proposal is a SUGGESTION until a reviewer approves it. An account whose
statement line depends on facts its name does not give (Utilities,
Marketing, Bank charges, Interest, …) is NEEDS_EVIDENCE: the evidence that
would decide it is named, and no line is chosen for it. An account no rule
recognises is UNMAPPED, never "Other". A split across lines must sum exactly
to the account's balance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from decimal import Decimal

from .normalize import ZERO, NormalizedTB, TBLine

# Stable statement line IDs (survive label changes) and their sections.
LINES: dict[str, tuple[str, str]] = {
    "pl.revenue": ("Revenue", "profit_or_loss"),
    "pl.other_income": ("Other operating income", "profit_or_loss"),
    "pl.cost_of_sales": ("Cost of sales", "profit_or_loss"),
    "pl.distribution_costs": ("Distribution costs", "profit_or_loss"),
    "pl.administrative_expenses": ("Administrative expenses", "profit_or_loss"),
    "pl.finance_income": ("Interest receivable and similar income", "profit_or_loss"),
    "pl.finance_costs": ("Interest payable and similar expenses", "profit_or_loss"),
    "pl.tax": ("Tax on profit", "profit_or_loss"),
    "bs.ppe": ("Property, plant and equipment", "balance_sheet"),
    "bs.intangibles": ("Intangible assets", "balance_sheet"),
    "bs.inventories": ("Inventories", "balance_sheet"),
    "bs.trade_receivables": ("Trade and other receivables", "balance_sheet"),
    "bs.cash": ("Cash at bank and in hand", "balance_sheet"),
    "bs.trade_payables": ("Trade and other payables", "balance_sheet"),
    "bs.tax_payable": ("Corporation tax payable", "balance_sheet"),
    "bs.borrowings": ("Borrowings", "balance_sheet"),
    "bs.deferred_tax": ("Deferred tax", "balance_sheet"),
    "bs.provisions": ("Provisions", "balance_sheet"),
    "eq.share_capital": ("Called up share capital", "equity"),
    "eq.retained_earnings": ("Retained earnings", "equity"),
    "eq.distributions": ("Dividends (distributions to owners)", "equity"),
}

# Name-only classification is unreliable for these: the evidence that decides.
_NEEDS_EVIDENCE: tuple[tuple[re.Pattern, tuple[str, ...], str], ...] = (
    (re.compile(r"utilit", re.I), ("pl.cost_of_sales", "pl.distribution_costs", "pl.administrative_expenses"),
     "site invoices, meters or cost centres (factory, warehouse or head office)"),
    (re.compile(r"marketing|advertis", re.I), ("pl.distribution_costs", "pl.administrative_expenses"),
     "what the spend was for (selling or corporate)"),
    (re.compile(r"bank\s+charges|bank\s+fees", re.I), ("pl.administrative_expenses", "pl.finance_costs"),
     "bank statements: routine service fees or borrowing costs"),
    (re.compile(r"interest\s+(?:income|received|receivable)|other\s+income", re.I), ("pl.finance_income", "pl.other_income"),
     "the source of the income (deposits, loans or trading)"),
    (re.compile(r"salar|wages|payroll|staff\s+costs", re.I),
     ("pl.cost_of_sales", "pl.distribution_costs", "pl.administrative_expenses"),
     "a department or direct-labour split"),
    (re.compile(r"\brent\b|rates", re.I), ("pl.cost_of_sales", "pl.distribution_costs", "pl.administrative_expenses"),
     "which premises (factory, warehouse or office)"),
    (re.compile(r"depreciation", re.I), ("pl.cost_of_sales", "pl.distribution_costs", "pl.administrative_expenses"),
     "the fixed asset register (which assets, used where)"),
)
# Unambiguous names, in order; (pattern, line, normal side).
_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"dividends?\s*(?:paid|declared)?|drawings", re.I), "eq.distributions"),
    (re.compile(r"share\s+capital|ordinary\s+shares|share\s+premium", re.I), "eq.share_capital"),
    (re.compile(r"retained\s+(?:earnings|profits?)|profit\s+and\s+loss\s+reserve|reserves?", re.I), "eq.retained_earnings"),
    (re.compile(r"deferred\s+tax", re.I), "bs.deferred_tax"),
    (re.compile(r"(?:corporation|income)\s+tax\s+(?:payable|liability)|tax\s+payable", re.I), "bs.tax_payable"),
    (re.compile(r"(?:corporation|income)\s+tax(?:\s+(?:charge|expense))?|tax\s+(?:charge|expense)", re.I), "pl.tax"),
    (re.compile(r"interest\s+(?:payable|expense|paid)|finance\s+costs?|loan\s+interest", re.I), "pl.finance_costs"),
    (re.compile(r"cost\s+of\s+(?:sales|goods)|purchases|direct\s+costs?", re.I), "pl.cost_of_sales"),
    (re.compile(r"revenue|sales|turnover|fee\s+income", re.I), "pl.revenue"),
    (re.compile(r"property|plant|equipment|machinery|vehicles?|fixtures|buildings?|\bland\b|computer|furniture|"
                r"accumulated\s+depreciation", re.I), "bs.ppe"),
    (re.compile(r"intangible|goodwill|software\s+licen|patents?|trademarks?", re.I), "bs.intangibles"),
    (re.compile(r"inventor|stock", re.I), "bs.inventories"),
    (re.compile(r"receivables?|debtors|prepayments?|allowance\s+for|doubtful", re.I), "bs.trade_receivables"),
    (re.compile(r"\bcash\b|\bbank\b(?!\s+(?:charges|fees|loan))|petty", re.I), "bs.cash"),
    (re.compile(r"loan|borrowing|overdraft|mortgage|debenture", re.I), "bs.borrowings"),
    (re.compile(r"payables?|creditors|accruals?|vat|paye|deferred\s+income", re.I), "bs.trade_payables"),
    (re.compile(r"provision", re.I), "bs.provisions"),
    (re.compile(r"insurance|professional|legal|audit|accountancy|office|stationery|telephone|postage|subscription|"
                r"travel|repairs|maintenance|bad\s+debt|training|cleaning|general\s+expenses|administrat|"
                r"employer|pension|national\s+insurance", re.I), "pl.administrative_expenses"),
    (re.compile(r"carriage|delivery|distribution|selling|commission", re.I), "pl.distribution_costs"),
)

SUGGESTED, NEEDS_EVIDENCE, UNMAPPED, APPROVED = "SUGGESTED", "NEEDS_EVIDENCE", "UNMAPPED", "APPROVED"


@dataclass(frozen=True)
class Allocation:
    line_id: str
    amount: Decimal


@dataclass(frozen=True)
class MappingProposal:
    account_key: str
    account_name: str
    balance: Decimal                       # net debit
    status: str
    line_id: str | None = None
    candidates: tuple[str, ...] = ()
    evidence_required: str = ""
    basis: str = ""
    allocations: tuple[Allocation, ...] = field(default_factory=tuple)
    reviewer: str | None = None
    source: str = ""

    def to_dict(self) -> dict:
        return {"account_key": self.account_key, "account_name": self.account_name, "balance": str(self.balance),
                "status": self.status, "line_id": self.line_id,
                "line_label": LINES[self.line_id][0] if self.line_id in LINES else None,
                "candidates": [{"line_id": c, "label": LINES[c][0]} for c in self.candidates],
                "evidence_required": self.evidence_required, "basis": self.basis,
                "allocations": [{"line_id": a.line_id, "amount": str(a.amount)} for a in self.allocations],
                "reviewer": self.reviewer, "source": self.source}


def propose(line: TBLine) -> MappingProposal:
    name = line.account_name
    base = dict(account_key=line.key, account_name=name, balance=line.net_debit, source=line.ref)
    for pattern, candidates, evidence in _NEEDS_EVIDENCE:
        if pattern.search(name):
            return MappingProposal(status=NEEDS_EVIDENCE, candidates=candidates, evidence_required=evidence,
                                   basis="The account name does not establish its function.", **base)
    for pattern, line_id in _RULES:
        if pattern.search(name):
            return MappingProposal(status=SUGGESTED, line_id=line_id,
                                   basis=f"Suggested from the account name '{name}'; confirm before approval.", **base)
    return MappingProposal(status=UNMAPPED, basis="No rule recognises this account; map it manually.", **base)


def propose_all(tb: NormalizedTB) -> list[MappingProposal]:
    """One proposal per account (a ledger's entries are summed per account)."""
    return [propose(line) for line in tb.account_lines()]


class MappingError(ValueError):
    pass


def approve(proposal: MappingProposal, *, reviewer: str, line_id: str | None = None,
            allocations: list[tuple[str, Decimal]] | None = None, evidence_ref: str = "") -> MappingProposal:
    """A reviewer's decision: one line, or a split whose parts sum exactly
    to the balance (SD-026). Needs-evidence accounts need an evidence reference."""
    if proposal.status == NEEDS_EVIDENCE and not evidence_ref:
        raise MappingError(f"{proposal.account_name}: approval needs the evidence reference ({proposal.evidence_required}).")
    if allocations:
        parts = tuple(Allocation(l, Decimal(a)) for l, a in allocations)
        if any(p.line_id not in LINES for p in parts):
            raise MappingError("Unknown statement line in the split.")
        if sum((p.amount for p in parts), ZERO) != abs(proposal.balance):
            raise MappingError(f"The split must sum exactly to {abs(proposal.balance)}.")
        return replace(proposal, status=APPROVED, line_id=None, allocations=parts, reviewer=reviewer,
                       basis=f"Split approved by {reviewer}" + (f"; evidence {evidence_ref}" if evidence_ref else ""))
    chosen = line_id or proposal.line_id
    if chosen not in LINES:
        raise MappingError(f"{proposal.account_name}: choose a statement line.")
    return replace(proposal, status=APPROVED, line_id=chosen, reviewer=reviewer,
                   basis=f"Approved by {reviewer}" + (f"; evidence {evidence_ref}" if evidence_ref else ""))
