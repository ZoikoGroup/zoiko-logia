"""G1 + G2 pipeline: ledger → sealed snapshot → compiled facts → reconcilers.

The result is at most DRAFT_RECONCILED. Unsupported context is UNAVAILABLE;
untrustworthy input, an open exception or a failed invariant is
DRAFT_INCOMPLETE with the exact reason attached.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .compiler import CompiledReport, compile_report
from .ledger import LedgerError
from .mapping import mapping_exceptions, parse_account_map
from .reconcile import ReconcilerOutcome, reconcile
from .snapshot import ImportReceipt, seal_snapshot
from .states import ReportState

# Request-level problems: the report basis itself is unsupported.
_UNAVAILABLE_CODES = frozenset({"context_invalid", "period_invalid", "fx_missing_or_inapplicable"})


@dataclass
class ReportDraft:
    state: ReportState
    error_code: str | None = None
    error_detail: str | None = None
    snapshot_hash: str | None = None
    receipt: ImportReceipt | None = None
    compiled: CompiledReport | None = None
    outcomes: list[ReconcilerOutcome] = field(default_factory=list)

    @property
    def exceptions(self) -> list[dict]:
        return self.compiled.exceptions if self.compiled else []


def build_draft(ledger: dict, account_map: dict) -> ReportDraft:
    try:
        snapshot = seal_snapshot(ledger)
        parsed_map = parse_account_map(account_map)
    except LedgerError as error:
        state = ReportState.UNAVAILABLE if error.code in _UNAVAILABLE_CODES else ReportState.DRAFT_INCOMPLETE
        return ReportDraft(state=state, error_code=error.code, error_detail=str(error))

    compiled = compile_report(snapshot, parsed_map, mapping_exceptions(snapshot.accounts, parsed_map))
    outcomes = reconcile(compiled)
    if compiled.exceptions:
        state, code = ReportState.DRAFT_INCOMPLETE, "snapshot_incomplete"
    elif not all(outcome.passed for outcome in outcomes):
        state, code = ReportState.DRAFT_INCOMPLETE, "reconciliation_failed"
    else:
        state, code = ReportState.DRAFT_RECONCILED, None
    return ReportDraft(state=state, error_code=code, snapshot_hash=snapshot.snapshot_hash,
                       receipt=snapshot.receipt, compiled=compiled, outcomes=outcomes)
