"""Small explanations grounded exclusively in verified calculation inputs."""
import re

from app.orchestration.calculations.engine import _money


def verified_example(query, result) -> str:
    if not re.search(r'^\s*(?:explain|show|give|illustrate)\b[^.!?]{0,120}\bexample\b', query or '', re.I):
        return ''
    if result.status != 'success' or result.verification_status != 'passed':
        return ''
    inputs = {item.name: item for item in result.inputs}
    outputs = {item.name: item for item in result.outputs}
    if not {'revenue', 'cost_of_sales'} <= inputs.keys() or not {'gross_profit', 'gross_margin'} <= outputs.keys():
        return ''
    revenue, costs = inputs['revenue'], inputs['cost_of_sales']
    profit, margin = outputs['gross_profit'], outputs['gross_margin']
    if any(item.value is None for item in (revenue, costs, profit, margin)):
        return ''
    if revenue.value <= 0 or costs.value < 0 or profit.value < 0 or revenue.currency != costs.currency:
        return ''
    # Reuse verified display values, with no fresh numbers or causal claims.
    explanation = (
        '\n\n### Grounded example using your figures\n\n'
        f'Your example business earns {_money(revenue.value, revenue.currency)} in revenue and incurs '
        f'{_money(costs.value, costs.currency)} in cost of goods sold. This leaves {profit.display_value} '
        f'of gross profit before other expenses. Its {margin.display_value} gross margin '
        'is the share of revenue remaining after cost of goods sold; it does not establish '
        'net profit or cash available.'
    )
    if re.search(r'\b(?:exchange rate|share price)\b', query, re.I):
        explanation += (' An exchange rate or share price is a separate market observation '
                        'and cannot be inferred from these accounting figures.')
    return explanation


def verified_comparison(query, result) -> str:
    if not re.search(r'^\s*(?:highlight|explain|summari[sz]e|outline|identify|compare)\b[^.!?]{0,160}'
                     r'\b(?:differences?|comparison)\b', query or '', re.I):
        return ''
    # Reuse the same verification and input guards as the worked explanation.
    if not verified_example('Explain this with a grounded example.', result):
        return ''
    values = {item.name: item for item in result.outputs}
    text = ('\n\n### Most important differences\n\n'
            f'- Gross profit ({values["gross_profit"].display_value}) is an amount: revenue less cost of goods sold.\n'
            f'- Gross margin ({values["gross_margin"].display_value}) is that gross profit as a percentage of revenue.\n')
    if re.search(r'\bexchange rate\b', query, re.I):
        text += ('- An exchange rate is a dated observation for a currency pair, requiring a source; '
                 'it cannot be inferred from the profit calculation.\n')
    if re.search(r'\bshare price\b', query, re.I):
        text += ('- A share price concerns an identified security and a dated market quote; '
                 'it cannot be inferred from these business figures.\n')
        if re.search(r'\bfictional\b', query, re.I):
            text += '- The company is described as fictional; the supplied example does not establish a real quoted share price.\n'
    return text
