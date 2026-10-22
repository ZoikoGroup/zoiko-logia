"""Period-scoped operating statements from explicitly labelled user inputs.

Never mix a current sales figure with a previous-period cost, and never use
an assistant's answer as an input. Unsupported shapes stay on the agent path.
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

from .schemas import CalculationInput, CalculationOutput, CalculationResult

_PERIOD = re.compile(r'\b(?:for\s+)?(?:the\s+)?(?P<period>current|previous|prior)[ -]year\s*:', re.I)
_VALUE = r'\s*:\s*(?P<symbol>[£$€₹])?\s*(?P<value>-?\d(?:[\d,]*\d)?(?:\.\d+)?)'
_EXPENSES = ('salaries', 'rent', 'utilities', 'marketing', 'depreciation')


def structured_operating_statement(query: str) -> CalculationResult | None:
    """Complete labelled single/two-period statements; never just a subtotal."""
    from .engine import _find_value, _money
    if not re.search(r'\b(?:operating profit|profit before tax|management report)\b', query, re.I):
        return None
    if re.search(r'\b(?:opening inventory|closing inventory|purchases|forecast|projected)\b', query, re.I):
        return None
    periods = list(_PERIOD.finditer(query))
    if periods and (len(periods) != 2 or periods[0]['period'].lower() != 'current'):
        return None
    sections = [('current_', query[periods[0].end():periods[1].start()]),
                ('previous_', query[periods[1].end():])] if periods else [('', query)]
    inputs, outputs, steps, notes = [], [], [], []
    currencies = set()
    computed = {}
    for prefix, text in sections:
        revenue = _find_value(text, ('revenue', 'gross sales'))
        cost = _find_value(text, ('cost of goods sold', 'cost of sales'))
        interest = _find_value(text, ('interest expense', 'interest'))
        aggregate = _find_value(text, ('total operating expenses', 'operating expenses'))
        components = [(name, _find_value(text, (name,))) for name in _EXPENSES]
        # An aggregate and component amounts together require a reconciliation,
        # not an assumption that the figures can be added or substituted.
        if not revenue or not cost or not interest or (aggregate and any(v for _, v in components)):
            return None
        if not aggregate and not all(dict(components)[n] for n in ('salaries','rent','utilities','depreciation')):
            return None
        returns = _find_value(text, ('sales returns',))
        supplied = [('revenue', revenue), ('cost_of_goods_sold', cost), ('finance_costs', interest)]
        supplied += [('sales_returns', returns)] if returns else []
        supplied += [('operating_expenses', aggregate)] if aggregate else [(n,v) for n,v in components if v]
        if len(re.findall(r'[£$€₹]\s*\d[\d,]*(?:\.\d+)?',text)) > len(supplied):
            return None
        for name, (number, currency) in supplied:
            if currency:
                currencies.add(currency)
            if number < 0:
                return None
            inputs.append(CalculationInput(name=prefix+name, value=number, currency=currency, kind='money', display_value=str(number)))
        if len(currencies) != 1:
            return None
        currency = next(iter(currencies))
        net = revenue[0] - (returns[0] if returns else Decimal(0))
        if net < 0:
            return None
        gross = net - cost[0]
        opex = aggregate[0] if aggregate else sum((v[0] for _,v in components if v), Decimal(0))
        operating = gross - opex
        result = {'net_sales':net, 'gross_profit':gross, 'operating_expenses':opex,
                  'operating_profit':operating, 'finance_costs':interest[0], 'profit_before_tax':operating-interest[0]}
        if net:
            result.update(gross_margin=gross/net*100, operating_margin=operating/net*100)
        computed[prefix] = result
        for name, number in result.items():
            percent = name.endswith('margin')
            outputs.append(CalculationOutput(name=prefix+name, value=number, kind='percentage' if percent else 'money',
                display_value=f'{number:.2f}%' if percent else _money(number,currency)))
        p = prefix.replace('_',' ').strip().title()
        operating_inputs = [aggregate[0]] if aggregate else [v[0] for _,v in components if v]
        steps += [f'{p} net sales = {_money(revenue[0],currency)} − {_money(returns[0] if returns else Decimal(0),currency)} = {_money(net,currency)}',
                  f'{p} gross profit = {_money(net,currency)} − {_money(cost[0],currency)} = {_money(gross,currency)}',
                  f'{p} operating expenses = ' + ' + '.join(_money(v,currency) for v in operating_inputs) + f' = {_money(opex,currency)}',
                  f'{p} operating profit = {_money(gross,currency)} − {_money(opex,currency)} = {_money(operating,currency)}',
                  f'{p} profit before tax = {_money(operating,currency)} − {_money(interest[0],currency)} = {_money(operating-interest[0],currency)}']
        if net:
            steps += [f'{p} gross margin = {gross} ÷ {net} × 100 = {gross/net*100:.2f}%',
                      f'{p} operating margin = {operating} ÷ {net} × 100 = {operating/net*100:.2f}%']
    if len(computed) == 2:
        current, previous = computed['current_'], computed['previous_']
        for name in ('gross_profit','operating_profit','profit_before_tax','gross_margin','operating_margin'):
            if name not in current or name not in previous:
                continue
            delta = current[name]-previous[name]
            margin = name.endswith('margin')
            outputs.append(CalculationOutput(name=name+'_change'+('_percentage_points' if margin else ''), value=delta,
                kind='number' if margin else 'money', display_value=f'{delta:.2f} percentage points' if margin else _money(delta,currency)))
            if not margin and previous[name] > 0:
                percent = delta/previous[name]*100
                outputs.append(CalculationOutput(name=name+'_change_percent',value=percent,kind='percentage',display_value=f'{percent:.2f}%'))
                steps.append(f'{name} percentage change = ({current[name]} − {previous[name]}) ÷ {previous[name]} × 100 = {percent:.2f}%')
    notes = ['Interest is deducted after operating profit. No tax has been calculated. The supplied figures do not establish business causes.']
    return CalculationResult(matched=True,status='success',formula_ids=['structured_operating_statement'],
        inputs=inputs,outputs=outputs,steps=steps,notes=notes,verification_status='passed')


def structured_statement_followup(query: str, history) -> CalculationResult | None:
    from .engine import _money
    pattern = r'^\s*(?:correct|change|set)\s+(?:only\s+)?(depreciation|rent|utilities|salaries|marketing)\s+to\s*([£$€₹])?\s*(\d[\d,]*(?:\.\d+)?)(?:[.!]|$)'
    change = re.match(pattern, query, re.I)
    if not change:
        return None
    baseline = None
    pending = []
    for message in reversed(history):
        if message.role != 'user':
            continue
        baseline = structured_operating_statement(message.content)
        if baseline:
            break
        prior_change = re.match(pattern,message.content,re.I)
        if prior_change:
            pending.insert(0,prior_change)
        else:
            return None
    if not baseline or any(i.name.startswith('current_') for i in baseline.inputs):
        return None
    currency = next(i.currency for i in baseline.inputs if i.currency)
    symbol = {'GBP':'£','USD':'$','EUR':'€','INR':'₹'}[currency]
    if change[2] and change[2] != symbol:
        return None
    supplied = {i.name:i.value for i in baseline.inputs}
    labels = {'cost_of_goods_sold':'cost of goods sold','finance_costs':'interest','sales_returns':'sales returns','operating_expenses':'operating expenses'}
    def calculate_active():
        return structured_operating_statement('. '.join(f'{labels.get(k,k)} {symbol}{v}' for k,v in supplied.items()) + '. Calculate operating profit and profit before tax.')
    for prior in pending:
        if prior[1].lower() not in supplied or (prior[2] and prior[2] != symbol):
            return None
        supplied[prior[1].lower()] = Decimal(prior[3].replace(',',''))
    baseline = calculate_active()
    replacement = Decimal(change[3].replace(',',''))
    if change[1].lower() not in supplied:
        return None
    supplied[change[1].lower()] = replacement
    revised = calculate_active()
    if not revised:
        return None
    revised.outputs = [CalculationOutput(name='original_'+o.name,value=o.value,display_value=o.display_value,kind=o.kind) for o in baseline.outputs] + revised.outputs
    for item in revised.inputs:
        item.source_location = 'query' if item.name == change[1].lower() else 'conversation_history'
    revised.notes += [f'Changed only {change[1].lower()} to {_money(replacement,currency)}. Original and corrected values are shown.',
                      'Gross margin is unchanged because sales, returns and cost of goods sold are unchanged. Operating margin changes because operating expenses changed.']
    return revised


def operating_statement(query: str) -> CalculationResult | None:
    """Recognise a full two-period statement, not an arbitrary word problem."""
    periods = list(_PERIOD.finditer(query))
    if len(periods) != 2 or {m['period'].lower() for m in periods} not in (
        {'current', 'previous'}, {'current', 'prior'},
    ):
        return None
    # A lookup or other independent request must still be handled by the agent.
    if re.search(r'\b(?:latest|search|retrieve|benchmark|industry|IFRS|IAS|tax rate|exchange rate|chart)\b', query, re.I):
        return None
    sections = {m['period'].lower(): query[m.end():periods[i + 1].start() if i + 1 < len(periods) else len(query)]
                for i, m in enumerate(periods)}
    current, previous = sections['current'], sections.get('previous', sections.get('prior'))
    currencies: set[str] = set()
    inputs = []

    def read(text, label, name):
        matches = list(re.finditer(r'(?<!\w)' + re.escape(label) + _VALUE, text, re.I))
        if len(matches) != 1:
            raise ValueError('missing or ambiguous labelled input')
        match = matches[0]
        if len(match['value']) > 30:
            raise ValueError('input exceeds supported decimal precision')
        value = Decimal(match['value'].replace(',', ''))
        if match['symbol']:
            currencies.add({'£': 'GBP', '$': 'USD', '€': 'EUR', '₹': 'INR'}[match['symbol']])
        inputs.append(CalculationInput(name=name, value=value, display_value=str(value), kind='money'))
        return value

    try:
        sales = read(current, 'gross sales', 'current_gross_sales')
        returns = read(current, 'sales returns', 'current_sales_returns')
        cost = read(current, 'cost of goods sold', 'current_cost_of_goods_sold')
        expenses = [read(current, label, 'current_' + label) for label in _EXPENSES]
        interest = read(current, 'interest expense', 'current_interest_expense')
        prior_sales = read(previous, 'net sales', 'previous_net_sales')
        prior_cost = read(previous, 'cost of goods sold', 'previous_cost_of_goods_sold')
        prior_expenses = read(previous, 'total operating expenses', 'previous_operating_expenses')
    except ValueError:
        return None
    if len(currencies) != 1:
        return None
    # Unrecognised additional monetary lines could change the expense total.
    # Accept precisely the supported labelled statement, otherwise defer.
    # "sections:\n1. Executive summary" is a numbered instruction, not an
    # additional monetary input. Keep rejecting actual unknown amount lines.
    labelled_amount = r'\b[A-Za-z][A-Za-z ]*:(?![ \t]*\r?\n[ \t]*\d+[.)](?:[ \t]|$))\s*[£$€₹]?\s*-?\d'
    if len(re.findall(labelled_amount, current)) != 9 or len(re.findall(labelled_amount, previous)) != 3:
        return None
    currency = next(iter(currencies))
    symbol = {'GBP': '£', 'USD': '$', 'EUR': '€', 'INR': '₹'}[currency]
    for item in inputs:
        item.currency = currency
    net = sales - returns
    gross = net - cost
    opex = sum(expenses, Decimal(0))
    operating = gross - opex
    prior_gross = prior_sales - prior_cost
    prior_operating = prior_gross - prior_expenses

    def money(value):
        return f'{symbol}{value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):,f}'

    outputs = []
    steps = []

    def add(name, value, formula, percent=False):
        shown = f'{value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):f}%' if percent else money(value)
        outputs.append(CalculationOutput(name=name, value=value, display_value=shown,
                                         kind='percentage' if percent else 'money'))
        steps.append(f'{name.replace("_", " ").capitalize()}: {formula} = {shown}')

    add('current_net_sales', net, f'{money(sales)} − {money(returns)}')
    add('current_gross_profit', gross, f'{money(net)} − {money(cost)}')
    if net:
        add('current_gross_margin', gross / net * 100, f'{money(gross)} ÷ {money(net)} × 100', True)
    add('current_operating_expenses', opex, ' + '.join(money(v) for v in expenses))
    add('current_operating_profit', operating, f'{money(gross)} − {money(opex)}')
    if net:
        add('current_operating_margin', operating / net * 100, f'{money(operating)} ÷ {money(net)} × 100', True)
    add('current_profit_before_tax', operating - interest, f'{money(operating)} − {money(interest)}')
    add('previous_gross_profit', prior_gross, f'{money(prior_sales)} − {money(prior_cost)}')
    add('previous_operating_profit', prior_operating, f'{money(prior_gross)} − {money(prior_expenses)}')
    for label, now, before in [('gross_profit', gross, prior_gross), ('operating_profit', operating, prior_operating)]:
        add(label + '_change', now - before, f'{money(now)} − {money(before)}')
        if before > 0:
            add(label + '_change_percent', (now - before) / before * 100,
                f'({money(now)} − {money(before)}) ÷ {money(before)} × 100', True)
    notes = [
        f'Net sales changed by {money(net - prior_sales)} and cost of goods sold by {money(cost - prior_cost)}; '
        f'together these explain the {money(gross - prior_gross)} change in gross profit.',
        f'Operating expenses changed by {money(opex - prior_expenses)}, leaving an operating-profit change '
        f'of {money(operating - prior_operating)}. Interest of {money(interest)} is deducted after operating profit.',
        'The figures show changes, but do not establish their business causes. Corporation tax has not been calculated.',
    ]
    if not net:
        notes.append('Gross margin and operating margin are undefined because current net sales are zero.')
    if prior_gross <= 0 or prior_operating <= 0:
        notes.append('Percentage growth is not shown for a zero or negative previous profit; the amount change is shown.')
    if re.search(r'\b(?:questions|investigate)\b', query, re.I):
        notes.extend([
            'Management question 1: What price, volume, returns and product-mix evidence explains the change in net sales?',
            'Management question 2: What purchasing, usage and production records explain the change in cost of goods sold?',
            'Management question 3: Which expense categories explain the change in total operating expenses, and how do they compare with budget?',
        ])
    return CalculationResult(matched=True, status='success', formula_ids=['operating_statement'],
                             inputs=inputs, outputs=outputs, steps=steps, notes=notes, verification_status='passed',
                             message='Calculated separately for each period from the labelled inputs supplied.')


_SCENARIO_CHANGE = re.compile(
    r'\bincrease\s+(?:(?:the\s+)?current[ -]year\s+)?(?P<label>gross sales|cost of goods sold)\s+by\s+'
    r'(?P<rate>\d+(?:\.\d+)?)\s*%', re.I,
)
_OTHER_REVISION = re.compile(
    r'\b(?:change|set|reduce|decrease|increase)\s+(?:the\s+)?(?:current[ -]year\s+)?'
    r'(?:gross sales|cost of goods sold|rent|salaries|returns|sales returns|interest|utilities|marketing|depreciation|expenses)\b',
    re.I,
)


def statement_followup(query: str, history) -> CalculationResult | None:
    """Explicit sales/COGS sensitivities, always based on original user data.

    Unsupported revisions remain with the agent; assistant replies, including
    failed replies, never supply the financial inputs.
    """
    changes = list(_SCENARIO_CHANGE.finditer(query))
    unsupported_revision = _OTHER_REVISION.search(_SCENARIO_CHANGE.sub('', query))
    if (not changes or unsupported_revision
            or re.search(r'\b(?:again|compound)\b', query, re.I)):
        return None
    users = [m.content for m in history if m.role == 'user']
    baseline = None
    baseline_index = -1
    for i in reversed(range(len(users))):
        candidate = operating_statement(users[i])
        if candidate is not None:
            baseline, baseline_index = candidate, i
            break
    if baseline is None:
        return None
    amounts = {i.value for i in baseline.inputs}
    if any(Decimal(raw.replace(',', '')) not in amounts
           for raw in re.findall(r'[£$€₹]\s*(-?\d[\d,]*(?:\.\d+)?)', query)):
        return None
    rates = {}
    for text in [*users[baseline_index + 1:], query]:
        if _OTHER_REVISION.search(_SCENARIO_CHANGE.sub('', text)):
            return None
        if text != query and len(re.findall(r'[£$€₹]\s*\d', text)) >= 2 and not _SCENARIO_CHANGE.search(text):
            # A new financial problem may have superseded this statement.
            return None
        for change in _SCENARIO_CHANGE.finditer(text):
            rates[change['label'].lower()] = Decimal(change['rate'])
    revised_query = users[baseline_index]
    # Replace just the original current-period label. The revised request's
    # unchanged returns/expenses and the prior-year comparison stay intact.
    steps = []
    for label, rate in rates.items():
        name = 'current_' + label.replace(' ', '_')
        source = next(i for i in baseline.inputs if i.name == name)
        revised = source.value * (1 + rate / 100)
        pattern = re.compile(r'(?<!\w)' + re.escape(label) + _VALUE, re.I)
        markers = list(_PERIOD.finditer(revised_query))
        index = next(i for i, m in enumerate(markers) if m['period'].lower() == 'current')
        start = markers[index].end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(revised_query)
        section = pattern.sub(lambda m: f'{label}: {m["symbol"] or ""}{revised:f}', revised_query[start:end], count=1)
        revised_query = revised_query[:start] + section + revised_query[end:]
        steps.append(f'Revised {label} = {source.value:f} × (1 + {rate:f} ÷ 100) = {revised:f}')
    revised_result = operating_statement(revised_query)
    if revised_result is None:
        return None
    wanted = {'current_net_sales', 'current_gross_profit', 'current_operating_profit', 'current_profit_before_tax'}
    outputs = []
    for prefix, result in [('original', baseline), ('revised', revised_result)]:
        outputs.extend(o.model_copy(update={'name': prefix + '_' + o.name.removeprefix('current_')})
                       for o in result.outputs if o.name in wanted)
    return CalculationResult(matched=True, status='success', formula_ids=['operating_statement_scenario'],
                             inputs=[i.model_copy(update={'source_location': 'conversation_history'}) for i in baseline.inputs],
                             outputs=outputs, steps=steps + revised_result.steps[:7], verification_status='passed',
                             notes=['Only the explicitly revised inputs changed. Earlier user figures were retained, even if the previous answer failed.',
                                    'This is a sensitivity calculation, not a prediction: unchanged costs and returns are assumptions. '
                                    'The supplied figures do not establish how volume, pricing, production capacity or costs would respond.'])
