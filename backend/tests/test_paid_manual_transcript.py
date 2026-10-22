from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.calculations.inventory_statement import inventory_followup, reconciliation_followup
from app.orchestration.input_requirements import statement_not_question
from app.orchestration.schemas import ConversationMessage as M
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

VAT = 'Sales were £150,000, including VAT at 20%. Calculate sales excluding VAT and the VAT amount. Do not ask for a jurisdiction because I have supplied the rate and treatment.'
WHOLESALE = ('I manage a wholesale business. All figures are GBP and relate to one year. Revenue is £960,000, '
             'sales returns are £24,000, opening inventory is £85,000, purchases are £570,000, and closing inventory is £95,000. '
             'Salaries are £140,000, rent £42,000, utilities £18,000, depreciation £22,000, and interest £9,000. '
             'Calculate net sales, cost of goods sold, gross profit, gross margin, total operating expenses, operating profit '
             'and profit before tax. Show formulas and a results table. Explain the difference between inventory, an expense '
             'and a cash payment. Do not assume purchases were paid immediately. Finish with two questions management should investigate.')
CORRECTION = 'Closing inventory was overstated by £10,000. Correct only that figure and update the results. Explain the effect without asking me to repeat the original information.'
DIFFERENCES = 'Highlight the most important differences between the original and corrected results. Do not just repeat the calculation table.'
RECON = ('Our report says revenue £500,000, cost of sales £320,000 and gross profit £210,000. Do not silently change any '
         'reported number. Show the discrepancy, calculate the implied gross margin under each interpretation, and explain what information would resolve it.')


def values(result):
    return {item.name: item.value for item in result.outputs}


def test_inclusive_input_is_not_overridden_by_requested_exclusive_output():
    result = calculate_from_query(VAT)
    assert result.status == 'success'
    assert values(result) == {'vat_amount': 25000, 'amount_excluding_vat': 125000}


def test_inventory_statement_keeps_finance_costs_out_of_operating_expenses():
    result = calculate_from_query(WHOLESALE)
    v = values(result)
    assert v['net_sales'] == 936000 and v['cost_of_goods_sold'] == 560000
    assert v['gross_profit'] == 376000 and v['operating_expenses'] == 222000
    assert v['operating_profit'] == 154000 and v['profit_before_tax'] == 145000
    assert round(v['gross_margin'], 2) == Decimal('40.17')


def test_inventory_correction_and_followup_comparison_use_user_baseline():
    history = [M(role='user', content=WHOLESALE), M(role='assistant', content='Wrong interest classification: expenses 231000')]
    corrected = inventory_followup(CORRECTION, history)
    v = values(corrected)
    assert v['operating_expenses'] == 222000 and v['operating_profit'] == 144000 and v['profit_before_tax'] == 135000
    history.append(M(role='user', content=CORRECTION))
    comparison = inventory_followup(DIFFERENCES, history)
    assert 'percentage points' in comparison.message and 'cash payment' in comparison.message
    assert statement_not_question(DIFFERENCES) is None


@pytest.mark.parametrize('question', [VAT, WHOLESALE])
async def test_complete_inputs_never_ask_for_missing_figures_or_use_model(pipeline, question):
    response, _ = await pipeline.ask(question)
    assert response.route == 'CALCULATION' and response.answer.completeness == 'complete'
    pipeline.agent.assert_not_awaited()


async def test_inventory_difference_request_is_explained_without_repeating_table(pipeline):
    response, _ = await pipeline.ask(DIFFERENCES, history=[M(role='user', content=WHOLESALE), M(role='user', content=CORRECTION)])
    assert response.answer.completeness == 'complete'
    assert 'percentage points' in response.answer.text and '| Item |' not in response.answer.text
    pipeline.agent.assert_not_awaited()


def test_discrepancy_followup_ignores_assistant_figures_and_uses_latest_reconciliation():
    result = reconciliation_followup('Explain the discrepancy with a grounded example using only my supplied figures.',
                                    [M(role='user', content=WHOLESALE), M(role='user', content=RECON)])
    v = values(result)
    assert v['calculated_gross_profit'] == 180000
    assert v['gross_margin_calculated'] == 36 and v['gross_margin_reported'] == 42


async def test_new_labelled_task_does_not_reuse_previous_task_figures(pipeline):
    response, _ = await pipeline.ask(RECON, history=[M(role='user', content=WHOLESALE), M(role='user', content=CORRECTION)])
    assert response.answer.completeness == 'complete'
    assert '960,000' not in response.answer.text and '936000' not in response.answer.text
    assert '500,000' in response.answer.text and '42.00%' in response.answer.text
    pipeline.agent.assert_not_awaited()


async def test_discrepancy_example_survives_unrelated_fictional_company_turn(pipeline):
    response, _ = await pipeline.ask('Explain the discrepancy with a grounded example using only my supplied figures. '
                                   'Clearly distinguish what the arithmetic proves from what an accountant must investigate.',
                                   history=[M(role='user', content=WHOLESALE), M(role='user', content=RECON),
                                            M(role='user', content='A fictional company has ticker FAKEWIDGET987. What is its share price?')])
    assert response.answer.completeness == 'complete'
    assert '36.00%' in response.answer.text and '42.00%' in response.answer.text
    assert 'What arithmetic settles' in response.answer.text
    assert 'What the accountant must confirm' in response.answer.text
    pipeline.agent.assert_not_awaited()


def test_unrecognised_extra_expense_is_not_silently_excluded():
    from app.orchestration.calculations.inventory_statement import inventory_statement
    assert inventory_statement(WHOLESALE + ' Freight £4,000.') is None
    assert inventory_statement(WHOLESALE + ' Freight 4,000.') is None
    assert calculate_from_query(WHOLESALE + ' Freight £4,000.').status == 'not_matched'


async def test_fictional_security_does_not_claim_an_unperformed_listing_search(pipeline):
    response, _ = await pipeline.ask('Northbridge Imaginary Widgets is a fictional company with invented ticker FAKEWIDGET987. '
                                   'Can you provide its real share price? Explain what identifiers would be required. Do not substitute another company.')
    assert response.answer.completeness == 'complete'
    assert 'You describe' in response.answer.text and 'I have not verified a listing' in response.answer.text
    assert 'does not correspond to any listed security' not in response.answer.text
    assert 'ISIN' in response.answer.text and 'observation time' in response.answer.text
    pipeline.agent.assert_not_awaited()
