"""Inventory-based statements and explicit closing-inventory corrections."""
import re
from decimal import Decimal

from .schemas import CalculationInput, CalculationOutput, CalculationResult

LABELS = ('revenue', 'sales returns', 'opening inventory', 'purchases', 'closing inventory',
          'salaries', 'wages', 'rent', 'utilities', 'depreciation', 'marketing', 'insurance', 'interest')
AMOUNT = r'(?P<symbol>[£$€₹])?\s*(?P<amount>-?\d(?:[\d,]*\d)?(?:\.\d+)?)'


def inventory_statement(query):
    if not all(re.search(r'\b' + label + r'\b', query, re.I)
               for label in ('opening inventory', 'closing inventory', 'purchases')):
        return None
    # Independent live rules and additional unknown monetary inputs must
    # continue through composition rather than receiving an incomplete table.
    if re.search(r'\b(?:retrieve|latest|benchmark|exchange rate|tax rate)\b', query, re.I):
        return None
    inputs, spans, currencies = [], [], set()
    for label in LABELS:
        pattern = r'(?:sales returns|(?<!purchase )(?<!sales )returns)' if label == 'sales returns' else label
        matches = list(re.finditer(r'\b' + pattern + r'\b\s*(?:is|are|was|were|of|:|=)?\s*' + AMOUNT, query, re.I))
        if len(matches) > 1:
            return None
        if matches:
            match = matches[0]
            if label == 'sales returns' and match.group(0).lower().startswith('returns'):
                preceding = re.findall(r'\b(revenue|sales|purchases|opening inventory|closing inventory)\b',
                                       query[:match.start()], re.I)
                if not preceding or preceding[-1].lower() not in {'revenue', 'sales'}:
                    return None  # Unqualified returns cannot be assigned across purchase inputs.
            if len(match['amount']) > 30:
                return None
            value = Decimal(match['amount'].replace(',', ''))
            if value < 0:
                return None
            if match['symbol']:
                currencies.add({'£': 'GBP', '$': 'USD', '€': 'EUR', '₹': 'INR'}[match['symbol']])
            inputs.append(CalculationInput(name=label.replace(' ', '_'), value=value,
                                          display_value=str(value), kind='money'))
            spans.append(match.span())
    declared = re.search(r'all (?:figures|amounts)\s+(?:are|in|are in)\s+(GBP|USD|EUR|INR)\b', query, re.I)
    if declared:
        currencies.add(declared[1].upper())
    if len(currencies) != 1:
        return None
    masked = list(query)
    for start, end in spans:
        masked[start:end] = ' ' * (end - start)
    if re.search(r'[£$€₹]\s*\d|\b[A-Za-z][A-Za-z ]{0,35}\s+(?:is\s+|are\s+)?\d[\d,]*(?:\.\d+)?\b', ''.join(masked)):
        return None
    values = {item.name: item.value for item in inputs}
    if not {'revenue', 'opening_inventory', 'closing_inventory', 'purchases'} <= values.keys():
        return None
    for label in ('sales_returns', 'interest'):
        if re.search(r'\b' + label.replace('_', ' ') + r'\b', query, re.I) and label not in values:
            return None
    if (not any(name in values for name in ('salaries', 'wages', 'rent', 'utilities', 'depreciation', 'marketing', 'insurance'))
            and re.search(r'\b(?:operating profit|operating expenses|profit before tax)\b', query, re.I)):
        return None  # No invented zero operating-expense assumption.
    currency = next(iter(currencies))
    for item in inputs:
        item.currency = currency
    return _render(inputs, currency)


def _render(inputs, currency):
    from .engine import _money, _percent
    v = {item.name: item.value for item in inputs}
    net = v['revenue'] - v.get('sales_returns', 0)
    cost = v['opening_inventory'] + v['purchases'] - v['closing_inventory']
    if net <= 0 or cost < 0:
        return None
    expenses = [item for item in inputs if item.name in {'salaries', 'wages', 'rent', 'utilities', 'depreciation', 'marketing', 'insurance'}]
    opex = sum((item.value for item in expenses), Decimal(0))
    gross, operating = net - cost, net - cost - opex
    outputs, steps = [], []

    def add(name, value, formula, percentage=False):
        shown = _percent(value) if percentage else _money(value, currency)
        outputs.append(CalculationOutput(name=name, value=value, display_value=shown,
                                         kind='percentage' if percentage else 'money'))
        steps.append(f'{name.replace("_", " ").capitalize()} = {formula} = {shown}')

    money = lambda value: _money(Decimal(value), currency)
    add('net_sales', net, f'{money(v["revenue"])} − {money(v.get("sales_returns", 0))}')
    add('cost_of_goods_sold', cost, f'{money(v["opening_inventory"])} + {money(v["purchases"])} − {money(v["closing_inventory"])}')
    add('gross_profit', gross, f'{money(net)} − {money(cost)}')
    add('gross_margin', gross / net * 100, f'{money(gross)} ÷ {money(net)} × 100', True)
    if expenses:
        add('operating_expenses', opex, ' + '.join(money(item.value) for item in expenses))
        add('operating_profit', operating, f'{money(gross)} − {money(opex)}')
        if 'interest' in v:
            add('finance_costs', v['interest'], money(v['interest']))
        add('profit_before_tax', operating - v.get('interest', 0), f'{money(operating)} − {money(v.get("interest", 0))} interest')
    return CalculationResult(matched=True, status='success', formula_ids=['inventory_operating_statement'],
                             inputs=inputs, outputs=outputs, steps=steps, verification_status='passed', notes=[
        'Interest is a finance expense deducted after operating profit; it is not included in operating expenses.',
        'Inventory is an asset held for sale. Cost of goods sold is the expense recognised as inventory is sold. '
        'A cash payment is a separate cash outflow: the purchase figures do not establish when suppliers were paid.',
        'Management question: do stock counts, purchase records and inventory valuation support the closing balance?',
        'Management question: what do receivables, supplier payment terms and cash records show about working capital?',
    ])


def _inventory_revision(text):
    adjustment = re.search(r'closing inventory\s+(?:was\s+)?(overstated|understated)\s+by\s*([£$€₹])?\s*(\d[\d,]*(?:\.\d+)?)', text, re.I)
    if adjustment:
        amount = Decimal(adjustment[3].replace(',', ''))
        return ('delta', -amount if adjustment[1].lower() == 'overstated' else amount, None, adjustment[2])
    replacement = re.search(r'closing inventory\s+(?:from\s*([£$€₹])?\s*(\d[\d,]*(?:\.\d+)?)\s+)?to\s*([£$€₹])?\s*(\d[\d,]*(?:\.\d+)?)', text, re.I)
    if replacement:
        symbols = {symbol for symbol in (replacement[1], replacement[3]) if symbol}
        if len(symbols) > 1:
            return None
        return ('replace', Decimal(replacement[4].replace(',', '')),
                Decimal(replacement[2].replace(',', '')) if replacement[2] else None,
                next(iter(symbols), None))
    return None


def inventory_followup(query, history):
    correction = _inventory_revision(query)
    comparison = bool(re.search(r'\b(?:differences?|compare|comparison)\b', query, re.I)
                      and re.search(r'\b(?:original|corrected|correction)\b', query, re.I))
    if not correction and not comparison:
        return None
    baseline, revision_texts = None, []
    for message in reversed(history or []):
        if getattr(message, 'role', '') != 'user':
            continue
        text = message.content
        revision = _inventory_revision(text)
        if revision:
            revision_texts.insert(0, text)
            continue
        if len(re.findall(r'[£$€₹]\s*\d', text)) >= 2:
            baseline = inventory_statement(text)
            break
    if baseline is None:
        return None
    if correction:
        revision_texts.append(query)
    if not revision_texts:
        return None
    inputs = [item.model_copy(update={'source_location': 'conversation_history'}) for item in baseline.inputs]
    original_closing = next(item.value for item in inputs if item.name == 'closing_inventory')
    for revision_text in revision_texts:
        revision = _inventory_revision(revision_text)
        if revision is None:
            return None
        operation, value, expected_old, symbol = revision
        if symbol and {'£': 'GBP', '$': 'USD', '€': 'EUR', '₹': 'INR'}[symbol] != inputs[0].currency:
            return None
        current_closing = next(item.value for item in inputs if item.name == 'closing_inventory')
        if expected_old is not None and expected_old != current_closing:
            return CalculationResult(matched=True, status='clarification_required', error_code='AMBIGUOUS_INPUTS',
                                     message='The stated starting closing inventory differs from the active task. Which version should be changed?')
        updated = current_closing + value if operation == 'delta' else value
        inputs = [item.model_copy(update={
            'value': updated,
            'display_value': str(updated),
            'source_location': 'query' if correction and revision_text is query else 'conversation_history',
        }) if item.name == 'closing_inventory' else item for item in inputs]
    closing = next(item.value for item in inputs if item.name == 'closing_inventory')
    if closing < 0:
        return None
    delta = closing - original_closing
    amount = abs(delta)
    currency = inputs[0].currency
    result = _render(inputs, currency)
    if result is None:
        return None
    from .engine import _money, _percent
    old, new = ({item.name: item.value for item in r.outputs} for r in (baseline, result))
    change = new['gross_margin'] - old['gross_margin']
    verb = 'falls' if delta < 0 else 'rises'
    notes = [f'Closing inventory {verb} by {_money(amount, currency)}. Cost of goods sold moves in the opposite direction; '
             f'gross profit, operating profit and profit before tax each {verb} by {_money(amount, currency)}.',
             f'Gross margin changes from {_percent(old["gross_margin"])} to {_percent(new["gross_margin"])} '
             f'({change:+.2f} percentage points); it is not a currency amount.',
             'The correction does not by itself establish a cash payment or change in cash. '
             'No other supplied expense changed.']
    result.notes = notes + result.notes
    if comparison:
        result.formula_ids = ['inventory_statement_comparison']
        result.message = ' '.join(notes)
    return result


def reconciliation_followup(query, history):
    if not re.search(r'\b(?:discrepancy|reconciliation|inconsistency)\b', query, re.I):
        return None
    if re.search(r'[£$€₹]\s*\d', query):
        return None
    from .engine import reconcile_reported_figures
    for message in reversed(history or []):
        if getattr(message, 'role', '') != 'user':
            continue
        if len(re.findall(r'[£$€₹]\s*\d', message.content)) >= 2:
            result = reconcile_reported_figures(message.content)
            if result is not None and result.status == 'success':
                result.formula_ids = [*result.formula_ids, 'reconciliation_explanation']
                for item in result.inputs:
                    item.source_location = 'conversation_history'
                return result
            return None
    return None
