"""Deterministic answers for reviewed Kriton educational procedures.

These answers intentionally trade stylistic variation for accounting
consistency. Every statement maps to the corresponding reviewed source chunk.
"""
from __future__ import annotations

import re


def compose_bank_reconciliation(query: str, ref: str) -> str:
    q = query.lower()
    citation = f"[{ref}]"
    if "journal entr" in q and ("which" in q or "require" in q or "deposit" in q):
        return f"""## Bank-reconciliation journal entries

### Usually requires a book-side journal entry

- Bank fees, interest, automatic payments, returned items, and direct bank credits or debits that are not yet in the ledger. {citation}
- Bookkeeping errors such as omissions, duplicates, transpositions, or incorrect amounts. {citation}

### Usually does not require another journal entry

- Deposits in transit and outstanding checks that are already recorded in the books. These are timing differences used to adjust the bank side of the reconciliation; they are not recorded a second time merely because they have not cleared. {citation}

After recording the required book-side adjustments, confirm that the adjusted bank balance equals the adjusted book balance. {citation}"""

    if "mistake" in q:
        return f"""## Common bank-reconciliation mistakes

1. **Using different periods:** Compare the bank statement and ledger for the same period. {citation}
2. **Skipping the opening balance:** Confirm it agrees with the prior completed reconciliation. {citation}
3. **Missing timing differences:** Track deposits in transit and outstanding checks without recording them twice. {citation}
4. **Ignoring bank-only activity:** Record unbooked fees, interest, automatic payments, returned items, and direct credits or debits. {citation}
5. **Posting unsupported adjustments:** Investigate omissions, duplicates, transpositions, and incorrect amounts before correcting the books. {citation}
6. **Stopping before balances agree:** Verify that adjusted bank and book balances are equal. {citation}
7. **Weak documentation:** Retain support and obtain the review or approval required by the entity's controls. {citation}"""

    if "complete picture" in q or "senior management" in q or ("controls" in q and "risks" in q):
        return f"""## Bank reconciliation: management overview

### Purpose

Bank reconciliation compares the book cash balance with the bank statement, explains timing differences and errors, records book-side adjustments, and confirms that adjusted balances agree. It detects discrepancies but does not by itself prevent every future error. {citation}

### Core process

1. Match the statement and ledger for the same period and confirm the opening balance. {citation}
2. Match deposits, withdrawals, cleared checks, transfers, and direct debits. {citation}
3. Separate timing differences—deposits in transit and outstanding checks—from bank-only items and errors. {citation}
4. Adjust the bank side for timing differences and the book side for unrecorded bank activity and book errors. {citation}
5. Post only the necessary book-side entries, verify equal adjusted balances, and document the review. {citation}

### Journal-entry treatment

Bank fees, interest, automatic payments, returned items, direct credits or debits, and book errors may require entries when they are not already recorded. Deposits in transit and outstanding checks already in the books normally do not require another entry. {citation}

### Key risks and controls

| Risk | Control response |
|---|---|
| Missing or duplicate activity | Match transactions and investigate omissions, duplicates, transpositions, and incorrect amounts. {citation} |
| Unrecorded bank activity | Review fees, interest, automatic payments, returned items, and direct credits or debits. {citation} |
| Unresolved differences | Require adjusted bank and book balances to agree. {citation} |
| Unsupported or unreviewed reconciliation | Retain evidence and obtain the review or approval required by the entity's control procedures. {citation} |

### Management takeaway

Perform the reconciliation regularly; monthly is common, while higher transaction volume or risk may justify greater frequency. Management should monitor unresolved differences, completion, evidence, and approval. {citation}"""

    if "checklist" in q:
        title = "## Bank-reconciliation review checklist"
    else:
        title = "## Bank-reconciliation process"
    return f"""{title}

A bank reconciliation explains the difference between the cash balance in the accounting records and the corresponding bank statement, records book-side adjustments, and confirms that the adjusted balances agree. {citation}

1. **Select the period:** Obtain the bank statement and cash ledger for the same period. {citation}
2. **Confirm the opening balance:** Tie it to the prior completed reconciliation. {citation}
3. **Match transactions:** Match deposits, withdrawals, cleared checks, transfers, direct debits, and other activity. {citation}
4. **Identify timing differences:** List deposits in transit and outstanding checks already recorded in the books. {citation}
5. **Identify bank-only items:** Find fees, interest, automatic payments, returned items, and direct credits or debits not yet recorded. {citation}
6. **Investigate errors:** Resolve omissions, duplicates, transpositions, and incorrect amounts. {citation}
7. **Calculate adjusted balances:** Adjust the bank side for timing differences and the book side for bank-only items and book errors. {citation}
8. **Post book-side entries:** Record required book adjustments; do not record deposits in transit or outstanding checks a second time. {citation}
9. **Verify agreement:** Confirm that adjusted bank and book balances are equal. {citation}
10. **Document and review:** Retain supporting evidence and obtain required approval. {citation}

Monthly reconciliation is common, but frequency should reflect transaction volume, risk, and the entity's control policy. {citation}"""


def compose_month_end_close(query: str, ref: str) -> str:
    citation = f"[{ref}]"
    if re.search(r"preparer|reviewer|supporting evidence|escalation conditions", query, re.I):
        return f"""## Month-end close control checklist

### Preparer controls
1. **Complete and evidence assigned close tasks:** Apply cut-off, prepare supported entries, and reconcile material accounts. {citation}
2. **Investigate exceptions:** Document unusual, missing, duplicate, late, or unreconciled items before sign-off. {citation}

### Reviewer controls
3. **Review reconciliations and entries:** Confirm support, approval, period, account treatment, and resolution of differences. {citation}
4. **Review reporting:** Compare the trial balance and draft statements with budgets, prior periods, and expected activity. {citation}

### Supporting evidence
5. **Retain the close record:** Preserve reconciliations, entry support, exception documentation, approvals, and the reporting package. {citation}

### Escalation conditions
6. **Escalate unresolved or material matters:** Document open items and route significant differences, unsupported entries, control failures, or post-close adjustments for appropriate approval. {citation}"""
    title = "## Month-end financial close timeline" if re.search(r"timeline|schedule", query, re.I) else "## Month-end financial close checklist"
    return f"""{title}

1. **Plan the close:** Establish the calendar, cut-off date, responsibilities, and required approvals. {citation}
2. **Complete transaction entry:** Apply cut-off procedures to revenue, purchases, payroll, cash, and other significant cycles. {citation}
3. **Reconcile material accounts:** Cover bank, receivables, payables, inventory, fixed assets, payroll, intercompany, and other material balance-sheet accounts. {citation}
4. **Prepare supported entries:** Record accruals, prepayments, depreciation, allocations, and approved corrections. {citation}
5. **Resolve exceptions:** Investigate reconciliation differences and unusual, missing, duplicate, or late transactions. {citation}
6. **Review reporting:** Produce the trial balance and draft statements, then compare results with budgets, prior periods, and expected activity. {citation}
7. **Approve the close:** Complete management review, document open items, and obtain required approvals. {citation}
8. **Issue and control the period:** Release the approved reporting package, restrict later postings, and track approved post-close adjustments separately. {citation}

Exact timing and ownership depend on the entity's systems, transaction volume, reporting framework, materiality, and control design. {citation}"""


def compose_accounting_fundamentals(query: str, ref: str) -> str:
    citation = f"[{ref}]"
    if re.search(r"audit\s+evidence|evidence.*audit", query, re.I):
        return f"""## Audit-evidence workflow

1. **Define the objective:** Link the account, assertion, risk, and applicable criteria to the audit procedure. {citation}
2. **Design the procedure:** Select procedures that can produce relevant and reliable evidence for the identified risk. {citation}
3. **Obtain and document evidence:** Perform the procedure and retain its source, scope, date, preparer, and result. {citation}
4. **Evaluate the evidence:** Assess relevance, reliability, sufficiency, consistency, and whether contradictory information exists. {citation}
5. **Investigate exceptions:** Resolve differences, missing support, inconsistent responses, and other exceptions; perform additional procedures when needed. {citation}
6. **Review the work:** Confirm that documentation supports the conclusion and that significant judgments and exceptions received appropriate review. {citation}
7. **Conclude or escalate:** Record the conclusion and escalate unresolved, contradictory, or insufficient evidence before the related audit conclusion is finalized. {citation}

The exact procedures and required evidence depend on the engagement, applicable auditing standards, assessed risks, materiality, and professional judgment. {citation}"""
    if re.search(r"accounts[\s-]*payable|invoice.*approval.*payment", query, re.I):
        return f"""## Accounts-payable process

1. **Receive and capture the invoice:** Record the supplier, invoice details, receipt date, and supporting purchase documentation. {citation}
2. **Validate the invoice:** Check for duplicates and match the invoice to the approved purchase order and evidence of receipt, where applicable. {citation}
3. **Resolve exceptions:** Investigate quantity, price, coding, supplier, tax, or authorization differences before payment. {citation}
4. **Code and approve:** Assign the appropriate account and obtain approval under the entity's authorization controls. {citation}
5. **Post the payable:** Record the approved liability and expense or asset in the appropriate accounting period. {citation}
6. **Schedule and release payment:** Select approved invoices, apply payment controls, and release funds through authorized personnel. {citation}
7. **Post settlement:** Reduce the payable and cash when payment is made, retaining the payment reference. {citation}
8. **Reconcile and review:** Reconcile supplier statements, the payables subledger, general ledger, and cash records; investigate unresolved items. {citation}"""
    if re.search(r"order[\s-]*to[\s-]*cash", query, re.I):
        return f"""## Order-to-cash accounting process

1. **Accept the customer order:** Validate customer, pricing, terms, authorization, and credit requirements. {citation}
2. **Fulfil and evidence delivery:** Retain evidence that goods or services were provided under the approved order. {citation}
3. **Issue the invoice:** Bill the customer using the approved terms and delivery evidence. {citation}
4. **Record revenue and receivable:** Recognize amounts only when the applicable reporting requirements are met and post the customer receivable. {citation}
5. **Monitor collection:** Track due dates, disputes, overdue balances, and approved collection activity. {citation}
6. **Receive and apply cash:** Match receipts to the correct customer and invoice, and investigate unidentified or short payments. {citation}
7. **Reconcile receivables:** Reconcile customer balances and the receivables subledger to the general ledger and resolve differences. {citation}"""
    if re.search(r"trial\s+balance", query, re.I):
        return f"""## Trial-balance preparation process

The purpose of a trial balance is to organize general-ledger balances and test whether total debits equal total credits before financial statements are prepared. It is an important error-detection step, but equal totals do not prove that every transaction was recorded in the correct account or period. {citation}

1. **Confirm the period and ledger completeness:** Ensure routine journal entries for the period have been posted to the general ledger. {citation}
2. **List every ledger account:** Use the chart-of-accounts order and include the accounts required by the entity's process. {citation}
3. **Extract ending balances:** Place each account's ending debit or credit in the corresponding trial-balance column. {citation}
4. **Total both columns:** Calculate total debits and credits and confirm that they agree. {citation}
5. **Investigate differences:** Check omitted accounts, one-sided entries, transpositions, incorrect signs, and posting errors; agreement alone does not prove every entry is correct. {citation}
6. **Post supported adjustments:** Record approved accruals, deferrals, depreciation, corrections, and other period-end adjustments. {citation}
7. **Prepare the adjusted trial balance:** Re-extract balances, confirm equal totals, and use the reviewed version for financial-statement preparation. {citation}
8. **Retain review evidence:** Document sign-off, adjustments, unresolved items, and the final version used for reporting. {citation}"""
    if re.search(r"compare|difference|table", query, re.I):
        decision_flow = f"""

### Recognition decision flow

1. **Identify the event:** Determine whether revenue was earned or an expense was incurred in the reporting period. {citation}
2. **For accrual accounting:** Recognize the economic activity in that period when the applicable framework requirements are met, using receivables, payables, accruals, or prepayments when cash timing differs. {citation}
3. **For cash-basis accounting:** Recognize the receipt or payment generally when cash moves, subject to applicable requirements. {citation}""" if re.search(r"decision\s+flow|flow", query, re.I) else ""
        return f"""## Cash basis and accrual basis compared

| Feature | Cash basis | Accrual basis |
|---|---|---|
| Revenue timing | Generally when cash is received {citation} | When earned, subject to the reporting framework {citation} |
| Expense timing | Generally when cash is paid {citation} | When incurred, subject to the reporting framework {citation} |
| Primary focus | Cash movement {citation} | Economic activity in the relevant period {citation} |
| Process complexity | Simpler {citation} | Requires estimates, adjustments, and stronger period-end processes {citation} |
| Financial picture | Timing may distort comparisons between periods {citation} | Usually provides a more complete view of performance and position {citation} |

The method an entity may or must use depends on the applicable financial-reporting, tax, and legal requirements. {citation}{decision_flow}"""
    return f"""## Accrual accounting

Accrual accounting recognizes revenue when it is earned and expenses when they are incurred, subject to the applicable reporting framework, instead of waiting for cash to move. {citation}

### Why it is used

It connects economic activity to the period in which it belongs and usually provides a more complete view of financial performance and position. Receivables, payables, accruals, and prepayments bridge the timing difference between recognition and cash settlement. {citation}

### How it works in practice

For a credit sale, revenue and a receivable are generally recognized when the applicable recognition requirements are met. Collecting the cash later reduces the receivable and increases cash; it does not create the revenue again. Accrual accounting therefore requires period-end adjustments, estimates, and stronger accounting processes than a simple cash basis. {citation}"""
