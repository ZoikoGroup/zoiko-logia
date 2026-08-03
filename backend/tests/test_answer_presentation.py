from app.orchestration.presentation import build_answer_presentation


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
    assert plan.charts[0].type == "line"
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
    # A single-series temporal table renders as "area" now (2-series-and-up
    # temporal tables still render as "line" — see the two-series test above).
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


def test_chart_contract_includes_deterministic_format_and_accessibility_metadata():
    plan = build_answer_presentation(
        "Show monthly receivables as a chart.",
        "| Month | Receivables |\n|---|---:|\n| January | $210,000 |\n| February | $195,000 |",
    )

    chart = plan.charts[0]
    assert chart.value_format == "currency"
    assert chart.currency_code == "USD"
    assert chart.decimal_places == 0
    assert chart.x_axis_label == "Month"
    assert chart.y_axis_label == "USD"
    assert "2 categories" in chart.accessible_summary
    assert "validated answer table" in chart.accessible_summary


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


def test_bulleted_checklist_under_headers_still_produces_a_checklist_guide():
    """Real incident (2026-07-29): an audit checklist written as headers
    followed by '- item' bullet lines (no numbered prefix at all) produced
    zero charts/metrics/guides — the whole visual panel silently didn't
    appear — because the extractor only ever recognized a literal '1.'/'1)'
    numbered prefix. A bulleted procedure/checklist is at least as common in
    real model output as a numbered one."""
    plan = build_answer_presentation(
        "Create an audit checklist for reviewing bank-reconciliation controls",
        "Control Environment\n"
        "- Evaluate the company's control environment, including the tone at the top.\n"
        "- Assess the competence and objectivity of the individuals performing reconciliations.\n\n"
        "Risk Assessment\n"
        "- Identify the locations or business units that are individually important.\n"
        "- Test controls over significant accounts and disclosures.",
    )
    assert len(plan.guides) == 1
    assert plan.guides[0].type == "checklist"
    assert plan.guides[0].items == [
        "Evaluate the company's control environment, including the tone at the top.",
        "Assess the competence and objectivity of the individuals performing reconciliations.",
        "Identify the locations or business units that are individually important.",
        "Test controls over significant accounts and disclosures.",
    ]


def test_asterisk_bullets_also_recognized():
    plan = build_answer_presentation(
        "Give me a review checklist",
        "* Review the bank statement.\n* Confirm outstanding items.\n* Reconcile the balance.",
    )
    assert plan.guides[0].type == "checklist"
    assert plan.guides[0].items == [
        "Review the bank statement.",
        "Confirm outstanding items.",
        "Reconcile the balance.",
    ]


def test_bold_lead_in_line_is_not_mistaken_for_a_bullet():
    """A line starting with '**Term**' (no bullet marker) must not match the
    bullet pattern just because it also starts with '*' — the '*' has to be
    immediately followed by whitespace to count as a bullet marker."""
    from app.orchestration.presentation import _ORDERED_LINE
    assert _ORDERED_LINE.match("**Materiality**: compare to threshold") is None
    assert _ORDERED_LINE.match("---") is None


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


def test_single_row_table_becomes_metric_card_not_a_dropped_chart():
    plan = build_answer_presentation(
        "What is our total revenue?",
        "| Metric | Value |\n|---|---:|\n| Total revenue | $482,000 [REF-1] |",
    )
    assert plan.layout == "data_visualization"
    assert plan.charts == []
    assert len(plan.metrics) == 1
    assert plan.metrics[0].label == "Total revenue"
    assert plan.metrics[0].value == "482000"
    assert plan.metrics[0].unit == "$"


def test_share_language_table_becomes_donut():
    plan = build_answer_presentation(
        "Show a breakdown of expenses by category",
        "| Expense category | Share |\n|---|---:|\n"
        "| Payroll | 45% |\n| Rent | 20% |\n| Marketing | 15% |\n"
        "| Software | 10% |\n| Travel | 6% |\n| Other | 4% |",
    )
    assert len(plan.charts) == 1
    assert plan.charts[0].type == "donut"
    assert plan.charts[0].categories == ["Payroll", "Rent", "Marketing", "Software", "Travel", "Other"]


def test_donut_caps_slices_and_rolls_remainder_into_other():
    rows = "\n".join(f"| Category {c} | {v}% |" for c, v in zip("ABCDEFGH", [20, 18, 15, 12, 10, 9, 8, 8]))
    plan = build_answer_presentation(
        "breakdown by category",
        f"| Category | Share |\n|---|---:|\n{rows}",
    )
    chart = plan.charts[0]
    assert chart.categories == ["Category A", "Category B", "Category C", "Category D", "Category E", "Other"]
    assert chart.series[0].values == ["20", "18", "15", "12", "10", "25"]


def test_decision_judgment_query_produces_decision_flow_guide():
    plan = build_answer_presentation(
        "Does an unexplained variance require additional audit testing?",
        "## Considerations for additional testing\n\n"
        "1. **Materiality**: Compare the variance to the applicable materiality threshold. [REF-1]\n"
        "2. **Qualitative risk**: Consider indicators unrelated to size, such as prior misstatements. [REF-1]\n"
        "3. **Evidence sufficiency**: Assess whether evidence already obtained addresses the risk. [REF-1]\n"
        "4. **Escalation**: Escalate to the audit manager if evidence remains insufficient. [REF-1]\n\n"
        "The actual conclusion depends on the specific facts of the engagement. [REF-1]",
    )
    assert plan.guides[0].type == "decision_flow"
    assert plan.guides[0].title == "Decision considerations"
    assert len(plan.guides[0].items) == 4


def test_ordinary_checklist_query_still_gets_checklist_not_decision_flow():
    plan = build_answer_presentation(
        "Give me a checklist for bank reconciliation.",
        "1. **Select the period.** [REF-1]\n2. **Confirm the opening balance.** [REF-1]",
    )
    assert plan.guides[0].type == "checklist"


def test_plain_two_item_comparison_is_bar_not_donut():
    """A donut must never be inferred from value sign alone — an ordinary
    2-column comparison with no share/composition language stays a bar,
    even with an explicit chart request and non-negative values."""
    plan = build_answer_presentation(
        "Show a chart comparing cash and receivables",
        "| Account | Balance |\n|---|---:|\n| Cash | $50,000 |\n| Receivables | $30,000 |",
    )
    assert len(plan.charts) == 1
    assert plan.charts[0].type == "bar"


def test_every_recognised_currency_is_permitted_by_the_chart_contract():
    """_CURRENCY_BY_UNIT and PresentationChart.currency_code's Literal were
    two independent lists of permitted currencies. Adding a symbol to the map
    without widening the Literal makes pydantic reject the chart inside
    _chart_from_table — which has no try/except, and neither does
    build_answer_presentation — so it surfaces as a failed answer rather than
    a missing chart.
    """
    from typing import get_args, get_type_hints

    from app.orchestration.presentation import _CURRENCY_BY_UNIT
    from app.orchestration.schemas import PresentationChart

    annotation = get_type_hints(PresentationChart)["currency_code"]
    # Optional[Literal[...]] -> pull the Literal's members out of the union.
    permitted = {
        member
        for arg in get_args(annotation)
        for member in get_args(arg)
        if isinstance(member, str)
    }
    unmapped = set(_CURRENCY_BY_UNIT.values()) - permitted
    assert not unmapped, (
        f"{sorted(unmapped)} can be produced by _CURRENCY_BY_UNIT but would be "
        f"rejected by PresentationChart.currency_code (permits {sorted(permitted)})"
    )


def test_a_recognised_currency_symbol_actually_builds_a_chart():
    # The guard above is static; this proves the round trip for each symbol.
    from app.orchestration.presentation import _CURRENCY_BY_UNIT

    for symbol in ("$", "£", "€"):
        answer = (
            f"| Segment | Revenue |\n| --- | --- |\n"
            f"| Retail | {symbol}60,000 |\n| Wholesale | {symbol}40,000 |\n"
        )
        presentation = build_answer_presentation("chart revenue by segment", answer)
        assert presentation.charts, f"{symbol} produced no chart"
        assert presentation.charts[0].currency_code == _CURRENCY_BY_UNIT[symbol]
