"""Separate sourced rates from locally verified hypothetical table arithmetic."""
import re
from decimal import Decimal, ROUND_HALF_UP

from app.orchestration.source_taxonomy import detect_jurisdictions


def split_tax_row(claim: str, answer: str, question: str):
    """Return (source claim, calculation error), or None for other row shapes.

    Only monetary cells, simple tax/total expressions and one tax-exclusive input are
    accepted. Ambiguous tables remain subject to normal full-claim checks.
    The rate itself must still pass the cited-source release verifier.
    """
    if not claim.startswith('|') or not re.search(r'\b(?:vat|gst)\b', question, re.I):
        return None
    if not re.search(r'tax[\s\-‑]exclusive', question, re.I):
        return None
    amounts = re.findall(r'\b(?:amount|price)\s+of\s+([\d,]+(?:\.\d+)?)', question, re.I)
    if len(amounts) != 1:
        return None
    base = Decimal(amounts[0].replace(',', ''))
    if base < 0:
        return None
    def row_cells(line):
        clean = re.sub(r'\[REF-\d+\]', '', line).strip()
        if clean.startswith('|'):
            clean = clean[1:]
        if clean.endswith('|'):
            clean = clean[:-1]
        return [re.sub(r'(?<=\d)[ \u00a0\u202f](?=\d{3}(?:\D|$))', '', cell.strip())
                for cell in clean.split('|')]
    cells = row_cells(claim)
    header = None
    for line in answer.splitlines():
        if line.strip().startswith('|'):
            possible = [cell.strip().lower() for cell in line.strip('| ').split('|')]
            if any(cell == 'country' for cell in possible):
                header = possible
            if row_cells(line) == cells:
                break
    if not header or len(cells) != len(header):
        return None
    def column(pattern):
        found = [i for i, name in enumerate(header) if re.search(pattern, name)]
        return found[0] if len(found) == 1 else None
    country_i, rate_i = column(r'^country$'), column(r'\brate\b')
    tax_i, total_i = column(r'^tax\b'), column(r'\btotal\b')
    if None in (country_i, rate_i, tax_i, total_i):
        return None
    country = cells[country_i]
    named = detect_jurisdictions(country)
    if len(named) != 1 or named[0] not in detect_jurisdictions(question):
        return None
    currency = {'UK': 'GBP', 'SINGAPORE': 'SGD', 'AUSTRALIA': 'AUD'}.get(named[0])
    if currency is None:
        return None
    rate_match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*%', cells[rate_i])
    if not rate_match:
        return None
    money = r'(?:GBP|SGD|AUD|INR|USD|EUR|CAD|NZD|ZAR|[£$₹€])?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:GBP|SGD|AUD|INR|USD|EUR|CAD|NZD|ZAR)?'
    rate = Decimal(rate_match.group(1))
    expected_tax = (base * rate / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    expected_total = (base + expected_tax).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    refs = ' '.join(dict.fromkeys(re.findall(r'\[REF-\d+\]', claim)))
    fact = f'{country}: standard VAT/GST rate is {rate}%. {refs}'
    def amount(cell, kind):
        expression = None
        if cell.count('=') == 1:
            expression, cell = (part.strip() for part in cell.split('='))
        else:
            parenthetical = re.fullmatch(r'(.+?)\s*\(([^()]+)\)', cell)
            if parenthetical:
                cell, expression = parenthetical.groups()
        match = re.fullmatch(money, cell.strip(), re.I)
        if not match:
            return None
        value = Decimal(match.group(1).replace(',', ''))
        if expression:
            operands = re.fullmatch(r'([\d,.]+)\s*([×x*+])\s*([\d,.]+)\s*(%)?', expression.strip())
            if not operands:
                return None
            left, right = (Decimal(operands.group(i).replace(',', '')) for i in (1, 3))
            operator, percent = operands.group(2), operands.group(4)
            correct = left == base and (
                (kind == 'tax' and operator in '×x*' and right == (rate if percent else rate / 100))
                or (kind == 'total' and operator == '+' and not percent and right == expected_tax)
            )
            if not correct:
                return 'invalid'
        return value
    tax, total = amount(cells[tax_i], 'tax'), amount(cells[total_i], 'total')
    if tax is None or total is None:
        return None
    symbols = {'UK': '£', 'SINGAPORE': '$', 'AUSTRALIA': '$'}
    for cell in (cells[tax_i], cells[total_i]):
        codes = re.findall(r'[A-Za-z]{3}', cell)
        if any(code.upper() != currency for code in codes) or any(symbol != symbols[named[0]] for symbol in re.findall(r'[£$₹€]', cell)):
            return fact, 'Tax table currency does not match the requested local currency'
    if rate > 100 or tax != expected_tax or total != expected_total:
        return fact, 'Tax table arithmetic does not match the supplied tax-exclusive price and rate'
    return fact, None
