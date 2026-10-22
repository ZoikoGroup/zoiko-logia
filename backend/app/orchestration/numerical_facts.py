"""Typed identity for verified calculation values, without model extraction."""
from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class NumericalFact(BaseModel):
    model_config = ConfigDict(frozen=True)
    fact_id: str
    query_id: str
    name: str
    metric: str
    value: Decimal
    kind: str
    currency: str | None = None
    period: Literal['current', 'previous'] | None = None
    scenario: Literal['original', 'revised'] | None = None
    source: Literal['user', 'calculation']


def calculation_facts(result, query_id: str) -> list[NumericalFact]:
    if result is None or result.status != 'success' or result.verification_status != 'passed':
        return []
    currencies = {i.currency for i in result.inputs if i.currency}
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    facts = []
    statement_family = result.formula_ids in (['operating_statement'], ['operating_statement_scenario'])
    for source, items in [('user', result.inputs), ('calculation', result.outputs)]:
        for index, item in enumerate(items):
            if item.value is None:
                continue
            metric = item.name
            scenario, period = None, None
            for prefix in ('original', 'revised'):
                if statement_family and metric.startswith(prefix + '_'):
                    scenario, metric = prefix, metric[len(prefix) + 1:]
                    if result.formula_ids == ['operating_statement_scenario']:
                        period = 'current'
                    break
            for prefix in ('current', 'previous', 'prior'):
                if statement_family and metric.startswith(prefix + '_'):
                    period, metric = ('previous' if prefix == 'prior' else prefix), metric[len(prefix) + 1:]
                    break
            fact_currency = (getattr(item, 'currency', None) or currency) if item.kind == 'money' else None
            identifier = hashlib.sha256(f'{query_id}:{source}:{index}:{item.name}'.encode()).hexdigest()[:24]
            facts.append(NumericalFact(fact_id=identifier, query_id=query_id, name=item.name,
                                       metric=metric, value=item.value, kind=item.kind, currency=fact_currency,
                                       period=period, scenario=scenario, source=source))
    return facts


def mislabelled_calculation_rows(text: str, result) -> list[tuple[str, str, str]]:
    """Conclusive mismatches for known table metrics and explicit contexts.

    Ambiguous labels, multi-number workings and unlabelled contexts are left
    to the existing equation/citation checks rather than guessed here.
    """
    import re
    from app.orchestration.figure_reconciliation import material_figures, _amount
    facts = [f for f in calculation_facts(result, 'release') if f.source == 'calculation']
    if not facts:
        return []

    def context(label):
        lowered = label.lower().replace('-', ' ').replace('‑', ' ')
        values = {}
        for words, key, value in [('current|this year', 'period', 'current'),
                                  ('previous|prior|last year', 'period', 'previous'),
                                  ('original|baseline', 'scenario', 'original'),
                                  ('revised|adjusted', 'scenario', 'revised')]:
            if re.search(r'\b(?:' + words + r')\b', lowered):
                values[key] = value
        return values

    def metric(label):
        label = label.lower().replace('_', ' ').replace('-', ' ').replace('‑', ' ')
        label = re.sub(r'\b(?:current|previous|prior|original|revised|baseline|adjusted|year|total|calculated)\b', ' ', label)
        return ' '.join(re.findall(r'[a-z]+', label))

    headers = []
    wrong = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith('|'):
            headers = []
            continue
        if set(stripped) <= set('|-: '):
            continue
        cells = [c.strip() for c in stripped.strip('|').split('|')]
        if not material_figures(stripped):
            headers = cells
            continue
        if not headers or not cells:
            continue
        for index in range(1, min(len(cells), len(headers))):
            if re.search(r'\breported\b', headers[index] + ' ' + cells[0], re.I):
                continue
            scope = {**context(cells[0]), **context(headers[index])}
            if not scope:
                continue
            candidates = [f for f in facts if metric(f.metric) == metric(cells[0])
                          and all(getattr(f, k) == v for k, v in scope.items())]
            figures = material_figures(cells[index])
            if len(candidates) != 1 or len(figures) != 1:
                continue
            fact = candidates[0]
            shown, number = figures[0]
            value = _amount(shown, number)
            currency = next((code for symbol, code in [('£', 'GBP'), ('$', 'USD'), ('€', 'EUR'), ('₹', 'INR')]
                             if symbol in shown), None)
            header_currency = re.search(r'\b(?:GBP|USD|EUR|INR)\b', headers[index], re.I)
            currencies = [c for c in (currency, header_currency[0].upper() if header_currency else None) if c]
            wrong_currency = fact.kind == 'money' and fact.currency and any(c != fact.currency for c in currencies)
            wrong_unit = ((fact.kind == 'money' and '%' in shown)
                          or (fact.kind == 'percentage' and currency is not None))
            token = re.search(r'\d[\d,]*(?:\.(\d+))?', shown)
            decimals = len(token[1] or '') if token else 0
            # Whole pounds have half-pound display precision; trailing zeroes
            # alone never authorize rounding a result to the nearest thousand.
            scale = Decimal(str(abs(_amount(shown, 1.0))))
            tolerance = Decimal('0.5') * Decimal(10) ** -decimals * scale + Decimal('0.000000001')
            if wrong_currency or wrong_unit or abs(fact.value - Decimal(str(value))) > tolerance:
                reason = f'{shown} does not match the verified {fact.name.replace("_", " ")} ({fact.value} {fact.currency or fact.kind}).'
                wrong.append((stripped, shown, reason))
    return wrong
