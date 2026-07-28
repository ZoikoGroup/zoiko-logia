"""Reviewed educational procedure for a routine month-end financial close."""
from __future__ import annotations


MONTH_END_CLOSE_GOVERNED_SOURCE_ID = "src-kriton-month-end-close-procedure"
MONTH_END_CLOSE_NODE_PREFIX = "month-end-close-procedure-"

_PROCEDURE_TEXT = """Kriton Month-End Financial Close Educational Procedure, version 1.0.

Purpose: The month-end close completes transaction processing, reconciles
material accounts, records supported adjustments, reviews the resulting
financial information, and locks or controls the completed period.

Typical sequence:
1. Establish the close calendar, responsibilities, cut-off date, and required
   reviewer approvals.
2. Complete transaction entry and apply cut-off procedures for revenue,
   purchases, payroll, cash, and other significant cycles.
3. Reconcile bank accounts, receivables, payables, inventory, fixed assets,
   payroll, intercompany balances, and other material balance-sheet accounts.
4. Prepare and support recurring and non-recurring journal entries, including
   accruals, prepayments, depreciation, allocations, and approved corrections.
5. Resolve reconciliation differences and review unusual, missing, duplicate,
   or late transactions.
6. Produce the trial balance and draft financial statements, then perform
   analytical review against budgets, prior periods, and expected activity.
7. Complete management review, document open items, and obtain the approvals
   required by the entity's close controls.
8. Issue the approved reporting package, retain supporting evidence, restrict
   subsequent postings, and track approved post-close adjustments separately.

The exact timing and ownership depend on the entity's systems, transaction
volume, reporting framework, materiality, and internal-control design. This
general procedure does not include legal transaction-closing events such as a
merger, securities subscription, or acquisition closing date.
"""


def to_month_end_close_rag_chunk() -> dict:
    return {
        "text": _PROCEDURE_TEXT,
        "metadata": {
            "source_id": MONTH_END_CLOSE_GOVERNED_SOURCE_ID,
            "title": "Kriton Month-End Financial Close Educational Procedure",
            "version": "1.0",
            "jurisdiction": "GLOBAL",
        },
        "score": 1.0,
        "node_id": f"{MONTH_END_CLOSE_NODE_PREFIX}v1",
    }
