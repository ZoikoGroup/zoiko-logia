from app.orchestration.educational_answers import (
    compose_accounting_fundamentals,
    compose_bank_reconciliation,
    compose_month_end_close,
)
from app.domains.reference_data.user_provided_data import (
    compose_quarterly_results,
    extract_user_data_table,
    extract_quarterly_results,
    to_user_provided_data_rag_chunk,
)


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


def test_bank_management_summary_covers_controls_risks_and_correct_entries():
    answer = compose_bank_reconciliation(
        "Summarize the purpose, process, controls, and risks for senior management.", "REF-1"
    )
    assert "### Key risks and controls" in answer
    assert "### Management takeaway" in answer
    assert "normally do not require another entry" in answer


def test_month_end_answer_has_no_invented_deadline():
    answer = compose_month_end_close("Show the timeline.", "REF-1")
    assert "15th" not in answer
    assert "8. **Issue and control the period:**" in answer


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


def test_budget_actual_and_balance_datasets_are_recognised():
    budget = extract_user_data_table("Show a chart: Payroll budget $200,000 and actual $210,000; Marketing budget $50,000 and actual $47,000.")
    assert budget is not None and budget.headers == ("Category", "Budget", "Actual", "Variance")
    assert budget.rows[0][3] == 10000
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
