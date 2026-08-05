from app.orchestration.educational_answers import (
    compose_accounting_fundamentals,
    compose_audit_variance_decision,
    compose_bank_reconciliation,
    compose_month_end_close,
)
from app.domains.reference_data.user_provided_data import (
    compose_quarterly_results,
    extract_user_data_table,
    extract_quarterly_results,
    to_user_provided_data_rag_chunk,
)
from app.domains.reference_data.accounting_fundamentals import to_accounting_fundamentals_rag_chunk


def test_bank_journal_entry_answer_never_records_timing_difference_twice():
    answer = compose_bank_reconciliation(
        "Explain deposits in transit, outstanding checks, and journal entries.", "REF-1"
    )
    assert "does not require another journal entry" in answer
    assert "not recorded a second time" in answer
    assert "Bank fees" in answer


def test_bank_checklist_is_complete_and_cited():
    answer = compose_bank_reconciliation("Give me a review checklist.", "REF-1")
    assert answer.count("[REF-1]") >= 10
    assert "10. **Document and review:**" in answer


def test_demo_sequence_and_workflow_prompts_get_on_topic_reviewed_answers():
    invoice = compose_accounting_fundamentals(
        "Create a sequence diagram showing how a supplier invoice moves from document upload through validation, duplicate checking, approval, journal posting, payment and audit logging.",
        "REF-1",
    )
    assert "Supplier-invoice processing sequence" in invoice
    assert "Duplicate checker" in invoice and "audit logging" in invoice

    variance = compose_audit_variance_decision(
        "Visualize how an unexplained account variance moves through investigation, evidence collection, reviewer challenge and final resolution.",
        "REF-1",
    )
    assert variance is not None and "Validate the variance" in variance

    duplicate = compose_accounting_fundamentals(
        "Create an editable workflow for investigating and approving a suspected duplicate supplier payment.",
        "REF-1",
    )
    assert "Obtain reviewer approval" in duplicate


def test_demo_graph_and_neutral_tax_prompts_are_grounded_and_structured():
    graph = compose_accounting_fundamentals(
        "Create an evidence relationship graph connecting invoice INV-1045, supplier ABC Ltd, purchase order PO-880, receipt GRN-225, payment PAY-990 and ledger entry JE-450.",
        "REF-1",
    )
    assert "| INV-1045 | invoice |" in graph
    assert "| Source | Source Type | Relationship | Target | Target Type |" in graph

    tax = compose_accounting_fundamentals(
        "Create a sequence diagram for a jurisdiction-neutral tax compliance process.", "REF-1",
    )
    assert "Jurisdiction-neutral business tax compliance sequence" in tax
    assert "internal governance step" in tax
    assert "auditor should" not in tax.lower()


def test_graph_identifiers_are_extracted_from_each_request():
    answer = compose_accounting_fundamentals(
        "Create an evidence graph connecting purchase order PO-410, supplier XYZ Ltd, invoice INV-820, "
        "goods receipt GRN-315, approval APR-45, payment PAY-620 and ledger entry JE-910.",
        "REF-1",
    )
    for identifier in ("PO-410", "XYZ Ltd", "INV-820", "GRN-315", "APR-45", "PAY-620", "JE-910"):
        assert identifier in answer
    assert "INV-1045" not in answer

    sales = compose_accounting_fundamentals(
        "Build an evidence graph connecting sales invoice SI-225, customer order SO-180, delivery note DN-440, "
        "customer contract CT-72, bank receipt BR-390 and ledger entry JE-775.",
        "REF-1",
    )
    for identifier in ("SI-225", "SO-180", "DN-440", "CT-72", "BR-390", "JE-775"):
        assert identifier in sales


def test_generalized_demo_workflows_use_reviewed_answers():
    cases = {
        "Create a sequence diagram showing how a customer order moves through credit approval, fulfilment, invoicing, revenue posting, cash collection and reconciliation.": "Customer order-to-cash sequence",
        "Create a sequence diagram showing how an employee expense claim moves from submission through validation, manager approval, accounting review, reimbursement and audit logging.": "Employee expense-claim sequence",
        "Create a sequence diagram showing how an audit exception moves from identification through evidence collection, management response, reviewer assessment, escalation and final resolution.": "Audit-exception resolution sequence",
        "Create an editable workflow for reviewing and resolving an unmatched supplier invoice.": "Unmatched supplier-invoice resolution workflow",
        "Create a sequence diagram for a jurisdiction-neutral indirect-tax process covering transaction classification, tax calculation, invoice validation, return preparation, internal approval, submission, payment and record retention.": "Jurisdiction-neutral indirect-tax compliance sequence",
    }
    for query, heading in cases.items():
        answer = compose_accounting_fundamentals(query, "REF-1")
        assert heading in answer
        assert answer.count("[REF-1]") >= 6


def test_bank_management_summary_covers_controls_risks_and_correct_entries():
    answer = compose_bank_reconciliation(
        "Summarize the purpose, process, controls, and risks for senior management.", "REF-1"
    )
    assert "### Key risks and controls" in answer
    assert "### Management takeaway" in answer
    assert "normally do not require another entry" in answer


def test_month_end_answer_uses_an_explicitly_illustrative_schedule():
    answer = compose_month_end_close("Show the timeline.", "REF-1")
    assert "15th" not in answer
    assert "D−5 to D−1" in answer
    assert "illustrative five-business-day close" in answer
    assert "D+5" in answer


def test_month_end_control_request_is_grouped_by_role_and_evidence():
    answer = compose_month_end_close(
        "Create a checklist grouped by preparer, reviewer, supporting evidence, and escalation conditions.",
        "REF-1",
    )
    for heading in ("### Preparer controls", "### Reviewer controls", "### Supporting evidence", "### Escalation conditions"):
        assert heading in answer
    assert answer.count("[REF-1]") >= 6


def test_accounting_fundamentals_comparison_uses_real_gfm_table():
    answer = compose_accounting_fundamentals("Compare cash and accrual in a table.", "REF-1")
    assert "| Feature | Cash basis | Accrual basis |" in answer
    assert "|---|---|---|" in answer


def test_accounting_comparison_includes_requested_decision_flow():
    answer = compose_accounting_fundamentals(
        "Compare cash and accrual accounting and include a decision flow.", "REF-1"
    )
    assert "### Recognition decision flow" in answer
    assert "3. **For cash-basis accounting:**" in answer


def test_retained_earnings_has_complete_formula_and_worked_example():
    answer = compose_accounting_fundamentals(
        "What is retained earnings, and how is it calculated?", "REF-1"
    )
    assert "Beginning retained earnings + Net income − Dividends" in answer
    assert "$100,000 + $50,000 − $20,000" in answer
    assert "applicable amount" not in answer


def test_duplicate_revenue_receipt_returns_correcting_entry():
    answer = compose_accounting_fundamentals(
        "A customer paid a $12,000 invoice, but the payment was recorded as revenue again. "
        "Identify the error and provide the correcting journal entry.",
        "REF-1",
    )
    assert "| Revenue | $12,000 | — |" in answer
    assert "| Accounts receivable | — | $12,000 |" in answer


def test_audit_evidence_matrix_has_critical_override():
    answer = compose_accounting_fundamentals(
        "Create a scoring matrix for assessing the reliability and sufficiency of audit evidence.",
        "REF-1",
    )
    assert "| Factor | 1 — Weak | 2 — Moderate | 3 — Strong |" in answer
    assert "critical override" in answer


def test_receivables_trend_answer_has_targeted_procedures_without_context_leak():
    answer = compose_accounting_fundamentals(
        "Accounts receivable increased by 35% while revenue increased by only 8%. "
        "Explain the possible causes and recommend audit procedures.",
        "REF-1",
    )
    assert "subsequent cash receipts" in answer
    assert "sales cut-off" in answer
    assert "Content:" not in answer


def test_bank_swimlane_assigns_all_three_roles():
    answer = compose_bank_reconciliation(
        "Create a swimlane-style workflow showing the responsibilities of the preparer, "
        "reviewer, and approver during a bank reconciliation.",
        "REF-1",
    )
    assert "| Stage | Preparer | Reviewer | Approver |" in answer
    assert "Approve the completed reconciliation" in answer


def test_accounting_source_context_is_focused_for_reviewed_topics():
    retained = to_accounting_fundamentals_rag_chunk("What is retained earnings?")["text"]
    assert "Retained earnings is" in retained
    assert "Accounts payable proceeds" not in retained
    matrix = to_accounting_fundamentals_rag_chunk("Create an audit evidence scoring matrix")["text"]
    assert "evidence-assessment matrix" in matrix
    assert "Trial-balance preparation" not in matrix
    variance = to_accounting_fundamentals_rag_chunk(
        "Create a decision flow for whether an unexpected account movement needs more testing"
    )["text"]
    assert "For an unexplained account variance" in variance
    assert "Trial-balance preparation" not in variance


def test_ap_and_order_to_cash_requests_do_not_fall_back_to_accrual_definition():
    ap = compose_accounting_fundamentals("Show the accounts-payable process as a flow chart.", "REF-1")
    otc = compose_accounting_fundamentals("Show order-to-cash as a flow chart.", "REF-1")
    assert "## Accounts-payable process" in ap
    assert "8. **Reconcile and review:**" in ap
    assert "## Order-to-cash accounting process" in otc
    assert "7. **Reconcile receivables:**" in otc


def test_audit_evidence_flow_is_reviewed_and_cited():
    answer = compose_accounting_fundamentals("Show the audit evidence process as a flow chart.", "REF-1")
    assert "## Audit-evidence workflow" in answer
    assert "7. **Conclude or escalate:**" in answer
    assert answer.count("[REF-1]") >= 8


def test_audit_variance_decision_flow_is_reviewed_and_not_threshold_only():
    answer = compose_audit_variance_decision(
        "Create a decision flow for whether an unexplained account variance requires additional audit testing.",
        "REF-1",
    )
    assert answer is not None
    assert "Do not dismiss a variance only because it is below a quantitative threshold" in answer
    assert "6. **Perform additional procedures or escalate:**" in answer
    assert answer.count("[REF-1]") >= 7


def test_natural_review_questions_get_specific_reviewed_answers():
    assert "## Duplicate supplier-payment investigation" in compose_accounting_fundamentals(
        "What should I examine when a supplier appears to have been paid twice?", "REF-1"
    )
    assert "## Revenue cut-off review" in compose_accounting_fundamentals(
        "How do I check whether money received after year-end belongs in the current reporting period?", "REF-1"
    )
    assert "## Liability-completeness review" in compose_accounting_fundamentals(
        "What steps help confirm that all obligations incurred before year-end were recorded?", "REF-1"
    )
    evidence = compose_accounting_fundamentals(
        "What should happen when supporting documents contradict the amount recorded in the ledger?", "REF-1"
    )
    assert "## Evidence reliability and sufficiency review" in evidence
    assert "6. **Extend or escalate when needed:**" in evidence


def test_natural_unusual_balance_uses_reviewed_variance_decision():
    answer = compose_audit_variance_decision(
        "How should I investigate a balance that looks unusual compared with last month?", "REF-1"
    )
    assert answer is not None and "## Audit decision flow" in answer


def test_user_quarterly_data_is_parsed_and_profit_is_verified():
    query = (
        "Using this data, show profit: Q1 revenue $120,000 and expenses $90,000; "
        "Q2 revenue $135,000 and expenses $92,000."
    )
    rows = extract_quarterly_results(query)
    assert [row[3] for row in rows] == [30000, 43000]
    chunk = to_user_provided_data_rag_chunk(query)
    assert "$120,000 - $90,000 = $30,000" in chunk["text"]
    answer = compose_quarterly_results(query, "REF-1")
    assert "| Q1 | $120,000 [REF-1] | $90,000 [REF-1] | $30,000 [REF-1] |" in answer
    assert "**Total revenue:** $255,000 [REF-1]" in answer
    assert "**Total profit:** $73,000 [REF-1]" in answer
    assert "**Overall profit margin:** 28.6% [REF-1]" in answer
    assert "**Key insight:** Profit increased from $30,000 in Q1 to $43,000 in Q2" in answer


def test_monthly_user_data_gets_a_deterministic_table():
    query = "Show a line chart using this data: January revenue $100,000 and expenses $75,000; February revenue $115,000 and expenses $80,000."
    answer = compose_quarterly_results(query, "REF-1")
    assert "## Monthly revenue, expenses, and profit" in answer
    assert "| January | $100,000 [REF-1] | $75,000 [REF-1] | $25,000 [REF-1] |" in answer
    assert "a 40.0% change" in answer


def test_single_metric_period_series_gets_a_trend_table():
    quarterly = extract_user_data_table("Visualize quarterly expenses: Q1 $110,000, Q2 $118,000, Q3 $105,000, Q4 $125,000.")
    assert quarterly is not None and quarterly.title == "Quarterly expenses trend"
    assert quarterly.rows[-1] == ("Q4", 125000)
    monthly = extract_user_data_table("Show the monthly accounts-receivable trend: January $180,000, February $165,000, March $172,000.")
    assert monthly is not None and monthly.headers == ("Period", "Accounts-Receivable")


def test_budget_actual_and_balance_datasets_are_recognised():
    budget = extract_user_data_table("Show a chart: Payroll budget $200,000 and actual $210,000; Marketing budget $50,000 and actual $47,000.")
    assert budget is not None and budget.headers == ("Category", "Budget", "Actual", "Variance")
    assert budget.rows[0][3] == 10000
    versus = extract_user_data_table("Compare budget and actual expenses: payroll $100,000 versus $108,000; rent $30,000 versus $30,000; marketing $25,000 versus $21,000.")
    assert versus is not None and versus.headers == ("Category", "Budget", "Actual", "Variance")
    assert versus.rows == (("Payroll", 100000, 108000, 8000), ("Rent", 30000, 30000, 0), ("Marketing", 25000, 21000, -4000))
    balances = extract_user_data_table("Compare cash $120,000, receivables $180,000, and inventory $150,000 in a chart.")
    assert balances is not None and len(balances.rows) == 3
    departments = extract_user_data_table("Compare department expenses in a bar chart using this data: Sales $80,000, Marketing $60,000, Operations $95,000, and Finance $45,000.")
    assert departments is not None and departments.rows == (("Sales", 80000), ("Marketing", 60000), ("Operations", 95000), ("Finance", 45000))


def test_budget_and_balance_answers_include_professional_insights():
    budget = compose_quarterly_results("Show a chart: Payroll budget $200,000 and actual $210,000; Marketing budget $50,000 and actual $47,000.", "REF-1")
    assert "Overall spending is $7,000 over budget" in budget
    assert "**Total actual:** $257,000 [REF-1]" in budget
    balances = compose_quarterly_results("Compare cash $120,000, receivables $180,000, and inventory $150,000.", "REF-1")
    assert "Receivables is the largest item" in balances
    assert "**Displayed total:** $450,000 [REF-1]" in balances


def test_trial_balance_process_is_reviewed_and_cited():
    answer = compose_accounting_fundamentals("Explain the process for preparing a trial balance.", "REF-1")
    assert "## Trial-balance preparation process" in answer
    assert "8. **Retain review evidence:**" in answer
