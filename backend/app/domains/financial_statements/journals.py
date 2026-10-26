"""Proposed correcting and reclassification journals (Document 04 stage P5,
rules SD-037 to SD-045).

A proposal must balance and say why. Its effect on every statement line and
on profit before tax is simulated before review. A reclassification (moving
an amount between lines) changes presentation only: profit before tax stays
the same. Nothing is ever posted: posting to a ledger is a separately
authorised action outside this engine.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from .mapping import APPROVED, LINES, MappingProposal
from .normalize import ZERO

RECLASSIFICATION, ADJUSTMENT = "RECLASSIFICATION", "ADJUSTMENT"

# SD-035 / SD-041: what a correction is decides how it is accounted for
# (FRS 102 Section 10 / IAS 8). An estimate change is never a restatement by
# default; a prior-period error or policy change needs restated comparatives.
CORRECTION_TYPES: dict[str, str] = {
    "PRESENTATION": "Reclassification between lines only; no change to profit or net assets.",
    "CURRENT_PERIOD": "Correction of the current period; recognised in this period.",
    "ESTIMATE_CHANGE": "Change in an accounting estimate; applied prospectively, no restatement.",
    "PRIOR_PERIOD_ERROR": "Material prior-period error; corrected retrospectively with restated comparatives and "
                          "disclosure (FRS 102 Section 10 / IAS 8).",
    "POLICY_CHANGE": "Change in accounting policy; applied retrospectively unless a transition rule says otherwise, "
                     "with disclosure.",
}
RESTATING = frozenset({"PRIOR_PERIOD_ERROR", "POLICY_CHANGE"})


class JournalError(ValueError):
    pass


@dataclass(frozen=True)
class JournalLine:
    line_id: str                   # statement line moved to / from
    debit: Decimal = ZERO
    credit: Decimal = ZERO


@dataclass(frozen=True)
class JournalProposal:
    journal_id: str
    kind: str
    reason: str
    lines: tuple[JournalLine, ...]
    evidence_refs: tuple[str, ...]
    created_by: str
    review_status: str = "PENDING_REVIEW"
    posting_status: str = "NOT_POSTED"          # never changed here (SD-043, SD-044)
    reviewer: str | None = None
    correction_type: str = "CURRENT_PERIOD"

    @property
    def requires_restatement(self) -> bool:
        return self.correction_type in RESTATING

    def to_dict(self) -> dict:
        return {"journal_id": self.journal_id, "kind": self.kind, "reason": self.reason,
                "correction_type": self.correction_type, "treatment": CORRECTION_TYPES[self.correction_type],
                "requires_restatement": self.requires_restatement,
                "lines": [{"line_id": l.line_id, "debit": str(l.debit), "credit": str(l.credit)} for l in self.lines],
                "evidence_refs": list(self.evidence_refs), "created_by": self.created_by,
                "review_status": self.review_status, "posting_status": self.posting_status, "reviewer": self.reviewer}


def propose_journal(*, kind: str, reason: str, lines: list[tuple[str, Decimal, Decimal]], created_by: str,
                    evidence_refs: list[str] | None = None, correction_type: str | None = None) -> JournalProposal:
    if kind not in (RECLASSIFICATION, ADJUSTMENT):
        raise JournalError("A journal is a reclassification or an adjustment.")
    correction_type = correction_type or ("PRESENTATION" if kind == RECLASSIFICATION else "CURRENT_PERIOD")
    if correction_type not in CORRECTION_TYPES:
        raise JournalError(f"Unknown correction type; use one of {', '.join(CORRECTION_TYPES)}.")
    if kind == RECLASSIFICATION and correction_type != "PRESENTATION":
        raise JournalError("A reclassification is a presentation change only.")
    if not reason.strip():
        raise JournalError("A journal needs a reason.")
    parsed = tuple(JournalLine(line_id, Decimal(dr), Decimal(cr)) for line_id, dr, cr in lines)
    if len(parsed) < 2 or any(l.line_id not in LINES for l in parsed):
        raise JournalError("A journal needs at least two lines on known statement lines.")
    if any(l.debit < 0 or l.credit < 0 or (l.debit and l.credit) for l in parsed):
        raise JournalError("Each line is either a positive debit or a positive credit.")
    debits, credits = sum((l.debit for l in parsed), ZERO), sum((l.credit for l in parsed), ZERO)
    if debits != credits:
        raise JournalError(f"The journal does not balance: debits {debits}, credits {credits}.")
    if kind == RECLASSIFICATION:
        delta: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for l in parsed:
            delta[l.line_id] += l.debit - l.credit
        if profit_before_tax(delta) != 0:
            raise JournalError("A reclassification cannot change profit before tax; this is an adjustment.")
    identity = "|".join([kind, correction_type, reason, created_by,
                         *(f"{l.line_id}:{l.debit}:{l.credit}" for l in parsed)])
    return JournalProposal(journal_id="jnl-" + hashlib.sha256(identity.encode()).hexdigest()[:16], kind=kind,
                           reason=reason, lines=parsed, evidence_refs=tuple(evidence_refs or ()), created_by=created_by,
                           correction_type=correction_type)


def review_journal(journal: JournalProposal, *, reviewer: str, approve: bool) -> JournalProposal:
    if reviewer == journal.created_by:
        raise JournalError("The person who proposed a journal cannot review it.")
    from dataclasses import replace
    return replace(journal, review_status="APPROVED" if approve else "REJECTED", reviewer=reviewer)


def line_totals(mappings: list[MappingProposal]) -> dict[str, Decimal]:
    """Net debit per statement line from approved mappings."""
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for m in mappings:
        if m.status != APPROVED:
            continue
        if m.allocations:
            sign = 1 if m.balance >= 0 else -1
            for part in m.allocations:
                totals[part.line_id] += sign * part.amount
        elif m.line_id:
            totals[m.line_id] += m.balance
    return dict(totals)


def profit_before_tax(totals: dict[str, Decimal]) -> Decimal:
    """Income minus expenses, from net debits of profit-or-loss lines, before tax."""
    return -sum((v for k, v in totals.items() if k.startswith("pl.") and k != "pl.tax"), ZERO)


def simulate(mappings: list[MappingProposal], journal: JournalProposal) -> dict:
    """Before/after net debit of every affected line and profit before tax (SD-039)."""
    before = line_totals(mappings)
    after = dict(before)
    for l in journal.lines:
        after[l.line_id] = after.get(l.line_id, ZERO) + l.debit - l.credit
    affected = sorted({l.line_id for l in journal.lines})
    return {
        "journal_id": journal.journal_id,
        "lines": [{"line_id": k, "label": LINES[k][0], "before": str(before.get(k, ZERO)), "after": str(after[k])}
                  for k in affected],
        "profit_before_tax_before": str(profit_before_tax(before)),
        "profit_before_tax_after": str(profit_before_tax(after)),
        "posting_status": journal.posting_status,
    }
