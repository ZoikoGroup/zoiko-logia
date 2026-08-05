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

Retained earnings is the cumulative portion of profit retained in the business
rather than distributed to owners. Ending retained earnings equals beginning
retained earnings plus net income (or minus a net loss), less dividends or other
owner distributions recognized in retained earnings. Prior-period adjustments
may also affect the opening balance under the applicable reporting framework.
For example, beginning retained earnings of $100,000 plus net income of $50,000
less dividends of $20,000 produces ending retained earnings of $130,000.

When collection of an existing customer receivable is correctly debited to cash
but incorrectly credited to revenue a second time, revenue is overstated and the
receivable remains overstated. The correcting entry debits revenue and credits
accounts receivable for the duplicated amount. The original invoice entry and
cash receipt should be inspected before posting the correction.

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

Duplicate supplier-payment investigation includes confirming the apparent
duplicate across invoice, payable, payment, bank, and ledger records; inspecting
matching and approval evidence; determining whether two valid obligations or a
duplicate occurred; containing or correcting the issue under approved controls;
reconciling the affected records; documenting the conclusion; and assessing the
control cause.

A controlled supplier-invoice process captures the invoice and supplier data,
validates required fields and arithmetic, checks for duplicates, matches the
invoice to purchasing and receipt evidence where applicable, resolves
exceptions, obtains authorization, posts the liability and related expense or
asset, releases and records payment, and retains an audit log linking the
documents, approvals, journal entries, payment reference, timestamps, and users.

A controlled order-to-cash process validates a customer order and credit,
records fulfilment evidence, issues an invoice, applies the applicable revenue
recognition requirements, records and monitors the receivable, applies cash to
the correct invoice, reconciles customer, ledger, and bank records, and retains
approvals and exception evidence.

An employee expense-claim process captures the claim, business purpose, and
receipts; validates completeness, arithmetic, duplicates, and policy limits;
obtains manager approval; verifies accounting and tax coding and approval
authority; releases reimbursement; records settlement; and retains the claim,
support, approvals, exceptions, payment reference, timestamps, and users.

Audit-exception resolution documents the criterion, condition, affected
assertion, population, amount, and evidence; assesses significance and risk;
obtains and evaluates management's response and support; performs additional
procedures when evidence is insufficient or contradictory; submits the matter
for review and escalation when required; and records the final conclusion,
corrections, approvals, and follow-up actions.

An unmatched supplier invoice is held from payment while the supplier, invoice,
duplicate status, purchase order or contract, receipt or service confirmation,
amount, tax, coding, and authorization are investigated. A valid invoice is
matched and approved, handled through an authorized exception, corrected, or
rejected. Independent review precedes payment, and the resolution is reconciled
and retained.

An invoice evidence relationship can link an invoice to its supplier, purchase
order, goods receipt, payment, and ledger entry. A sales-invoice evidence chain
can link the invoice to the customer order, delivery evidence, contract, bank
receipt, and general-ledger entry. These expected relationships organize an
investigation but do not by themselves authenticate the records or prove that a
transaction occurred.

A jurisdiction-neutral business tax compliance process reconciles transaction
data to the ledgers, applies the applicable jurisdiction's rules, prepares the
return and supporting schedules, performs an internal review and authorization,
submits through the relevant filing method, tracks payment obligations, and
retains source records, calculations, approvals, correspondence, payment
evidence, and submission confirmation. Forms, calculations, deadlines, and
retention periods depend on the jurisdiction and tax type.

A jurisdiction-neutral indirect-tax process captures transaction attributes,
classifies the transaction under current applicable rules, calculates tax,
validates invoice requirements, reconciles tax data to accounting records,
prepares and internally approves the return, submits and pays through the
applicable methods, and retains invoices, calculations, approvals, payment, and
submission evidence. Classification rules, rates, forms, deadlines, and record
retention depend on the jurisdiction.

Revenue cut-off review traces cash and ledger entries to the customer, invoice,
contract, fulfilment, delivery, acceptance, and service evidence. Cash timing
alone does not determine accrual-basis recognition. Relevant terms and dates
before and after period end are compared, exceptions are investigated, and
supported corrections are approved and documented.

Liability-completeness review reconciles supplier records, examines post-period
invoices and payments, receiving records, unmatched documents, open purchase
orders, accruals, disputes, and bank activity, and determines when the underlying
goods or services were received. Missing, late, duplicate, or incorrectly dated
items are investigated and supported adjustments are reviewed and retained.

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

Evidence review links each item to the relevant account, assertion, risk, and
conclusion. Relevance, source independence, authenticity, accuracy, preparation
controls, directness, quantity, and quality are evaluated. Contradictory source
documents and ledger amounts are compared with other evidence and their source
data and calculations are verified. Missing, unreliable, contradictory, or
insufficient evidence leads to additional procedures or escalation before a
conclusion is finalized and documented.

An evidence-assessment matrix may score relevance, source independence,
authenticity, directness, control over preparation, consistency, and coverage.
Scores support—rather than replace—professional judgment. A critical failure,
such as suspected alteration or unresolved contradictory evidence, cannot be
offset by a high total score and requires more work or escalation.

A disproportionate increase in accounts receivable compared with revenue can
result from slower collections, extended credit terms, customer disputes,
concentration in newer sales, cutoff errors, unapplied cash, inadequate write-offs
or allowance estimates, or fictitious/premature revenue. Relevant procedures
include reconciling the subledger, analyzing aging and days sales outstanding,
testing subsequent receipts, confirming selected balances, testing sales cutoff
and credit notes, inspecting contracts/invoices/delivery evidence, testing the
allowance, reviewing manual journal entries, and evaluating contradictory trends.

Working capital equals current assets minus current liabilities. It is a basic
measure of net short-term resources and helps users assess liquidity and operating
capacity. It must be interpreted with cash-flow timing, asset quality, industry
conditions, seasonality, and related ratios; positive working capital alone does
not prove that obligations can be paid when due.

Intellectual property is a broad term for legally protected creations and
commercially valuable intangible knowledge. Common categories include patents,
trademarks, copyright, and trade secrets. The protection, registration,
ownership, duration, and enforcement rules differ by category and jurisdiction.

Revenue is the consideration recognized from ordinary activities under the
applicable reporting framework. Profit is the residual after relevant expenses
are deducted from revenue; gross, operating, and net profit differ by which
expense layers are included. Revenue therefore is not the same as cash received,
and profit is not the same as cash flow.

Accounts payable represents amounts an entity owes suppliers for goods or
services received on credit. Accounts receivable represents amounts customers
owe the entity for goods or services supplied on credit. Payables are generally
liabilities; receivables are generally assets. Both require subsidiary-ledger,
general-ledger, and supporting-document reconciliation.

A balance sheet presents assets, liabilities, and equity at a reporting date.
An income statement presents revenue, expenses, and profit or loss over a
reporting period. Profit or loss affects equity, so the statements are linked,
but one is a point-in-time position and the other measures period performance.

Audit materiality concerns whether an omission, misstatement, or obscuring of
information could reasonably influence users' decisions. It depends on amount
and nature in the circumstances and requires professional judgment; it is not
defined solely by one fixed percentage.

A company can report an accounting loss while generating positive operating
cash flow when non-cash expenses are added back or working-capital movements
provide cash. For example, depreciation reduces profit without a current cash
payment, while collecting receivables or increasing payables can improve
operating cash flow. A cash balance is a stock at one date and does not itself
prove that cash flow during a period was positive.

Internal audit provides independent and objective assurance and advice within
an organization's governance structure; internal auditors may be employees or
an outsourced provider. External financial-statement auditors are independent
of the entity and express an opinion under the applicable auditing framework.
Their mandates, reporting lines, scope, and independence requirements differ.

Inventory growing substantially faster than sales is a risk indicator rather
than proof of error. Possible causes include planned stocking, purchasing or
production changes, input-price inflation, slower demand, obsolete stock, cutoff
errors, costing errors, or overstated quantities. Relevant procedures include
reconciling the subledger, analyzing quantities, prices, turnover and aging,
observing and test-counting inventory, testing purchase and sales cutoff, testing
cost to invoices and production records, evaluating net realizable value and
obsolescence using subsequent sales, and reviewing unusual journal entries and
contradictory evidence.

For an unexplained account variance, the auditor first verifies the data and
expectation used to identify the variance. The auditor then evaluates both its
amount and qualitative significance, including possible fraud, control, or
disclosure implications; a variance is not dismissed solely because it is below
a quantitative threshold. The auditor considers whether the explanation is
plausible and supported by reliable evidence, whether contradictory information
or control exceptions exist, and whether the evidence obtained is sufficient.
Unexplained, unsupported, contradictory, qualitatively significant, or otherwise
insufficiently evidenced matters require additional procedures or escalation.
The nature, timing, and extent of those procedures depend on the assessed risk,
materiality, assertion, and professional judgment.

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


def _focused_text(query: str) -> str:
    """Return the reviewed section relevant to ``query``.

    The source is intentionally broad, but sending it as one ever-growing
    context chunk can exceed the context fitter's per-response budget and drop
    the mandatory source entirely. Keep the governed source identity unchanged
    while selecting only complete reviewed paragraphs for known deterministic
    topics.
    """
    q = query.lower()
    paragraphs = [part.strip() for part in _TEXT.split("\n\n") if part.strip()]
    if "retained earnings" in q:
        markers = ("Retained earnings is",)
    elif "intellectual propert" in q or "intelectual propert" in q:
        markers = ("Intellectual property is",)
    elif "revenue" in q and "profit" in q:
        markers = ("Revenue is the consideration",)
    elif "accounts payable" in q and "accounts receivable" in q:
        markers = ("Accounts payable represents",)
    elif "balance sheet" in q and "income statement" in q:
        markers = ("A balance sheet presents",)
    elif "materiality" in q and not any(word in q for word in ("calculate", "compute", "benchmark", "percentage")):
        markers = ("Audit materiality concerns",)
    elif "cash flow" in q and "loss" in q:
        markers = ("A company can report",)
    elif "internal audit" in q and "external audit" in q:
        markers = ("Internal audit provides",)
    elif "recorded as revenue again" in q or "correcting journal entry" in q:
        markers = ("When collection of an existing customer receivable",)
    elif "scoring matrix" in q and "evidence" in q:
        markers = ("Evidence review links", "An evidence-assessment matrix")
    elif "internal" in q and "external" in q and "evidence" in q:
        markers = ("Evidence review links", "An evidence-assessment matrix")
    elif "supplier" in q and ("paid twice" in q or "duplicate" in q):
        markers = ("Duplicate supplier-payment investigation",)
    elif "supplier invoice" in q and any(term in q for term in ("sequence", "document upload", "moves from")):
        markers = ("A controlled supplier-invoice process",)
    elif "customer order" in q and any(term in q for term in ("sequence", "credit approval", "moves through")):
        markers = ("A controlled order-to-cash process",)
    elif "employee expense claim" in q:
        markers = ("An employee expense-claim process",)
    elif "audit exception" in q:
        markers = ("Audit-exception resolution",)
    elif "unmatched supplier invoice" in q:
        markers = ("An unmatched supplier invoice",)
    elif "evidence graph" in q or "evidence relationship graph" in q or "sales invoice is supported by" in q:
        markers = ("An invoice evidence relationship",)
    elif "tax" in q and "jurisdiction-neutral" in q:
        markers = (("A jurisdiction-neutral indirect-tax process",) if "indirect" in q else ("A jurisdiction-neutral business tax compliance process",))
    elif ("accounts receivable" in q or "receivables" in q) and any(word in q for word in ("increased", "increase", "grew", "growth")):
        markers = ("A disproportionate increase in accounts receivable",)
    elif "working capital" in q:
        markers = ("Working capital equals",)
    elif "inventory" in q and any(word in q for word in ("increased", "increase", "grew", "growth")):
        markers = ("Inventory growing substantially",)
    elif any(term in q for term in ("account variance", "unexpected account movement", "unexpected movement in an account", "balance that looks unusual")):
        markers = ("For an unexplained account variance",)
    elif "cash" in q and "accrual" in q:
        markers = ("Cash-basis accounting", "Accrual-basis accounting", "Example without fixed amounts")
    else:
        return _TEXT
    selected = [paragraph for paragraph in paragraphs if paragraph.startswith(markers)]
    return paragraphs[0] + "\n\n" + "\n\n".join(selected)


def to_accounting_fundamentals_rag_chunk(query: str = "") -> dict:
    return {
        "text": _focused_text(query),
        "metadata": {
            "source_id": ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID,
            "title": "Kriton Accounting Fundamentals — Core Processes",
            "version": "1.0",
            "jurisdiction": "GLOBAL",
        },
        "score": 1.0,
        "node_id": f"{ACCOUNTING_FUNDAMENTALS_NODE_PREFIX}v1",
    }
