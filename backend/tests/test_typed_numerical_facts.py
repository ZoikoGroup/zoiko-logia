from app.orchestration.calculations.engine import calculate_from_query, calculation_markdown
from app.orchestration.calculations.statements import statement_followup
from app.orchestration.numerical_facts import calculation_facts, mislabelled_calculation_rows
from app.orchestration.schemas import ConversationMessage as M
from tests.test_agent_request_size import QUESTION


def test_correct_statement_results_pass_typed_verification():
    result = calculate_from_query(QUESTION)
    assert not mislabelled_calculation_rows(calculation_markdown(result), result)


def test_correct_number_used_for_the_wrong_metric_is_rejected():
    answer = '| Metric | Current year | Previous year |\n| --- | --- | --- |\n| Gross profit | £191,000 | £440,000 |'
    wrong = mislabelled_calculation_rows(answer, calculate_from_query(QUESTION))
    assert len(wrong) == 1
    assert wrong[0][1] == '£191,000'


def test_current_and_previous_figures_cannot_be_swapped():
    answer = '| Metric | Current year | Previous year |\n| --- | --- | --- |\n| Gross profit | £440,000 | £505,000 |'
    assert len(mislabelled_calculation_rows(answer, calculate_from_query(QUESTION))) == 2


def test_currency_is_part_of_the_verified_fact():
    answer = '| Metric | Current year |\n| --- | --- |\n| Gross profit | $505,000 |'
    assert mislabelled_calculation_rows(answer, calculate_from_query(QUESTION))
    assert mislabelled_calculation_rows(answer.replace('$505,000', '505,000').replace('Current year', 'Current year (USD)'), calculate_from_query(QUESTION))


def test_money_cannot_be_relabelled_as_a_percentage():
    answer = '| Metric | Current year |\n| --- | --- |\n| Gross profit | 505,000% |'
    assert mislabelled_calculation_rows(answer, calculate_from_query(QUESTION))


def test_trailing_zeroes_do_not_silently_change_the_money_rounding_precision():
    result = calculate_from_query(QUESTION.replace('Salaries: £165,000', 'Salaries: £165,050'))
    answer = '| Metric | Current year |\n| --- | --- |\n| Operating expenses | £314,000 |'
    assert mislabelled_calculation_rows(answer, result)
    assert not mislabelled_calculation_rows(answer.replace('314,000', '314,050'), result)


def test_scenario_columns_have_explicit_identity():
    result = statement_followup('Increase gross sales by 8%.', [M(role='user', content=QUESTION)])
    assert not mislabelled_calculation_rows(calculation_markdown(result), result)
    answer = '| Metric | Original | Revised |\n| --- | --- | --- |\n| Operating profit | £291,000 | £191,000 |'
    assert len(mislabelled_calculation_rows(answer, result)) == 2


def test_reported_inputs_are_not_silently_overwritten_by_calculated_results():
    answer = '| Metric | Reported current year |\n| --- | --- |\n| Gross profit | £410,000 |'
    assert not mislabelled_calculation_rows(answer, calculate_from_query(QUESTION))


def test_current_ratio_is_a_metric_not_a_period():
    facts = calculation_facts(calculate_from_query('Current assets £100,000, current liabilities £50,000. Calculate current ratio.'), 'q')
    ratio = next(f for f in facts if f.name == 'current_ratio')
    assert ratio.metric == 'current_ratio' and ratio.period is None
