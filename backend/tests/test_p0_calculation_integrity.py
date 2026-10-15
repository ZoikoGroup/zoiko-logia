"""P0 calculation integrity: supplied figures are read, kept and reconciled,
and a follow-up changes only what the user changed."""
from decimal import Decimal

from app.orchestration.calculations.engine import calculate_from_query, change_followup
from app.orchestration.schemas import ConversationMessage as M


def out(result, name):
    return next(o.value for o in result.outputs if o.name == name)


def test_a_cost_of_goods_sold_is_read_not_asked_for_again():
    r = calculate_from_query("Revenue is £250,000 and cost of goods sold is £160,000. Calculate gross profit, "
                             "gross margin and COGS as a percentage of revenue.")
    assert r.status == "success"
    assert out(r, "gross_profit") == Decimal("90000")
    assert out(r, "gross_margin") == Decimal("36")
    assert out(r, "cost_of_sales_as_percentage_of_revenue") == Decimal("64")


def test_b_supplied_cost_of_sales_is_preserved():
    r = calculate_from_query("Revenue is £500,000 and COGS is £125,000. Calculate gross profit and gross margin.")
    cost = next(i for i in r.inputs if i.name == "cost_of_sales")
    assert cost.value == Decimal("125000")
    assert out(r, "gross_profit") == Decimal("375000")
    assert "200,000" not in " ".join(r.steps)


def test_c_reported_figures_are_reconciled_not_overwritten():
    r = calculate_from_query(
        "A company reports revenue of £500,000, cost of goods sold of £320,000, gross profit of £190,000 and "
        "operating expenses of £110,000. Check whether the reported figures reconcile. Do not silently overwrite "
        "the reported figures.")
    assert r.status == "success" and "gross_profit_reconciliation" in r.formula_ids
    assert out(r, "reported_gross_profit") == Decimal("190000")       # kept
    assert out(r, "calculated_gross_profit") == Decimal("180000")
    assert out(r, "difference_reported_minus_calculated") == Decimal("10000")
    assert out(r, "operating_profit_on_calculated_gross_profit") == Decimal("70000")
    assert any("Inconsistency" in n and "has not been changed" in n for n in r.notes)
    assert any("accountant must confirm" in n for n in r.notes)


def test_figures_that_agree_are_said_to_agree():
    r = calculate_from_query("Revenue £500,000, cost of sales £320,000, gross profit £180,000. Do these reconcile?")
    assert out(r, "difference_reported_minus_calculated") == 0
    assert any("agrees" in n for n in r.notes)


def test_d_follow_up_changes_only_what_the_user_changed():
    history = [M(role="user", content="Revenue is £250,000 and COGS is £160,000. Calculate gross profit and margin.")]
    r = change_followup("What happens if revenue increases by 15%?", history)
    assert out(r, "revenue") == Decimal("287500")
    assert out(r, "cost_of_sales") == Decimal("160000")
    assert out(r, "gross_profit") == Decimal("127500")
    assert round(out(r, "gross_margin"), 2) == Decimal("44.35")
    assert all(i.source_location == "earlier message" for i in r.inputs)


def test_a_cost_change_keeps_revenue_and_a_fall_lowers_it():
    history = [M(role="user", content="Revenue is £250,000 and COGS is £160,000.")]
    r = change_followup("What if cost of sales falls by 10%?", history)
    assert out(r, "revenue") == Decimal("250000") and out(r, "cost_of_sales") == Decimal("144000")


def test_follow_up_uses_only_user_figures_and_needs_both():
    assistant_only = [M(role="assistant", content="Revenue is £250,000 and COGS is £160,000.")]
    assert change_followup("What if revenue increases by 15%?", assistant_only) is None
    assert change_followup("What if revenue increases by 15%?", [M(role="user", content="Revenue is £250,000.")]) is None
    # A follow-up stating its own figures is calculated from those, not history.
    assert change_followup("Revenue is £100 and COGS £50; what if revenue increases by 15%?",
                           [M(role="user", content="Revenue is £250,000 and COGS is £160,000.")]) is None


def test_a_comma_never_pulls_the_previous_figure_into_a_label():
    """'revenue of £200,000, cost of goods sold of £125,000' was calculated
    with cost of sales £200,000 (qry-6d5c6c721f92)."""
    r = calculate_from_query(
        "A junior accountant reports revenue of £200,000, cost of goods sold of £125,000, gross profit of £75,000, "
        "operating expenses of £45,000 and operating profit of £40,000. Identify any arithmetic errors and "
        "calculate the correct figures.")
    cost = next(i for i in r.inputs if i.name == "cost_of_sales")
    assert cost.value == Decimal("125000")
    assert out(r, "operating_profit_on_calculated_gross_profit") == Decimal("30000")
    # Gross profit agrees; the operating profit is the error, and it is named.
    assert any("reported operating profit (£40,000.00) is £10,000.00 higher" in n for n in r.notes)
    assert not any("reported gross profit (£75,000.00)" in n for n in r.notes)


def test_a_pasted_document_is_not_calculated_unless_the_request_asks():
    paste = "Overall impression\n\n" + "Completed deals gave gross profit of $919,000 on revenue of $2,000,000. " * 30
    assert calculate_from_query(paste + "\n\nsummarise this in 5 points").status == "not_matched"
    assert calculate_from_query(paste + "\n\nCalculate the gross margin.").status != "not_matched"


def test_a_percentage_of_an_amount_is_plain_arithmetic():
    """"What's 18% of £3,400?" was answered "the sources found do not establish
    the answer" after a web search."""
    r = calculate_from_query("What's 18% of £3,400?")
    assert r.status == "success" and out(r, "result") == Decimal("612")
    assert calculate_from_query("What is 12.5% of 8,000?").outputs[0].value == Decimal("1000")
    # Several percentages or a tax question are not this formula.
    assert calculate_from_query("18% of £3,400 and 20% of £1,000?").status == "not_matched"
    assert "percentage_of_amount" not in calculate_from_query("VAT at 20% of £1,000 excluding VAT").formula_ids
