import app.orchestration.presentation as presentation
from app.orchestration.presentation import _plain, build_answer_presentation
from app.orchestration.presentation_llm_classifier import GuideClassification


def test_inline_citation_marker_does_not_swallow_the_surrounding_word_boundary():
    # Live bug: _CITATION's \s*...\s* consumed the whitespace on both sides
    # of the marker along with it, so "significance and [REF-3] risk" lost
    # both spaces and concatenated into "andrisk" — same failure hit
    # "the [REF-x] explanation", "recorded [REF-x] correctly", and
    # "bank [REF-x] activity" in guide/sequence-diagram text.
    assert _plain("the significance and [REF-3] risk of the exception") == (
        "the significance and risk of the exception"
    )
    assert _plain("Confirm the entry was recorded [REF-2] correctly.") == (
        "Confirm the entry was recorded correctly."
    )


def test_numeric_cell_parses_a_leading_minus_sign_before_the_currency_symbol():
    # Real gap (2026-08-03): "-$90,000" (sign before currency — how
    # user_provided_data.py's _money() formats a negative figure) failed to
    # parse at all; only "$-90,000" (currency before sign) worked. A single
    # unparseable cell drops its entire column from the chart (see
    # _chart_from_table's `if any(value is None ...): continue`), so one
    # negative dollar value silently zeroed out an otherwise perfectly
    # chartable table — a cash-flow bridge with any reduction, or a
    # budget-vs-actual variance column with any underrun.
    assert presentation._numeric("-$90,000") == ("-90000", "$")
    assert presentation._numeric("$-90,000") == ("-90000", "$")
    assert presentation._numeric("$500,000") == ("500000", "$")
    assert presentation._numeric("(90,000)") == ("-90000", "")


def _explode_if_called(*args, **kwargs):
    raise AssertionError("LLM fallback classifier must not be called for a confidently rule-classified query")


def test_descriptive_answer_selects_descriptive_layout():
    plan = build_answer_presentation(
        "Explain accrual accounting",
        "## What it is\n\nAccrual accounting recognizes activity when earned. [REF-1]",
    )
    assert plan.layout == "descriptive"
    assert plan.table_count == 0
    assert plan.charts == []
    assert plan.sections == []
    assert len(plan.follow_up_questions) == 3


def test_comparison_table_is_detected_without_forcing_a_chart():
    plan = build_answer_presentation(
        "Compare cash and accrual accounting",
        "| Feature | Cash | Accrual |\n|---|---|---|\n| Revenue | On receipt | When earned |",
    )
    assert plan.layout == "comparison"
    assert plan.table_count == 1
    assert plan.charts == []


def test_demo_evidence_table_builds_cytoscape_graph():
    answer = """## Supplier-invoice evidence relationships

| Source | Source Type | Relationship | Target | Target Type | Reference |
|---|---|---|---|---|---|
| INV-1045 | invoice | issued_by | ABC Ltd | supplier | REF-1 |
| INV-1045 | invoice | references | PO-880 | purchase_order | REF-1 |
| INV-1045 | invoice | matched_to | GRN-225 | receipt | REF-1 |
| INV-1045 | invoice | paid_by | PAY-990 | payment | REF-1 |
| INV-1045 | invoice | recorded_as | JE-450 | ledger_entry | REF-1 |"""
    plan = build_answer_presentation("Create an evidence relationship graph connecting these records", answer)
    assert len(plan.graphs) == 1
    assert len(plan.graphs[0].nodes) == 6
    assert len(plan.graphs[0].edges) == 5


def test_visualize_how_variance_request_gets_mermaid_process():
    answer = """## Audit decision flow

1. Validate the variance.
2. Collect supporting evidence.
3. Challenge the explanation.
4. Resolve or escalate the matter."""
    plan = build_answer_presentation(
        "Visualize how an unexplained account variance moves through investigation and final resolution.",
        answer,
    )
    assert plan.guides[0].type == "process"
    assert plan.guides[0].renderer == "mermaid"


def test_complete_numeric_table_creates_chart_from_validated_values():
    plan = build_answer_presentation(
        "Show revenue by quarter",
        "| Quarter | Revenue | Expenses |\n"
        "|---|---:|---:|\n"
        "| Q1 | $120,000 [REF-1] | $90,000 [REF-1] |\n"
        "| Q2 | $135,000 [REF-1] | $92,000 [REF-1] |",
    )
    assert plan.layout == "data_visualization"
    assert plan.table_count == 1
    assert len(plan.charts) == 1
    assert plan.charts[0].type == "area"
    assert plan.charts[0].summary_mode == "latest"
    assert plan.charts[0].domain == "accounting"
    assert plan.charts[0].categories == ["Q1", "Q2"]
    assert plan.charts[0].unit == "$"
    assert plan.charts[0].series[0].values == ["120000", "135000"]


def test_four_digit_years_are_valid_timeline_categories():
    plan = build_answer_presentation(
        "Show a chart of US GDP growth over the last 5 years.",
        "| Year | Real GDP growth |\n"
        "|---|---:|\n"
        "| 2022 | 1.9% |\n"
        "| 2023 | 2.5% |\n"
        "| 2024 | 2.8% |\n"
        "| 2025 | 2.0% |\n"
        "| 2026 | 1.7% |",
    )
    assert len(plan.charts) == 1
    assert plan.charts[0].type == "area"
    assert plan.charts[0].categories == ["2022", "2023", "2024", "2025", "2026"]
    assert plan.charts[0].unit == "%"


def test_budget_chart_keeps_variance_in_table_but_not_chart_series():
    answer = """| Category | Budget | Actual | Variance |
|---|---:|---:|---:|
| Payroll | $200,000 | $210,000 | $10,000 |
| Marketing | $50,000 | $47,000 | -$3,000 |"""
    plan = build_answer_presentation("Show budget versus actual in a bar chart.", answer)
    assert [series.name for series in plan.charts[0].series] == ["Budget", "Actual"]


def test_incomplete_or_mixed_unit_column_is_not_charted():
    plan = build_answer_presentation(
        "Compare results",
        "| Period | Result |\n|---|---|\n| Q1 | $100 |\n| Q2 | 20% |",
    )
    assert plan.layout == "comparison"
    assert plan.charts == []


def test_numbered_procedure_selects_step_layout():
    plan = build_answer_presentation(
        "How do I reconcile the account?",
        "1. Obtain the ledger.\n2. Compare it with the statement.\n3. Investigate differences.",
    )
    assert plan.layout == "step_by_step"
    assert plan.has_steps is True
    assert len(plan.guides) == 1
    assert plan.guides[0].type == "process"
    assert plan.guides[0].items == [
        "Obtain the ledger.",
        "Compare it with the statement.",
        "Investigate differences.",
    ]


def test_analysis_with_numbered_procedures_does_not_duplicate_answer_as_visual():
    plan = build_answer_presentation(
        "Explain why receivables increased and recommend audit procedures.",
        "1. Reconcile the complete receivables subledger to the general ledger and reproduce the aging analysis.\n"
        "2. Test subsequent cash receipts and investigate contradictory evidence.",
    )
    assert plan.guides == []


def test_guide_items_keep_complete_validated_sentences():
    long_step = (
        "Reconcile the receivables subledger to the general ledger and reproduce the trend, "
        "aging, and days-sales-outstanding analysis without omitting relevant segments."
    )
    plan = build_answer_presentation("Create an audit workflow", f"1. {long_step}")
    assert plan.guides[0].items == [long_step]
    assert "…" not in plan.guides[0].items[0]


def test_follow_ups_match_journal_matrix_and_swimlane_requests():
    journal = build_answer_presentation(
        "Provide the correcting journal entry.",
        "| Account | Debit | Credit |\n|---|---:|---:|\n| Revenue | $100 | — |",
    )
    assert journal.follow_up_questions[0].startswith("Show the original")
    matrix = build_answer_presentation(
        "Create an audit evidence scoring matrix.",
        "| Factor | Weak | Strong |\n|---|---|---|\n| Relevance | Indirect | Direct |",
    )
    assert matrix.follow_up_questions[0].startswith("Apply this matrix")
    swimlane = build_answer_presentation(
        "Create a bank-reconciliation swimlane.",
        "| Stage | Preparer | Reviewer |\n|---|---|---|\n| Close | Prepare | Review |",
    )
    assert swimlane.follow_up_questions[0].startswith("Add evidence")


def test_timeline_query_uses_timeline_visual_for_grounded_steps():
    plan = build_answer_presentation(
        "Show the filing timeline",
        "1. Prepare the return. [REF-1]\n2. Submit it by the supported deadline. [REF-1]",
    )
    assert plan.guides[0].type == "timeline"
    assert plan.guides[0].title == "Timeline"
    assert plan.guides[0].items[0] == "Prepare the return."
    assert plan.layout == "step_by_step"
    assert plan.follow_up_questions[0] == "Turn this timeline into an owner-and-deadline checklist."


def test_visual_process_uses_concise_stage_labels():
    plan = build_answer_presentation(
        "Give me the steps",
        "1. **Select the period:** Obtain the matching statement and ledger.\n"
        "2. **Match transactions:** Compare deposits and withdrawals.",
    )
    assert plan.guides[0].items == ["Select the period", "Match transactions"]


def test_review_query_uses_checklist_visual():
    plan = build_answer_presentation(
        "Give me a review checklist",
        "1. Verify the balance.\n2. Document the reviewer.",
    )
    assert plan.guides[0].type == "checklist"


def test_audit_decision_query_uses_domain_decision_flow():
    plan = build_answer_presentation(
        "Create an audit decision flow for whether a variance needs testing",
        "1. Compare the variance with the threshold.\n2. Evaluate the control evidence.\n3. Document the conclusion.",
    )
    assert plan.guides[0].type == "decision_flow"
    assert plan.guides[0].domain == "audit"


def test_communication_query_uses_sequence_diagram():
    plan = build_answer_presentation(
        "Show how the chatbot communicates with the calculation engine",
        "1. Frontend sends the query to the Classifier.\n"
        "2. Classifier forwards the risk-scored query to the Calculation Engine.\n"
        "3. Calculation Engine returns the verified result to Frontend.",
    )
    assert plan.guides[0].type == "sequence"
    assert plan.guides[0].title == "Sequence flow"
    assert plan.guides[0].renderer == "mermaid"
    assert plan.follow_up_questions[0].startswith("Explain what happens if a step")


def test_sequence_query_does_not_misclassify_as_decision_flow():
    plan = build_answer_presentation(
        "Show the message flow between the classifier and the calculation engine",
        "1. Classifier sends the query to the Calculation Engine.\n"
        "2. Calculation Engine returns the result to Classifier.",
    )
    assert plan.guides[0].type == "sequence"


def test_obvious_sequence_query_remains_rule_classified(monkeypatch):
    monkeypatch.setattr(presentation.presentation_llm_classifier, "classify", _explode_if_called)
    plan = build_answer_presentation(
        "Show the sequence diagram for how the classifier talks to the calculation engine",
        "1. Classifier sends the query to the Calculation Engine.\n"
        "2. Calculation Engine returns the result to Classifier.",
    )
    assert plan.guides[0].type == "sequence"


def test_obvious_flowchart_query_remains_rule_classified(monkeypatch):
    monkeypatch.setattr(presentation.presentation_llm_classifier, "classify", _explode_if_called)
    plan = build_answer_presentation(
        "Create a flowchart for whether a variance needs testing",
        "1. Compare the variance with the threshold.\n2. Evaluate the control evidence.\n3. Document the conclusion.",
    )
    assert plan.guides[0].type == "decision_flow"


def test_ambiguous_process_query_is_classified_through_llm_fallback(monkeypatch):
    def fake_classify(query, ordered_items):
        assert ordered_items  # deterministic steps are passed through, never invented
        return GuideClassification(
            guide_type="process",
            confidence=0.88,
            reasoning_summary="Sequential swimlane stages with no branching.",
            requires_clarification=False,
            model="gpt-4o-mini-test",
        )
    monkeypatch.setattr(presentation.presentation_llm_classifier, "classify", fake_classify)
    # "Show this as a swimlane." has guide-request signal (swimlane) but
    # matches none of the specific rule regexes — the genuinely ambiguous case.
    plan = build_answer_presentation(
        "Show this as a swimlane.",
        "1. Preparer drafts the entry.\n2. Reviewer checks it.\n3. Approver signs off.",
    )
    assert plan.guides[0].type == "process"
    assert plan.guides[0].title == "Process overview"


def test_invalid_llm_output_falls_back_safely(monkeypatch):
    def fake_classify(query, ordered_items):
        return GuideClassification(
            guide_type="gauge",  # not an approved PresentationGuide.type literal
            confidence=0.95,
            reasoning_summary="Invalid.",
            requires_clarification=False,
            model="gpt-4o-mini-test",
        )
    monkeypatch.setattr(presentation.presentation_llm_classifier, "classify", fake_classify)
    plan = build_answer_presentation(
        "Show this as a swimlane.",
        "1. Preparer drafts the entry.\n2. Reviewer checks it.\n3. Approver signs off.",
    )
    assert plan.guides == []


def test_low_confidence_llm_result_requests_clarification(monkeypatch):
    def fake_classify(query, ordered_items):
        return GuideClassification(
            guide_type="process",
            confidence=0.3,
            reasoning_summary="Not sure which layout fits.",
            requires_clarification=False,
            model="gpt-4o-mini-test",
        )
    monkeypatch.setattr(presentation.presentation_llm_classifier, "classify", fake_classify)
    plan = build_answer_presentation(
        "Show this as a swimlane.",
        "1. Preparer drafts the entry.\n2. Reviewer checks it.\n3. Approver signs off.",
    )
    assert plan.guides == []
    assert plan.follow_up_questions == [
        "Would you like this shown as a flowchart, timeline, checklist, or process overview?"
    ]


def test_llm_timeout_does_not_break_the_user_response(monkeypatch):
    def fake_classify(query, ordered_items):
        raise TimeoutError("provider timed out")
    monkeypatch.setattr(presentation.presentation_llm_classifier, "classify", fake_classify)
    plan = build_answer_presentation(
        "Show this as a swimlane.",
        "1. Preparer drafts the entry.\n2. Reviewer checks it.\n3. Approver signs off.",
    )
    assert plan.guides == []


def test_invoice_supplier_purchase_order_payment_chain_builds_graph():
    plan = build_answer_presentation(
        "Trace invoice INV-100 through to its payment.",
        "The chain below is built from validated records.\n\n"
        "| Source | Source Type | Relationship | Target | Target Type |\n"
        "|---|---|---|---|---|\n"
        "| INV-100 | Invoice | issued_by | SUP-1 | Supplier |\n"
        "| INV-100 | Invoice | references | PO-55 | Purchase Order |\n"
        "| PMT-9 | Payment | matched_to | INV-100 | Invoice |\n",
    )
    assert len(plan.graphs) == 1
    graph = plan.graphs[0]
    assert {node.id for node in graph.nodes} == {"INV-100", "SUP-1", "PO-55", "PMT-9"}
    assert len(graph.edges) == 3
    node_types = {node.id: node.entity_type for node in graph.nodes}
    assert node_types["PO-55"] == "purchase_order"
    assert node_types["PMT-9"] == "payment"
    assert graph.layout == "breadthfirst"
    assert plan.layout == "data_visualization"


def test_hub_topology_around_one_entity_uses_concentric_layout():
    plan = build_answer_presentation(
        "Show the relationships connected to this supplier.",
        "| Source | Source Type | Relationship | Target | Target Type |\n"
        "|---|---|---|---|---|\n"
        "| INV-100 | Invoice | issued_by | SUP-1 | Supplier |\n"
        "| CONTRACT-1 | Contract | belongs_to | SUP-1 | Supplier |\n"
        "| PMT-9 | Payment | paid_by | SUP-1 | Supplier |\n",
    )
    assert len(plan.graphs) == 1
    graph = plan.graphs[0]
    assert graph.layout == "concentric"
    assert {node.id for node in graph.nodes} == {"INV-100", "CONTRACT-1", "PMT-9", "SUP-1"}


def test_payment_bank_transaction_ledger_entry_evidence_chain():
    plan = build_answer_presentation(
        "Show the evidence chain from this payment to the ledger entry.",
        "| Source | Source Type | Relationship | Target | Target Type |\n"
        "|---|---|---|---|---|\n"
        "| PMT-9 | Payment | reconciled_with | BTX-3 | Bank Transaction |\n"
        "| BTX-3 | Bank Transaction | recorded_as | GL-77 | Ledger Entry |\n",
    )
    assert len(plan.graphs) == 1
    graph = plan.graphs[0]
    assert {node.id for node in graph.nodes} == {"PMT-9", "BTX-3", "GL-77"}
    assert [edge.relationship_type for edge in graph.edges] == ["reconciled_with", "recorded_as"]
    assert graph.layout == "breadthfirst"
    assert graph.title == "Evidence chain"


def test_empty_graph_falls_back_to_text():
    plan = build_answer_presentation(
        "Explain the relationships between these accounting records.",
        "There is no structured evidence table in this answer, only prose "
        "describing how records generally relate to one another.",
    )
    assert plan.graphs == []


def test_relationship_query_without_valid_table_does_not_force_a_graph():
    plan = build_answer_presentation(
        "Show the relationships involved.",
        "| Period | Revenue |\n|---|---:|\n| Q1 | $100 |\n| Q2 | $120 |",
    )
    assert plan.graphs == []


def test_existing_chart_and_sequence_renderers_remain_unchanged():
    chart_plan = build_answer_presentation(
        "Visualize the tax expense breakdown by category",
        "| Tax category | Amount |\n|---|---:|\n| Current tax | $80 |\n| Deferred tax | $20 |",
    )
    assert chart_plan.charts[0].type == "donut"
    assert chart_plan.graphs == []

    sequence_plan = build_answer_presentation(
        "Show the sequence diagram for how the classifier talks to the calculation engine",
        "1. Classifier sends the query to the Calculation Engine.\n"
        "2. Calculation Engine returns the result to Classifier.",
    )
    assert sequence_plan.guides[0].type == "sequence"
    assert sequence_plan.graphs == []


def test_tax_breakdown_uses_donut_visual():
    plan = build_answer_presentation(
        "Visualize the tax expense breakdown by category",
        "| Tax category | Amount |\n|---|---:|\n| Current tax | $80 |\n| Deferred tax | $20 |",
    )
    assert plan.charts[0].type == "donut"
    assert plan.charts[0].domain == "tax"
    assert plan.follow_up_questions[0] == "Explain the largest share in this composition."


def test_plural_expenses_are_labelled_as_accounting_analysis():
    plan = build_answer_presentation(
        "Visualize quarterly operating expenses",
        "| Period | Expenses |\n|---|---:|\n| Q1 | $120 |\n| Q2 | $135 |",
    )
    assert plan.charts[0].domain == "accounting"


def test_section_overview_is_limited_and_deduplicated():
    plan = build_answer_presentation(
        "Explain the full picture",
        "## Overview\nText.\n## Details\nText.\n## Overview\nText.",
    )
    assert plan.sections == ["Overview", "Details"]


def test_calculation_input_table_does_not_create_meaningless_chart_or_timeline():
    plan = build_answer_presentation(
        "Calculate effective tax rate when tax expense is $21,000 and pretax income is $100,000.",
        "## Effective Tax Rate\n\n### Verified result\n\n**21.00%** [REF-1]\n\n"
        "### Inputs\n\n| Input | Value | Unit |\n|---|---:|---|\n"
        "| Tax expense | 21000 | USD |\n| Pretax income | 100000 | USD |\n\n"
        "### Calculation steps\n\n1. Tax expense / pretax income = 21%.\n\n"
        "Calculation ID: `calc-test`",
    )
    assert plan.layout == "calculation"
    assert plan.charts == []
    assert plan.guides == []
    assert plan.sections == []
    assert plan.follow_up_questions[0] == "Explain what this result means."


def test_missing_input_answer_has_no_decorative_visuals_or_followups():
    plan = build_answer_presentation(
        "Calculate materiality with benchmark amount $5,000,000.",
        "## Information needed\n\nPlease provide the user-selected percentage. [REF-1]",
    )
    assert plan.layout == "concise"
    assert plan.charts == []
    assert plan.guides == []
    assert plan.sections == []
    assert plan.follow_up_questions == []


def test_word_when_does_not_turn_a_calculation_into_timeline():
    plan = build_answer_presentation(
        "Calculate net profit when revenue is $250,000 and expenses are $180,000.",
        "## Net Profit\n\n### Verified result\n\n**$70,000** [REF-1]\n\nCalculation ID: `calc-test`",
    )
    assert plan.layout == "calculation"


def test_compare_and_rank_keywords_allow_automatic_charting():
    # Real gap (2026-08-04): _VISUAL_REQUEST was missing "compare"/"rank",
    # so a fully supplied dataset whose query only said "Compare ... on
    # ..." (no literal "chart"/"graph"/"show" word) extracted correctly
    # but never triggered allow_automatic_chart, silently producing zero
    # charts despite complete tabular data reaching this stage.
    compare_plan = build_answer_presentation(
        "Compare Vendor A, Vendor B, and Vendor C on quality, delivery speed, reliability, and cost efficiency.",
        "| Category | Quality | Delivery Speed | Reliability | Cost Efficiency |\n|---|---:|---:|---:|---:|\n"
        "| Vendor A | 82 [REF-1] | 75 [REF-1] | 91 [REF-1] | 68 [REF-1] |\n"
        "| Vendor B | 76 [REF-1] | 88 [REF-1] | 84 [REF-1] | 73 [REF-1] |\n"
        "| Vendor C | 90 [REF-1] | 72 [REF-1] | 86 [REF-1] | 79 [REF-1] |",
    )
    assert compare_plan.charts

    rank_plan = build_answer_presentation(
        "Rank product revenue.",
        "| Category | Amount |\n|---|---:|\n| Widget | $50,000 [REF-1] |\n"
        "| Gadget | $72,000 [REF-1] |\n| Gizmo | $31,000 [REF-1] |",
    )
    assert rank_plan.charts


def test_break_down_two_words_allows_automatic_charting():
    # Real gap (2026-08-04): _VISUAL_REQUEST didn't recognize "break down"
    # (two words), so a fully supplied dataset introduced with that
    # natural phrasing extracted correctly but produced zero charts.
    plan = build_answer_presentation(
        "Break down our expenses by category.",
        "| Category | Amount |\n|---|---:|\n| Salaries | 45 [REF-1] |\n"
        "| Rent | 15 [REF-1] |\n| Marketing | 12 [REF-1] |",
    )
    assert plan.charts
