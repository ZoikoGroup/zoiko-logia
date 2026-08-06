"""Deterministic answers for reviewed Kriton educational procedures.

These answers intentionally trade stylistic variation for accounting
consistency. Every statement maps to the corresponding reviewed source chunk.
"""
from __future__ import annotations

import re


def _identifier(query: str, pattern: str, fallback: str) -> str:
    match = re.search(pattern, query, re.I)
    return match.group(1).upper() if match else fallback


def _evidence_graph_answer(query: str, ref: str) -> str:
    """Build an edge table from identifiers in this request, never from a
    previous demo. Generic labels are used only when the user names a record
    type without an identifier."""
    sales = bool(re.search(r"sales invoice|customer order|delivery note|customer contract|bank receipt", query, re.I))
    invoice = _identifier(query, r"(?:sales\s+)?invoice\s+([A-Z]{1,8}-\d+)", "Sales invoice" if sales else "Supplier invoice")
    ledger = _identifier(query, r"(?:ledger entry|general-ledger entry)\s+([A-Z]{1,8}-\d+)", "General-ledger entry")
    if sales:
        order = _identifier(query, r"customer order\s+([A-Z]{1,8}-\d+)", "Customer order")
        delivery = _identifier(query, r"delivery note\s+([A-Z]{1,8}-\d+)", "Delivery note")
        contract = _identifier(query, r"(?:customer )?contract\s+([A-Z]{1,8}-\d+)", "Customer contract")
        bank = _identifier(query, r"bank receipt\s+([A-Z]{1,8}-\d+)", "Bank receipt")
        rows = [
            (invoice, "invoice", "supported_by", order, "purchase_order"),
            (invoice, "invoice", "supported_by", delivery, "receipt"),
            (invoice, "invoice", "supported_by", contract, "contract"),
            (invoice, "invoice", "supported_by", bank, "bank_transaction"),
            (invoice, "invoice", "recorded_as", ledger, "ledger_entry"),
        ]
        title = "Sales-invoice evidence relationships"
    else:
        supplier_match = re.search(r"supplier\s+(.+?)(?=,\s*(?:purchase|invoice|goods|receipt|approval|payment|ledger)|\s+and\s+(?:purchase|invoice|goods|receipt|approval|payment|ledger)|[.]?$)", query, re.I)
        supplier = supplier_match.group(1).strip() if supplier_match else "Supplier"
        order = _identifier(query, r"purchase order\s+([A-Z]{1,8}-\d+)", "Purchase order")
        receipt = _identifier(query, r"(?:goods receipt|receipt)\s+([A-Z]{1,8}-\d+)", "Goods receipt")
        payment = _identifier(query, r"payment\s+([A-Z]{1,8}-\d+)", "Payment")
        approval_match = re.search(r"approval\s+([A-Z]{1,8}-\d+)", query, re.I)
        rows = [
            (invoice, "invoice", "issued_by", supplier, "supplier"),
            (invoice, "invoice", "references", order, "purchase_order"),
            (invoice, "invoice", "matched_to", receipt, "receipt"),
        ]
        if approval_match:
            rows.append((invoice, "invoice", "approved_by", approval_match.group(1).upper(), "approval"))
        rows.extend([
            (invoice, "invoice", "paid_by", payment, "payment"),
            (invoice, "invoice", "recorded_as", ledger, "ledger_entry"),
        ])
        title = "Supplier-invoice evidence relationships"
    lines = [
        f"## {title}", "",
        f"These relationships are constructed from the record names supplied in this request; they do not confirm authenticity or matching. [{ref}]", "",
        "| Source | Source Type | Relationship | Target | Target Type | Reference |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(f"| {source} | {source_type} | {relationship} | {target} | {target_type} | {ref} |" for source, source_type, relationship, target, target_type in rows)
    return "\n".join(lines)


def compose_bank_reconciliation(query: str, ref: str) -> str:
    q = query.lower()
    citation = f"[{ref}]"
    if re.search(r"swimlane|preparer.*reviewer.*approver", q, re.I):
        return f"""## Bank-reconciliation responsibility swimlane

| Stage | Preparer | Reviewer | Approver |
|---|---|---|---|
| Obtain records | Obtain the bank statement, ledger, and prior reconciliation for the same period. {citation} | Confirm the records and period are complete. {citation} | — |
| Reconcile | Match activity, identify timing differences and bank-only items, and investigate errors. {citation} | Challenge unusual, old, unsupported, or unreconciled items. {citation} | — |
| Correct | Prepare supported book-side entries; do not repost timing differences already in the ledger. {citation} | Verify the accounting treatment, evidence, and adjusted balances. {citation} | Approve material or exceptional corrections under the entity's authority policy. {citation} |
| Conclude | Confirm adjusted bank and book balances agree and assemble the evidence. {citation} | Sign off only when differences and exceptions are resolved or documented. {citation} | Approve the completed reconciliation and any formally accepted open items. {citation} |
| Retain and monitor | Retain the reconciliation and support. {citation} | Track recurring or overdue exceptions. {citation} | Escalate control failures or significant unresolved differences. {citation} |

Segregate preparation, review, approval, and payment authority wherever practical; exact role assignments depend on the entity's control design. {citation}"""
    if "journal entr" in q and ("which" in q or "require" in q or "deposit" in q):
        return f"""## Bank-reconciliation journal entries

1. **Identify the difference:** Match it to the bank statement, ledger, and supporting evidence. {citation}
2. **Is it already recorded correctly in the books?** If yes and it is a deposit in transit or outstanding check, it **does not require another journal entry**; treat it as a timing difference and ensure it is **not recorded a second time**. {citation}
3. **Is it unrecorded bank activity?** Bank fees, interest, automatic payments, returned items, and direct bank credits or debits require a supported book-side entry when absent from the ledger. {citation}
4. **Is it a bookkeeping error?** Correct supported omissions, duplicates, transpositions, or incorrect amounts in the books. {citation}
5. **Verify the result:** After required entries, confirm that adjusted bank and adjusted book balances agree; investigate any remaining difference. {citation}"""

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
    if re.search(r"preparer.*reviewer|controls?\s+by\s+role|supporting evidence|escalation conditions", query, re.I):
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
    if re.search(r"timeline|schedule", query, re.I):
        return f"""## Illustrative month-end financial close timeline

| Timing | Primary activity | Typical owner/control |
|---|---|---|
| **D−5 to D−1** | Confirm the close calendar, cut-off instructions, responsibilities, recurring entries, and expected submissions. {citation} | Controller coordinates; owners acknowledge deadlines. |
| **Day 0** | Apply transaction cut-off to revenue, purchases, payroll, cash, and other significant cycles. {citation} | Process owners complete and evidence cut-off. |
| **D+1 to D+2** | Complete transaction entry and reconcile bank, receivables, payables, inventory, fixed assets, payroll, and intercompany accounts. {citation} | Preparers reconcile; reviewers challenge exceptions. |
| **D+2 to D+3** | Post supported accruals, prepayments, depreciation, allocations, and approved corrections. {citation} | Entry preparation and approval remain segregated. |
| **D+3 to D+4** | Resolve unusual, missing, duplicate, late, or unreconciled items; prepare the trial balance and draft statements. {citation} | Controller tracks open items and materiality. |
| **D+4 to D+5** | Perform analytical and management review against budgets, prior periods, and expected activity. {citation} | Reviewers document questions and resolutions. |
| **D+5** | Approve and issue the reporting package, restrict later postings, and track approved post-close adjustments separately. {citation} | Authorized management gives final approval. |

This is an illustrative five-business-day close. The entity should adjust dates and ownership for its systems, volume, reporting deadlines, materiality, and control design. {citation}"""
    title = "## Month-end financial close checklist"
    return f"""{title}

1. **Pre-close — plan:** Establish the calendar, cut-off date, responsibilities, and required approvals. {citation}
2. **At cut-off — complete transaction entry:** Apply cut-off procedures to revenue, purchases, payroll, cash, and other significant cycles. {citation}
3. **After transaction entry — reconcile:** Cover bank, receivables, payables, inventory, fixed assets, payroll, intercompany, and other material balance-sheet accounts. {citation}
4. **During reconciliation — prepare supported entries:** Record accruals, prepayments, depreciation, allocations, and approved corrections. {citation}
5. **Before reporting review — resolve exceptions:** Investigate reconciliation differences and unusual, missing, duplicate, or late transactions. {citation}
6. **Draft-reporting stage — review results:** Produce the trial balance and draft statements, then compare results with budgets, prior periods, and expected activity. {citation}
7. **Approval stage — approve the close:** Complete management review, document open items, and obtain required approvals. {citation}
8. **Final stage — issue and control the period:** Release the approved reporting package, restrict later postings, and track approved post-close adjustments separately. {citation}

Exact timing and ownership depend on the entity's systems, transaction volume, reporting framework, materiality, and control design. {citation}"""


def compose_audit_variance_decision(query: str, ref: str) -> str | None:
    if not re.search(r"(?:account\s+)?variance|unexplained difference|balance that looks unusual|unexpected (?:account )?movement", query, re.I) or not re.search(r"audit|additional testing|more testing|investigat|unusual|unexpected|unexplained|reviewer|visuali[sz]e", query, re.I):
        return None
    citation = f"[{ref}]"
    return f"""## Audit decision flow for an unexplained account variance

1. **Validate the variance:** Confirm the source data, period, account, calculation, and expectation used to identify the difference. If the variance is not valid, correct the analysis and document why. {citation}
2. **Assess significance and risk:** Evaluate the amount and qualitative factors, including possible fraud, control, or disclosure implications. Do not dismiss a variance only because it is below a quantitative threshold. {citation}
3. **Obtain and test the explanation:** Determine whether management's explanation is plausible and supported by relevant, reliable evidence. {citation}
4. **Check for contradictory or control evidence:** Consider inconsistent information, repeated exceptions, control failures, and effects on related accounts or assertions. {citation}
5. **Evaluate evidence sufficiency:** If the explanation is supported and the evidence is sufficient for the assessed risk, document the conclusion. {citation}
6. **Perform additional procedures or escalate:** If the matter remains unexplained, unsupported, contradictory, qualitatively significant, or insufficiently evidenced, design additional procedures or escalate before concluding. {citation}

The nature, timing, and extent of additional testing depend on the relevant assertion, assessed risk, materiality, available evidence, and professional judgment. {citation}"""


def compose_accounting_fundamentals(query: str, ref: str) -> str | None:
    """Returns None when the query doesn't match any of the specifically
    reviewed topics below — the caller (orchestration/service.py) must
    treat None as "fall through to a genuine LLM composition," never as
    "answer with whatever branch happens to be last.\""""
    citation = f"[{ref}]"
    if re.search(r"(?:intellectual\s+propert|intelectual\s+properit)", query, re.I):
        return f"""## Intellectual property

Intellectual property is a broad term for legally protected creations and commercially valuable intangible knowledge. Common categories include: {citation}

- **Patents:** protection for qualifying inventions.
- **Trademarks:** signs that identify the source of goods or services.
- **Copyright:** protection for qualifying original expression.
- **Trade secrets:** valuable confidential information protected through secrecy controls.

The applicable protection, registration, ownership, duration, and enforcement rules depend on the category and jurisdiction. {citation}"""
    if re.search(r"\brevenue\b.*\bprofit\b|\bprofit\b.*\brevenue\b", query, re.I) and not re.search(r"\bcalculate|margin|chart|graph\b", query, re.I):
        return f"""## Revenue and profit compared

| Item | Revenue | Profit |
|---|---|---|
| Meaning | Consideration recognized from ordinary activities | Residual after relevant expenses are deducted from revenue |
| Relationship to cash | Is not necessarily cash collected | Is not the same as cash flow |

Gross, operating, and net profit include different expense layers. A business can have high revenue but low or negative profit when its costs are high. {citation}"""
    if re.search(r"accounts?[\s-]+payable.*accounts?[\s-]+receivable|accounts?[\s-]+receivable.*accounts?[\s-]+payable", query, re.I):
        return f"""## Accounts payable and accounts receivable

| Feature | Accounts payable | Accounts receivable |
|---|---|---|
| Meaning | Amounts owed to suppliers for credit purchases | Amounts customers owe for credit sales |
| Usual classification | Liability | Asset |
| Settlement | The entity pays the supplier | The entity collects from the customer |
| Core control | Validate, approve, pay, and reconcile supplier balances | Bill, collect, apply cash, and reconcile customer balances |

Both should be reconciled to their subsidiary ledgers, general-ledger control accounts, and supporting documents. {citation}"""
    if re.search(r"balance\s+sheet.*income\s+statement|income\s+statement.*balance\s+sheet", query, re.I):
        return f"""## Balance sheet and income statement

| Feature | Balance sheet | Income statement |
|---|---|---|
| Time basis | At a reporting date | Over a reporting period |
| Main elements | Assets, liabilities, and equity | Revenue, expenses, and profit or loss |
| Purpose | Shows financial position | Shows financial performance |

The statements are linked because period profit or loss affects equity, subject to distributions and other equity movements. {citation}"""
    if re.search(r"\bmateriality\b", query, re.I) and not re.search(r"\bcalculate|compute|benchmark|percentage\b", query, re.I):
        return f"""## Audit materiality

Materiality is the principle that an omission, misstatement, or obscuring of information matters when it could reasonably influence users' decisions. It depends on both the amount and nature of the matter in its circumstances. {citation}

Auditors use materiality when planning procedures, evaluating identified misstatements, and forming conclusions. Selecting a benchmark and percentage requires professional judgment; materiality is not defined by one universal fixed percentage. {citation}"""
    if re.search(r"cash\s+flow.*positive.*loss|loss.*positive\s+cash\s+flow", query, re.I):
        return f"""## Why positive cash flow can accompany a loss

Accounting profit and cash flow measure different things. A company can report a loss while generating positive operating cash flow when: {citation}

1. **Non-cash expenses** such as depreciation reduce profit without a current cash payment. {citation}
2. **Receivables are collected**, releasing cash previously tied up in working capital. {citation}
3. **Payables or accrued liabilities increase**, delaying cash payment relative to expense recognition. {citation}
4. **Other timing differences** cause cash receipts and accounting recognition to occur in different periods. {citation}

A cash balance at one date does not prove that cash flow during the period was positive; the cash-flow statement must be examined. {citation}"""
    if re.search(r"internal\s+audit.*external\s+audit|external\s+audit.*internal\s+audit", query, re.I):
        return f"""## Internal and external audit compared

| Feature | Internal audit | External financial-statement audit |
|---|---|---|
| Primary purpose | Assurance and advice on governance, risk, and controls | Independent opinion on financial statements |
| Position | Within governance; may be in-house or outsourced | Independent of the entity |
| Scope | Risk-based and potentially operational, compliance, technology, and financial | Defined by the applicable auditing framework |
| Reporting | Usually to the board or audit committee and management | To shareholders or other intended users as required |

Internal audit independence is supported through organizational status and direct access to those charged with governance; it is not accurate to define all internal auditors simply as ordinary employees. {citation}"""
    if re.search(r"supplier invoice.*(?:sequence|moves? from|document upload)", query, re.I):
        return f"""## Supplier-invoice processing sequence

1. **Document intake receives the invoice from the supplier:** Capture the file, supplier identity, invoice number, date, amount, and attachment reference. {citation}
2. **Validation service sends validated invoice data to the duplicate checker:** Confirm required fields, supplier status, arithmetic, and readable supporting documents. {citation}
3. **Duplicate checker sends a unique invoice to accounts payable:** Compare supplier, invoice number, amount, date, purchase order, and prior postings or payments; route suspected duplicates to an exception queue. {citation}
4. **Accounts payable sends matched evidence to the approver:** Match the invoice to the purchase order and receipt where applicable, resolve exceptions, and confirm coding. {citation}
5. **Approver sends an authorized invoice to the ledger:** Apply the entity's approval limits and segregation-of-duties controls before posting the payable and expense or asset entry. {citation}
6. **Ledger sends the due payable to the payment process:** Select approved due items, apply payment controls, release the payment, and record settlement. {citation}
7. **Payment process sends the completed record to audit logging:** Retain the invoice, matching evidence, approvals, journal identifiers, payment reference, exceptions, timestamps, and responsible users. {citation}"""
    if re.search(r"customer order.*(?:sequence|moves? through|credit approval)", query, re.I):
        return f"""## Customer order-to-cash sequence

1. **Sales intake sends the customer order to credit control:** Validate the customer, terms, prices, quantities, and order authorization. {citation}
2. **Credit control sends an approved order to fulfilment:** Apply the entity's credit policy and route exceptions for authorization. {citation}
3. **Fulfilment sends delivery evidence to billing:** Record shipment or service completion and retain customer acceptance where relevant. {citation}
4. **Billing sends the invoice to the customer and ledger:** Link the invoice to the order and fulfilment evidence, then apply the applicable revenue-recognition requirements. {citation}
5. **Ledger sends the open receivable to collections:** Record revenue and the receivable only when the recognition criteria are met. {citation}
6. **Customer sends payment information to cash application:** Match the bank receipt and remittance to the correct invoice and investigate differences. {citation}
7. **Cash application sends reconciled records to review:** Reconcile customer, receivables, ledger, and bank records and retain the exception and approval trail. {citation}"""
    if re.search(r"employee expense claim.*(?:sequence|moves? from|submission)", query, re.I):
        return f"""## Employee expense-claim sequence

1. **Employee sends the claim and receipts to validation:** Provide the business purpose, date, amount, currency, category, and required evidence. {citation}
2. **Validation sends a complete claim to the manager:** Check arithmetic, duplicates, policy limits, required fields, and readable support. {citation}
3. **Manager sends an approved claim to accounting:** Confirm business purpose, reasonableness, budget ownership, and any policy exceptions. {citation}
4. **Accounting sends a coded claim to reimbursement:** Verify account and tax coding, approval authority, segregation of duties, and payable treatment. {citation}
5. **Reimbursement sends payment details to the ledger:** Release the authorized payment and record settlement against the employee payable. {citation}
6. **Ledger sends the completed claim to audit logging:** Retain the claim, receipts, validation, approvals, coding, payment reference, exceptions, timestamps, and users. {citation}"""
    if re.search(r"audit exception.*(?:sequence|moves? from|identification)", query, re.I):
        return f"""## Audit-exception resolution sequence

1. **Auditor sends the identified exception to risk assessment:** Document the criterion, condition, affected assertion, population, amount, and initial evidence. {citation}
2. **Risk assessment sends the scoped exception to evidence collection:** Consider quantitative and qualitative significance, control implications, and possible fraud indicators. {citation}
3. **Auditor sends the evidence request to management:** Obtain relevant records and a clear explanation while preserving contradictory information. {citation}
4. **Management sends its response and support to the auditor:** Identify proposed correction or remediation and the responsible owner. {citation}
5. **Auditor sends the evaluated exception to the reviewer:** Assess relevance, reliability, sufficiency, contradictions, and whether further procedures are required. {citation}
6. **Reviewer sends unresolved or significant matters to escalation:** Route the matter under the engagement's consultation and governance requirements. {citation}
7. **Authorized reviewer sends the final conclusion to audit documentation:** Record resolution, corrections, remaining effects, approvals, and follow-up actions. {citation}"""
    if re.search(r"evidence (?:relationship )?graph|evidence graph|sales invoice.*supported by", query, re.I):
        return _evidence_graph_answer(query, ref)
    if re.search(r"(?:sequence\s+diagram.*tax.*jurisdiction.neutral|tax.*(?:sequence|process).*(?:jurisdiction.neutral|collects? transaction data)|jurisdiction.neutral.*tax)", query, re.I):
        indirect = bool(re.search(r"indirect[\s-]*tax", query, re.I))
        if indirect:
            return f"""## Jurisdiction-neutral indirect-tax compliance sequence

1. **Transaction system sends transaction attributes to classification:** Capture location, parties, goods or services, consideration, invoice status, and other relevant facts. {citation}
2. **Classification sends the governed tax category to calculation:** Apply the current rules for the relevant jurisdiction and tax type; route uncertain classifications for review. {citation}
3. **Tax calculation sends the result to invoice validation:** Check tax base, rate, exemption or reverse-charge evidence, currency, rounding, and required invoice fields. {citation}
4. **Invoice validation sends reconciled tax data to return preparation:** Reconcile tax records to sales, purchases, ledger accounts, corrections, and prior-period carryovers. {citation}
5. **Return preparer sends the supported draft to internal approval:** Review completeness, calculations, exceptions, payment position, and filing period. {citation}
6. **Authorized filer sends the approved return to the relevant authority:** Retain submission confirmation and separately control the related payment. {citation}
7. **Payment process sends settlement evidence to records retention:** Reconcile the payment and preserve the return, calculations, invoices, approvals, correspondence, and filing evidence. {citation}

The specific classification rules, invoice requirements, rates, forms, deadlines, payment mechanics, and retention periods depend on the jurisdiction. {citation}"""
        return f"""## Jurisdiction-neutral business tax compliance sequence

1. **Business systems send transaction data to the tax data preparation team:** Reconcile relevant ledgers and preserve source-document links. {citation}
2. **Tax data preparation team sends reconciled data to the tax calculation process:** Apply the applicable jurisdiction's current tax rules and document adjustments and assumptions. {citation}
3. **Tax calculation process sends the draft return to the preparer:** Populate the return and connect material amounts to schedules and supporting evidence. {citation}
4. **Preparer sends the supported draft to the internal reviewer:** Check completeness, consistency, calculations, filing period, authorization, and unresolved exceptions. {citation}
5. **Internal reviewer sends the approved return to the authorized filer:** Approval is an internal governance step; it does not imply acceptance by a tax authority. {citation}
6. **Authorized filer sends the return to the relevant tax authority:** Use the applicable filing method, retain submission evidence, and separately track payment obligations and deadlines. {citation}
7. **Filing process sends the final package to records retention:** Preserve the filed return, calculations, source records, approvals, correspondence, payment evidence, and submission confirmation for the required retention period. {citation}

Specific calculations, forms, deadlines, and retention periods depend on the jurisdiction and tax type. {citation}"""
    if re.search(r"unmatched supplier invoice", query, re.I):
        return f"""## Unmatched supplier-invoice resolution workflow

1. **Quarantine the exception:** Prevent payment until the invoice is matched or an authorized exception is documented. {citation}
2. **Validate the invoice:** Confirm supplier, invoice number, date, amount, currency, arithmetic, duplicate status, and required support. {citation}
3. **Search for purchasing evidence:** Locate the purchase order, contract, receipt, service confirmation, and responsible requester. {citation}
4. **Investigate the mismatch:** Resolve quantity, price, tax, coding, timing, missing-receipt, or unauthorized-purchase differences. {citation}
5. **Choose the disposition:** Match and approve a valid obligation, obtain an authorized exception, reject the invoice, or request a corrected invoice or credit note. {citation}
6. **Obtain independent review:** Verify evidence, coding, approval authority, duplicate controls, and proposed accounting before release. {citation}
7. **Post, reconcile, and retain:** Update payables and ledger records, release only an approved payment, and preserve the resolution and audit trail. {citation}"""
    if re.search(r"retained\s+earnings", query, re.I):
        return f"""## Retained earnings

Retained earnings is the cumulative profit a company has kept in the business instead of distributing it to owners. It is presented within equity; it is not a separate cash account. {citation}

**Ending retained earnings = Beginning retained earnings + Net income − Dividends** {citation}

If beginning retained earnings is **$100,000**, net income is **$50,000**, and dividends are **$20,000**, ending retained earnings is **$130,000**: $100,000 + $50,000 − $20,000. A net loss reduces retained earnings, and applicable prior-period adjustments may affect the opening balance. {citation}"""
    if re.search(r"recorded\s+as\s+revenue\s+again|correcting\s+journal\s+entry", query, re.I):
        amount = re.search(r"\$\s*([\d,]+(?:\.\d{1,2})?)", query)
        display = f"${amount.group(1)}" if amount else "the duplicated amount"
        return f"""## Duplicate revenue correction

The cash receipt was credited to revenue instead of reducing the existing customer receivable. This records revenue twice and leaves accounts receivable overstated. {citation}

| Account | Debit | Credit |
|---|---:|---:|
| Revenue | {display} | — |
| Accounts receivable | — | {display} |

This correcting entry removes the duplicated revenue and clears the receivable. Before posting it, verify that the original invoice was recorded as **Dr Accounts receivable / Cr Revenue** and the incorrect receipt as **Dr Cash / Cr Revenue**. {citation}"""
    if re.search(r"scoring\s+matrix.*audit[\s-]+evidence|audit[\s-]+evidence.*scoring\s+matrix", query, re.I):
        return f"""## Audit-evidence reliability and sufficiency matrix

Score each factor from **1 (weak)** to **3 (strong)**. {citation}

| Factor | 1 — Weak | 2 — Moderate | 3 — Strong |
|---|---|---|---|
| Relevance | Indirectly related | Partly addresses the assertion | Directly addresses the assertion |
| Source | Management-created without tested controls | Internal evidence with tested controls | Independent external evidence obtained directly |
| Authenticity and accuracy | Unverified or altered | Partly verified | Authenticated and recalculated/validated |
| Consistency | Contradicted by other evidence | Minor unresolved differences | Consistent with corroborating evidence |
| Coverage | Small or biased coverage | Reasonable but incomplete coverage | Appropriate coverage for the assessed risk |

**Interpretation:** 13–15 may support a conclusion; 9–12 normally requires targeted corroboration; 5–8 normally requires additional procedures. A suspected alteration, unresolved contradiction, or failure to address the relevant assertion is a **critical override**—do not rely on the total score; extend testing or escalate. The matrix supports, but never replaces, professional judgment about relevance, reliability and sufficiency. {citation}"""
    if re.search(r"compare.*audit[\s-]+evidence.*internal.*external|audit[\s-]+evidence.*internal.*external", query, re.I):
        return f"""## Internal and external audit evidence comparison

| Factor | Internal evidence | External evidence |
|---|---|---|
| Source independence | Prepared within the entity; independence is lower. | Originates outside the entity and is generally more independent. |
| Reliability | Depends strongly on relevant controls and preparation processes. | Often more reliable when obtained directly by the auditor from a knowledgeable external source. |
| Relevance | Can be highly relevant when it directly addresses the assertion. | Must still address the assertion; external origin alone does not make evidence relevant. |
| Authenticity and accuracy | Test source data, calculations, completeness and applicable controls. | Authenticate the response, maintain control over confirmation, and resolve exceptions. |
| Corroboration and coverage | Compare with independent records and other evidence, especially where controls are weak. | Add other procedures when scope, response quality or coverage is incomplete. |

Neither source type is automatically sufficient. Evaluate relevance, reliability, consistency and coverage together, and extend procedures when evidence is contradictory or insufficient. {citation}"""
    if re.search(r"(?:accounts?\s+receivable|receivables).*(?:increased|increase|grew|grown|growth).*(?:revenue|sales)", query, re.I):
        comparison = (
            "A 35% increase in receivables compared with 8% revenue growth"
            if re.search(r"35\s*%.*8\s*%", query)
            else "Receivables growing materially faster than revenue"
        )
        return f"""## Accounts-receivable movement: causes and audit response

{comparison} may indicate slower collection, but the trend alone does not establish an error. {citation}

### Possible causes
- Extended credit terms, customer disputes, collection delays, or concentration in recent-period sales. {citation}
- Unapplied cash, delayed write-offs, or an understated expected-credit-loss/allowance estimate. {citation}
- Cut-off errors, premature or fictitious revenue, credit notes recorded late, or other manual-entry errors. {citation}

### Recommended procedures
1. Reconcile the receivables subledger to the general ledger and reproduce the trend, aging, and days-sales-outstanding analysis. {citation}
2. Segment the movement by customer, age, product, location, and period to identify where the increase arose. {citation}
3. Test subsequent cash receipts and confirm selected balances, emphasizing large, old, unusual, disputed, and related-party items. {citation}
4. Test sales cut-off around period end and inspect contracts, invoices, delivery evidence, returns, and post-period credit notes. {citation}
5. Evaluate the allowance using aging, payment history, disputes, subsequent receipts, and current customer information. {citation}
6. Test manual revenue and receivable journal entries and investigate contradictory explanations or control exceptions. {citation}

The nature and extent of testing should reflect materiality, relevant assertions, assessed fraud risk, controls, and evidence obtained. {citation}"""
    if re.search(r"inventory.*(?:increased|increase|grew|growth).*(?:revenue|sales)|(?:revenue|sales).*(?:inventory).*(?:increased|increase|grew|growth)", query, re.I):
        return f"""## Inventory movement: causes and audit response

Inventory growing substantially faster than sales is a risk indicator, not proof of misstatement. It may reflect planned stocking, purchasing or production changes, price inflation, slower demand, obsolete stock, cut-off errors, costing errors, or overstated quantities. {citation}

### Recommended procedures
1. Reconcile the inventory subledger to the general ledger and reproduce the trend by product, location, age, and quantity versus price. {citation}
2. Compare turnover and days-in-inventory with prior periods, budgets, sales trends, and credible operational explanations. {citation}
3. Observe the physical count where applicable, perform test counts, and investigate book-to-floor and floor-to-book differences. {citation}
4. Test purchase, production, transfer, and sales cut-off around period end using receiving and shipping evidence. {citation}
5. Test unit costs to invoices and production records; evaluate net realizable value, obsolescence, damage, and subsequent sales. {citation}
6. Review unusual manual entries, negative quantities, dormant items, control exceptions, and contradictory evidence. {citation}

Extend testing based on materiality, relevant assertions, assessed fraud risk, controls, and the evidence obtained. {citation}"""
    if re.search(r"\bwhat\s+is\s+working\s+capital\b|\bworking\s+capital.*(?:important|meaning|define)", query, re.I):
        return f"""## Working capital

**Working capital = current assets − current liabilities.** It measures the net short-term resources available after short-term obligations. {citation}

It is useful for assessing liquidity and day-to-day operating capacity, but it should be interpreted with cash-flow timing, asset quality, industry norms, seasonality, and related ratios. Positive working capital does not by itself prove that bills can be paid on time, because inventory or receivables may not convert quickly to cash. {citation}"""
    if re.search(r"supplier.*(?:paid twice|duplicate)|duplicate supplier payment", query, re.I):
        return f"""## Duplicate supplier-payment investigation

1. **Triage the alert:** Place any unreleased payment on hold and assign an investigator without changing the accounting records prematurely. {citation}
2. **Compare the two candidates:** Align supplier ID, invoice number, amount, currency, invoice date, purchase order, receipt, payment reference, and bank status. {citation}
3. **Decide whether both obligations are valid:** If they relate to different goods or services, document the distinction and continue normal approval; otherwise treat the item as a suspected duplicate. {citation}
4. **Establish the failure point:** Determine whether duplication arose during invoice capture, posting, approval, payment-file creation, or bank release. {citation}
5. **Choose the controlled response:** Cancel an unreleased duplicate, or obtain authorized recovery and correcting-entry instructions for a settled payment. {citation}
6. **Obtain reviewer approval:** A reviewer checks the evidence, proposed correction, recovery status, account impact, and segregation of duties before closure. {citation}
7. **Reconcile and close:** Tie supplier, payables, ledger, cash, and bank records; retain the investigation and approval evidence; record the root cause and remediation owner. {citation}"""
    if re.search(r"money received after year.end|income.*correct reporting period|revenue.*(?:cut.?off|reporting period)", query, re.I):
        return f"""## Revenue cut-off review

Cash timing alone does not determine the correct reporting period under accrual accounting. Revenue is recorded when the applicable recognition requirements are met. {citation}

1. **Identify the transaction:** Trace the receipt to the customer, invoice, contract, order, and related ledger entry. {citation}
2. **Determine when performance occurred:** Inspect fulfilment, delivery, acceptance, or service-completion evidence for the reporting cut-off. {citation}
3. **Review relevant terms:** Consider payment, delivery, acceptance, return, cancellation, and continuing-obligation terms. {citation}
4. **Compare dates:** Compare the recognition date with invoice, shipment or service, receipt, and subsequent cash dates. {citation}
5. **Check both sides of cut-off:** Test transactions immediately before and after period end for omission, duplication, or recording in the wrong period. {citation}
6. **Conclude and correct:** Document the evidence and record an approved correction when the entry is in the wrong period. {citation}"""
    if re.search(r"obligations incurred before year.end|liabilit(?:y|ies).*completeness|all obligations.*recorded", query, re.I):
        return f"""## Liability-completeness review

1. **Reconcile supplier records:** Compare supplier statements and the payables subledger with the general ledger. {citation}
2. **Review subsequent activity:** Examine post-year-end invoices, payments, receiving records, and unmatched purchase documents for pre-year-end obligations. {citation}
3. **Apply cut-off:** Determine when goods or services were received and whether the related liability belongs before year-end. {citation}
4. **Inspect unresolved items:** Review unapproved invoices, unmatched receipts, open purchase orders, accruals, disputes, and unrecorded bank activity. {citation}
5. **Investigate exceptions:** Resolve missing, duplicate, late, or incorrectly dated postings and obtain appropriate support. {citation}
6. **Record supported adjustments:** Post approved accruals or corrections and retain preparer and reviewer evidence. {citation}"""
    if re.search(r"evidence.*(?:reliable|sufficient|support|contradict)|supporting documents contradict", query, re.I):
        return f"""## Evidence reliability and sufficiency review

1. **Link evidence to the objective:** Identify the account, assertion, risk, and conclusion the evidence is intended to support. {citation}
2. **Evaluate relevance:** Confirm that the evidence addresses the specific matter being tested. {citation}
3. **Evaluate reliability:** Consider the evidence's source, independence, authenticity, accuracy, controls over its preparation, and whether it was obtained directly or indirectly. {citation}
4. **Evaluate sufficiency:** Decide whether the quantity and quality of evidence are enough for the assessed risk; stronger risk generally requires more persuasive evidence. {citation}
5. **Resolve contradictions:** Compare the document with the ledger and other evidence, verify source data and calculations, and investigate why the records disagree. {citation}
6. **Extend or escalate when needed:** Perform additional procedures when evidence is missing, unreliable, contradictory, or insufficient, and escalate unresolved matters before concluding. {citation}
7. **Document the conclusion:** Record the procedures, evidence, exceptions, judgments, review, and final conclusion. {citation}"""
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
    if re.search(r"accounts[\s-]*payable|invoice.*approval(?:.*payment)?", query, re.I):
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
    # Real gap (2026-08-06): "What is accrued revenue?" and "Explain the
    # accounting cycle from transaction to financial statements" both
    # matched none of the ~30 branches above and fell through to the
    # unconditional "Accrual accounting" default at the end of this
    # function — a fixed, specific answer that has nothing to do with
    # either question, served confidently regardless of what was actually
    # asked. This whole function's fallback behavior (a wrong, unrelated
    # hardcoded answer rather than gracefully degrading) is a broader
    # architectural risk beyond these two queries — any other unmatched
    # accounting-fundamentals topic hits the same default — but these two
    # are the concretely reported, common cases, handled the same
    # hand-curated way every other topic in this function already is.
    if re.search(r"accrued\s+revenue", query, re.I) and not re.search(r"\bliabilit", query, re.I):
        return f"""## Accrued revenue

Accrued revenue is revenue that has been earned — the applicable recognition requirements have been met — but not yet billed or collected in cash. It is recorded as revenue and a receivable in the period it is earned, not the period cash is received. {citation}

### Why it matters

Recognizing revenue only when cash is received (a cash basis) would understate performance in the period the work was actually done and overstate it in the period payment happens to arrive. Accrued revenue keeps the income statement aligned with the economic activity of the period. {citation}

### Example without fixed amounts

A service is delivered in one period but invoiced or collected in a later period. The revenue and a corresponding receivable are recognized in the period the service was delivered; when cash is later collected, the receivable is reduced and cash increases — no additional revenue is recorded at that point. {citation}"""
    if re.search(r"accounting\s+cycle", query, re.I):
        return f"""## The accounting cycle

The accounting cycle is the recurring sequence an entity follows to turn transactions into reported financial statements each period. {citation}

1. **Identify and record transactions:** Source documents (invoices, receipts, contracts) are analyzed and recorded as journal entries. {citation}
2. **Post to the general ledger:** Journal entries are posted to the relevant ledger accounts. {citation}
3. **Prepare an unadjusted trial balance:** Ledger balances are listed to confirm total debits equal total credits before adjustments. {citation}
4. **Post adjusting entries:** Accruals, deferrals, depreciation, and other period-end adjustments are recorded so revenue and expenses are recognized in the correct period. {citation}
5. **Prepare an adjusted trial balance:** Balances are re-extracted after adjustments and re-checked for equal debits and credits. {citation}
6. **Prepare financial statements:** The income statement, balance sheet, and other statements are drawn from the adjusted trial balance. {citation}
7. **Close temporary accounts:** Revenue and expense accounts are closed to retained earnings (or equivalent), and the cycle begins again for the next period. {citation}

Equal debit and credit totals at any stage confirm arithmetic balance, not that every entry is correct — omitted accounts, one-sided entries, or misclassifications can still exist even when the trial balance ties out. {citation}"""
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
    if re.search(r"\baccrual\b|\bcash[\s-]basis\b", query, re.I):
        return f"""## Accrual accounting

Accrual accounting recognizes revenue when it is earned and expenses when they are incurred, subject to the applicable reporting framework, instead of waiting for cash to move. {citation}

### Why it is used

It connects economic activity to the period in which it belongs and usually provides a more complete view of financial performance and position. Receivables, payables, accruals, and prepayments bridge the timing difference between recognition and cash settlement. {citation}

### How it works in practice

For a credit sale, revenue and a receivable are generally recognized when the applicable recognition requirements are met. Collecting the cash later reduces the receivable and increases cash; it does not create the revenue again. Accrual accounting therefore requires period-end adjustments, estimates, and stronger accounting processes than a simple cash basis. {citation}"""
    # Real gap (2026-08-06): this used to be an UNCONDITIONAL fallback —
    # any accounting-fundamentals query matching none of the ~30 branches
    # above got this same "Accrual accounting" answer regardless of what
    # was actually asked (confirmed live: "What is accrued revenue?" and
    # "Explain the accounting cycle..." both got it before their own
    # branches were added above). Narrowed to only fire when the query
    # actually mentions accrual/cash-basis accounting, and returns None
    # otherwise so the caller (orchestration/service.py) falls through to
    # a genuine LLM composition grounded in the retrieved excerpt instead
    # of ever serving a hardcoded, potentially unrelated answer — the same
    # protection every other unmatched category already has via the
    # normal RAG+LLM path.
    return None
