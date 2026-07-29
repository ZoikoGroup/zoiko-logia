"""Reviewed educational grounding for core accounting processes."""
from __future__ import annotations


ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID = "src-kriton-accounting-fundamentals"
ACCOUNTING_FUNDAMENTALS_NODE_PREFIX = "accounting-fundamentals-"

_TEXT = """Kriton Accounting Fundamentals: Cash Basis and Accrual Basis, version 1.0.

Cash-basis accounting generally recognizes cash receipts when received and cash
payments when paid. It is simpler and emphasizes cash movement, but timing can
make performance across periods less representative of the underlying economic
activity.

Accrual-basis accounting recognizes revenue when earned and expenses when
incurred, subject to the applicable reporting framework, rather than waiting
for the related cash receipt or payment. Receivables, payables, accruals, and
prepayments connect the economic activity to the period in which it belongs.
This usually gives a more complete view of financial performance and position,
but requires estimates, period-end adjustments, and stronger accounting
processes.

Example without fixed amounts: a credit sale is normally recognized as revenue
and a receivable when the relevant recognition requirements are met; collection
later reduces the receivable and increases cash. Under a simple cash basis, the
receipt is generally recognized when cash is collected. The reporting method an
entity is permitted or required to use depends on the applicable legal, tax, and
financial-reporting requirements.

Reviewed core-process coverage also includes accounts payable and order to cash.
Accounts payable proceeds through invoice capture, validation and matching,
exception resolution, account coding and approval, liability posting, controlled
payment, settlement posting, and reconciliation of supplier, subledger, ledger,
and cash records. Order to cash proceeds through customer-order validation,
fulfilment evidence, invoicing, revenue and receivable recognition under the
applicable framework, collection monitoring, cash application, and reconciliation
of customer and receivable records to the general ledger. Responsibilities,
evidence, approvals, segregation of duties, and exception resolution are control
considerations throughout both processes.

An educational audit-evidence workflow begins by linking the relevant account,
assertion, risk, and criteria to an audit objective. Procedures are designed to
obtain relevant and reliable evidence, then performed and documented with their
source, scope, date, preparer, and result. The auditor evaluates relevance,
reliability, sufficiency, consistency, and contradictory information. Exceptions
and missing or inconsistent support are investigated, with additional procedures
when necessary. Review confirms that the documentation supports the conclusion
and that significant judgments and exceptions were appropriately reviewed.
Unresolved, contradictory, or insufficient evidence is escalated before the
related audit conclusion is finalized. Exact procedures depend on the engagement,
applicable auditing standards, assessed risks, materiality, and professional
judgment.

Trial-balance preparation starts after routine journal entries are posted to the
general ledger. Its purpose is to organize ledger balances and test whether total
debits equal total credits before financial statements are prepared. The preparer lists ledger accounts in chart-of-accounts order,
extracts each ending debit or credit balance, totals both columns, and confirms
that total debits equal total credits. Differences can result from omitted
accounts, one-sided entries, transpositions, incorrect signs, or posting errors.
Equal totals do not prove that every entry is correct. Supported and approved
period-end adjustments, including accruals, deferrals, depreciation, and
corrections, are then posted. The adjusted balances are re-extracted and reviewed
before they are used to prepare financial statements. The final trial balance,
adjustments, unresolved items, and preparer/reviewer evidence should be retained.
"""


def to_accounting_fundamentals_rag_chunk() -> dict:
    return {
        "text": _TEXT,
        "metadata": {
            "source_id": ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID,
            "title": "Kriton Accounting Fundamentals — Core Processes",
            "version": "1.0",
            "jurisdiction": "GLOBAL",
        },
        "score": 1.0,
        "node_id": f"{ACCOUNTING_FUNDAMENTALS_NODE_PREFIX}v1",
    }
