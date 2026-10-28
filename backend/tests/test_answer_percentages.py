"""Calculated percentages are shown to two decimals (answer_formatting.py)."""
from app.orchestration.answer_formatting import calculated_percentages

# The D05 pie-chart answer, as Kriton wrote it.
PIE = ("| Quarter | Revenue (USD 000) | Share of FY 2025 revenue |\n|---|---|---|\n"
       "| Q1 | 2,100 | 21 % |\n| Q4 | 3,100 | 31 % |\n| Total FY 2025 revenue | 10,000 | 100 % |\n\n"
       "Q1 share: 2100 / 10000 * 100 = 21 %.\nQ4 share: 3100 / 10000 × 100 = 31 %.")


def test_calculated_shares_get_two_decimals():
    out = calculated_percentages(PIE)
    assert "| Q1 | 2,100 | 21.00% |" in out and "| Total FY 2025 revenue | 10,000 | 100.00% |" in out
    assert "2100 / 10000 * 100 = 21.00%." in out and "3100 / 10000 × 100 = 31.00%." in out


def test_a_margin_row_and_growth_column_get_two_decimals():
    table = "| Item | FY 2025 |\n|---|---|\n| Revenue | 10,000 |\n| Gross Margin | 38 % |"
    assert "| Gross Margin | 38.00% |" in calculated_percentages(table)
    growth = "| Quarter | Growth |\n|---|---|\n| Q4 | 24.5 % |"
    assert "| Q4 | 24.50% |" in calculated_percentages(growth)


def test_stated_rates_and_other_text_are_unchanged():
    text = ("VAT at 20% applies; the corporation tax rate is 25%.\n"
            "| Item | Rate |\n|---|---|\n| Standard VAT | 20 % |\n"
            "Box 100 = 5 is a label, and 38.25% stays as it is.")
    assert calculated_percentages(text) == text


def test_an_echo_of_kriton_s_own_instructions_is_removed():
    from app.orchestration.answer_formatting import remove_instruction_echoes
    text = ("| Gross margin | 43.00% |\n\nAll percentages are shown to two decimal places as required.\n\n"
            "Prepared by: Kriton – illustrative worksheet.")
    out = remove_instruction_echoes(text)
    assert "as required" not in out and "| Gross margin | 43.00% |" in out and "Prepared by" in out
    # An ordinary "as required" about the user's own obligations stays.
    kept = "The company must file its VAT return as required by HMRC."
    assert remove_instruction_echoes(kept) == kept


def test_trial_balance_ratios_state_their_formulas():
    from app.orchestration.document_figures import verified_document_figures
    from app.orchestration.websearch import WebSource
    tb = "\n".join(["account_name\tdebit\tcredit", "Revenue\t\t1000", "Cost of sales\t600\t", "Inventory\t300\t",
                    "Cash at bank\t400\t", "Trade payables\t\t200", "Share capital\t\t200", "Rent\t100\t"])
    figures = verified_document_figures([WebSource(title="tb.csv — Sheet1", url="", snippet=tb, source_id="d1")])
    assert "quick ratio ((current assets − inventory) ÷ current liabilities) = 2.00" in figures
    assert "Current ratio (current assets ÷ current liabilities) = 3.50" in figures
