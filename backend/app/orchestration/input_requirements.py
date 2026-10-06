"""Deterministic missing-input guards and bounded user-figure follow-ups."""
import re
from decimal import Decimal
from app.orchestration.calculation_service import _number_for_label, _REVENUE_LABEL


def expense_followup_query(query: str, history) -> str:
    change = re.search(r"\bincrease(?:d)?\s+(?:(?:those|the|my)\s+)?expenses\s+by\s+(\d+(?:\.\d+)?)\s*%", query, re.I)
    if not change or not re.search(r"\brevenue\s+(?:stays?\s+|remains?\s+)?unchanged\b", query, re.I):
        return query
    for message in reversed(history):
        if message.role != "user":
            continue
        revenue = _number_for_label(message.content, _REVENUE_LABEL)
        expenses = _number_for_label(message.content, r"expenses")
        if revenue is None or expenses is None:
            continue
        currencies = set(re.findall(r"[₹£$€]", message.content))
        if len(currencies) > 1:
            return query
        currency = next(iter(currencies), "")
        expenses *= 1 + Decimal(change.group(1)) / 100
        return f"Calculate profit and profit margin. Revenue is {currency}{revenue} and expenses are {currency}{expenses}."
    return query


def missing_tax_inputs(query: str) -> str | None:
    if re.search(r"\b(?:calculate|compute|work out)\b.*\b(?:company.?s?\s+tax|tax liability)\b", query, re.I) and not re.search(r"\d", query):
        return ("Please provide the tax jurisdiction, tax year or period, company type, taxable profit "
                "and relevant deductions or credits. If you want arithmetic only, provide the taxable amount and tax rate.")
    return None


def needs_invoice_attachment(query: str) -> bool:
    return bool(re.search(r"\b(?:invoice|subtotal)\b", query, re.I)
                and re.search(r"\b(?:extract|attached|uploaded|sample invoice)\b", query, re.I))


def gst_answer_gaps(query: str, answer: str) -> list[str]:
    """Detect obvious omissions; a statement of unchanged rates is not a value."""
    if not (re.search(r"\b(?:india|indian)\b", query, re.I) and re.search(r"\bgst\b", query, re.I)):
        return []
    gaps = []
    if re.search(r"\bregistration\b", query, re.I):
        value = re.search(r"(?:₹|rs\.?|inr)\s*[\d,]+|\d[\d,.]*\s*(?:lakh|lac|crore)", answer, re.I)
        threshold_gap = re.search(r"(?:sources?|evidence)[^.]*\b(?:not|missing|unavailable)\b[^.]*\bthreshold", answer, re.I)
        if not value and not threshold_gap:
            gaps.append("applicable goods/services turnover thresholds and state-dependent conditions")
    return gaps
