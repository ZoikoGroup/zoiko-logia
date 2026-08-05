"""Reviewed US business-tax filing guidance grounded in current IRS sources."""
from __future__ import annotations

import re


BUSINESS_TAX_REVIEW_GOVERNED_SOURCE_ID = "src-irs-business-tax-review-2026"
BUSINESS_TAX_REVIEW_NODE_PREFIX = "business-tax-review-"
BUSINESS_TAX_REVIEW_VERSION = "2026.07.29"

_WORKFLOW_TEXT = """IRS Business Filing and Employment Tax Review — reviewed 2026-07-29.

Federal income-tax and employment-tax reviews are separate workstreams. The
entity's federal income-tax return depends on its classification and filing
position; common business returns include Form 1120 for a C corporation, Form
1120-S for an S corporation, and Form 1065 for a partnership. The review begins
by confirming entity classification, tax year, elections, jurisdictions, and
the correct return and schedules. The final trial balance is reconciled to the
return, book-to-tax adjustments and taxable income are supported, payments and
credits are reconciled, disclosures and state/local obligations are considered,
and an authorized person approves filing and payment.

Employment-tax review is separate. Applicable forms may include Forms 940, 941,
943, 944, and 945. Payroll registers, Forms W-2/W-3 and information returns are
reconciled to the general ledger, tax deposits, and filed returns. Current Form
W-4 data should be reviewed using the applicable form steps and current IRS
withholding methods; the redesigned Form W-4 does not generally use the old
withholding-allowance model. Filing acknowledgements and supporting records are
retained. Employment-tax records generally must be retained for at least four
years, subject to the applicable record and issue.

Current official references reviewed: IRS Filing (businesses and self-employed),
IRS Business Tax Account and tax-form listings, IRS Recordkeeping, IRS E-file for
business and self-employed taxpayers, IRS E-file Employment Tax Forms, IRS
Depositing and Reporting Employment Taxes, and IRS Publication 15 (2026).
"""

_INTAKE_TEXT = """US company-specific tax-treatment intake — reviewed 2026-07-29.

Before addressing a company-specific tax-treatment question, identify the
country and subnational jurisdictions, entity legal and federal tax
classification, tax type, tax year or transaction date, and whether the question
concerns federal, state, local, or international rules. Obtain the complete
transaction facts, relevant contracts, amounts, dates, counterparties,
ownership/residency, business purpose, accounting treatment, prior elections or
positions, filing status, notices, and the precise decision the user needs.
Company name is not inherently required unless needed to retrieve public filings
or identify entity-specific facts. Do not request unnecessary personal or secret
data. Current primary authority and its effective date must be checked before a
company-specific conclusion; material, ambiguous, or advice-shaped matters
require a qualified tax professional.
"""


def to_business_tax_review_rag_chunk(query: str) -> dict:
    text = _INTAKE_TEXT if re.search(r"information.*(?:need|required)|jurisdiction details|company-specific tax", query, re.I) else _WORKFLOW_TEXT
    return {
        "text": text,
        "metadata": {
            "source_id": BUSINESS_TAX_REVIEW_GOVERNED_SOURCE_ID,
            "title": "IRS Business Filing & Employment Tax Review — Reviewed 2026",
            "version": BUSINESS_TAX_REVIEW_VERSION,
            "jurisdiction": "US",
            "file_path": "https://www.irs.gov/filing",
        },
        "score": 1.0,
        "node_id": f"{BUSINESS_TAX_REVIEW_NODE_PREFIX}{BUSINESS_TAX_REVIEW_VERSION}",
    }


def compose_business_tax_review(query: str, ref: str) -> str:
    citation = f"[{ref}]"
    if re.search(r"information.*(?:need|required)|jurisdiction details|company-specific tax", query, re.I):
        return f"""## Information needed for a company-specific tax question

Provide only the information relevant to the issue:

1. **Jurisdiction:** Country plus applicable state, province, locality, and any international jurisdictions. {citation}
2. **Entity and tax classification:** Legal entity type and federal/state tax classification, including relevant elections. {citation}
3. **Tax and period:** Income, payroll, sales/use, VAT/GST, withholding, property or other tax; tax year and transaction date. {citation}
4. **Complete facts:** Transaction steps, contracts, amounts, dates, counterparties, ownership/residency, business purpose and current accounting treatment. {citation}
5. **Existing position:** Prior returns, elections, notices, rulings or advice that may affect consistency. {citation}
6. **Question to decide:** The exact treatment, filing, calculation or disclosure that needs analysis. {citation}

Company name is needed only when public or entity-specific records must be retrieved. Do not provide unnecessary personal data, passwords, tax-account credentials or other secrets. Kriton must verify current primary authority and effective dates before addressing a company-specific conclusion; material or advice-shaped matters require a qualified tax professional. {citation}"""

    return f"""## US business tax return pre-filing review

### A. Scope and income-tax return
1. Confirm the entity's legal and federal tax classification, tax year, jurisdictions, elections, filing deadlines and correct return—for example Form 1120, 1120-S or 1065, as applicable. {citation}
2. Freeze the final tax trial balance and reconcile it to the financial statements and return. {citation}
3. Reconcile book income to taxable income; support permanent and temporary differences, depreciation, credits, loss/carryforward usage and other return positions. {citation}
4. Review required schedules, ownership and related-party reporting, state/local filings, estimated payments, extensions and amounts due. {citation}
5. Perform mathematical, diagnostic and prior-year consistency checks; investigate every material exception. {citation}
6. Obtain authorized review and signature/e-file authorization, transmit using an approved method, confirm acceptance and retain the filed return and support. {citation}

### B. Separate employment-tax review
1. Determine which employment returns apply, such as Forms 940, 941, 943, 944 or 945; these are not the entity's general income-tax return. {citation}
2. Reconcile payroll registers and the general ledger to taxable wages, withholding, employer taxes, deposits, Forms W-2/W-3, information returns and employment-tax returns. {citation}
3. Review current Forms W-4 using the applicable form steps and current IRS withholding methods; do not use the obsolete general "allowances claimed" checklist for redesigned forms. {citation}
4. Verify deposit and filing timeliness, corrections, credits, e-file authorization and acceptance. {citation}
5. Retain employment-tax records for the applicable period; IRS guidance generally requires at least four years. {citation}

This is a control workflow, not a conclusion about a particular return. Verify the applicable form instructions, tax-year rules, state/local requirements and developments issued after the reviewed sources. {citation}"""
