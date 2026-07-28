"""
Query-parsing helpers for extracting a plain arithmetic expression from raw
query text — feeds router.py's expression-evaluator path with a real
expression instead of the LLM computing the answer on its own. Mirrors
household_extraction.py's fail-closed contract exactly: a query this module
can't confidently resolve to a single, unambiguous expression returns None,
never a guess. None means "let this fall through to normal composition,"
not "there is no arithmetic here."

Deliberately narrow — covers the query shapes this codebase has actually
seen trigger the problem this module exists to solve (revenue-minus-expenses
profit questions, sales-tax-on-a-purchase questions), not a general
natural-language-to-arithmetic parser. Extend the pattern list as new
confidently-parseable shapes are found, the same incremental way
prescreen.py's and risk_classifier.py's pattern banks already grow.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

_DOLLAR = r"\$\s?([\d,]+(?:\.\d+)?)"
_PERCENT = r"([\d.]+)\s?%"

# "If revenue is $250,000 and expenses are $180,000, what is the net profit?"
_REVENUE_EXPENSES_PROFIT_PATTERN = re.compile(
    r"revenue\s+(?:is|of)\s+" + _DOLLAR + r".{0,40}?"
    r"expenses?\s+(?:is|are|of)\s+" + _DOLLAR + r".{0,60}?"
    r"(?:net\s+)?profit",
    re.IGNORECASE | re.DOTALL,
)

# "Calculate the sales tax on a $1,200 purchase at a 7.25% rate."
_SALES_TAX_PATTERN = re.compile(
    r"sales\s+tax\s+on\s+(?:a\s+)?" + _DOLLAR + r".{0,40}?" + _PERCENT,
    re.IGNORECASE | re.DOTALL,
)

# "$250,000 minus $180,000" / "$250,000 - $180,000"
_DOLLAR_MINUS_DOLLAR_PATTERN = re.compile(
    _DOLLAR + r"\s*(?:minus|-)\s*" + _DOLLAR, re.IGNORECASE,
)

# "$250,000 plus $180,000" / "$250,000 + $180,000"
_DOLLAR_PLUS_DOLLAR_PATTERN = re.compile(
    _DOLLAR + r"\s*(?:plus|\+)\s*" + _DOLLAR, re.IGNORECASE,
)


def _clean(raw: str) -> str:
    return raw.replace(",", "")


def _valid_decimal(raw: str) -> Optional[str]:
    try:
        Decimal(raw)
    except InvalidOperation:
        return None
    return raw


def extract_arithmetic_expression(query: str) -> Optional[str]:
    """Returns a ready-to-evaluate expression string ("250000 - 180000")
    when the query unambiguously names the shape of a plain two-figure
    arithmetic question this module recognizes, or None otherwise. Never
    guesses which two numbers in a longer query are the relevant ones —
    if more than one candidate pattern could plausibly apply, or a pattern
    matches more than once, this returns None rather than picking one."""
    match = _REVENUE_EXPENSES_PROFIT_PATTERN.search(query)
    if match:
        revenue = _valid_decimal(_clean(match.group(1)))
        expenses = _valid_decimal(_clean(match.group(2)))
        if revenue and expenses:
            return f"{revenue} - {expenses}"
        return None

    match = _SALES_TAX_PATTERN.search(query)
    if match:
        amount = _valid_decimal(_clean(match.group(1)))
        rate = _valid_decimal(match.group(2))
        if amount and rate:
            return f"{amount} * ({rate} / 100)"
        return None

    minus_matches = list(_DOLLAR_MINUS_DOLLAR_PATTERN.finditer(query))
    if len(minus_matches) == 1:
        a = _valid_decimal(_clean(minus_matches[0].group(1)))
        b = _valid_decimal(_clean(minus_matches[0].group(2)))
        if a and b:
            return f"{a} - {b}"
        return None

    plus_matches = list(_DOLLAR_PLUS_DOLLAR_PATTERN.finditer(query))
    if len(plus_matches) == 1:
        a = _valid_decimal(_clean(plus_matches[0].group(1)))
        b = _valid_decimal(_clean(plus_matches[0].group(2)))
        if a and b:
            return f"{a} + {b}"
        return None

    return None
