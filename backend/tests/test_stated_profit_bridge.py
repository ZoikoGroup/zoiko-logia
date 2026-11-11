"""QA C05: a profit bridge of the amounts the question states, computed by
Kriton (live run, 11 Nov 2026: the correct net income 1,185,000 was removed as
unverified and EBITDA, EBIT and profit before tax were never shown)."""
from app.orchestration.figure_reconciliation import unreconciled_figures
from app.orchestration.stated_profit_bridge import verified_profit_bridge_block

C05 = ("For 2026 assume revenue is $12 million, COGS $7.2m, operating costs $2.6m, depreciation $0.5m, "
       "interest $0.12m and tax $0.395m; forecast net income.")


def test_c05_every_subtotal_is_computed_and_labelled_a_forecast():
    block = verified_profit_bridge_block(C05)
    assert "a forecast from the question's stated assumptions, not actual results" in block
    assert "- EBITDA = 4,800,000 − operating costs 2,600,000 = 2,200,000 (2.2 million)" in block
    assert "- EBIT = 2,200,000 − depreciation 500,000 = 1,700,000 (1.7 million)" in block
    assert "- profit before tax = 1,700,000 − interest 120,000 = 1,580,000 (1.58 million)" in block
    assert "- net income = 1,580,000 − tax 395,000 = 1,185,000 (1.185 million)" in block


def test_c05_the_answers_figures_pass_the_figure_check_with_the_block():
    answer = "EBITDA $2.2m; EBIT 1,700,000; profit before tax $1.58m; net income 1,185,000 ($1.185m)."
    assert "1,185,000" in unreconciled_figures(answer, C05, "", stated=C05)       # without it: removed
    assert unreconciled_figures(answer, C05 + verified_profit_bridge_block(C05), "", stated=C05) == []
    # A wrong net income is still caught.
    assert unreconciled_figures("Net income 1,285,000.", C05 + verified_profit_bridge_block(C05), "", stated=C05)


def test_a_tax_rate_is_applied_and_no_depreciation_means_operating_profit():
    block = verified_profit_bridge_block("Revenue 500,000, cost of sales 300,000, operating expenses 100,000, "
                                         "interest 10,000, tax 25%. What is net profit?")
    assert "- operating profit = 200,000 − operating costs 100,000 = 100,000" in block and "EBITDA" not in block
    assert "- tax = 90,000 × 25% = 22,500" in block and "- net income = 90,000 − tax 22,500 = 67,500" in block
    assert "calculated from the question's stated amounts" in block


def test_no_block_without_the_amounts_or_a_profit_question():
    assert verified_profit_bridge_block("What is net income under IFRS?") == ""
    assert verified_profit_bridge_block("Calculate F0 net income.") == ""
    assert verified_profit_bridge_block("Revenue $12m and COGS $7.2m: what is the gross margin?") == ""
