"""Latest-rate requirements and arithmetic using structured FX evidence."""
import re
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.orchestration.frankfurter import _find_currencies


_NAMED_DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b", re.I,
)
_NEGATED_LATEST = re.compile(r"\b(?:do\s+not|don'?t|never|not)\s+(?:use\s+)?(?:the\s+)?(?:latest|current|today'?s?|newest)\b", re.I)


def latest_fx_requested(question):
    """"Convert at the latest rate". Not "the rate for 31 December 2024. Do
    not use today's rate": the word "today" made that a latest-rate request,
    and the dated rate the user asked for was refused as stale."""
    if _NAMED_DATE.search(question) or _NEGATED_LATEST.search(question):
        return False
    # "latest/current" must qualify an exchange rate or a conversion: "Current
    # assets ₹2,50,000 … Total liabilities £300,000" named two currencies and
    # the word "current", and nine ratio answers were replaced with "no
    # sufficiently recent exchange rate".
    text = re.sub(r'\bcurrent\s+(?:assets|liabilities|ratio|value|and\s+quick\s+ratio)\b', '', question, flags=re.I)
    return (len(_find_currencies(question)) >= 2
            and bool(re.search(r"\b(?:latest|current|today'?s?|newest|live)\b", text, re.I))
            and bool(re.search(r'\b(?:rates?|convert|conversion|exchange|fx)\b', text, re.I)))


def fresh_fx_sources(question, sources, today=None):
    today = today or datetime.now(timezone.utc).date()
    currencies = _find_currencies(question)
    valid = []
    for source in sources:
        observation = source.observation
        if not observation or source.freshness != 'daily':
            continue
        pairs = (f'{currencies[0]}/{currencies[1]}', f'{currencies[1]}/{currencies[0]}') if len(currencies) >= 2 else ()
        if not any(observation.indicator == f'{pair} exchange rate' for pair in pairs):
            continue
        try:
            reference_date = date.fromisoformat(observation.period)
            rate = Decimal(str(observation.value))
        except (ValueError, TypeError, ArithmeticError):
            continue
        if 0 <= (today-reference_date).days <= 7 and rate.is_finite() and rate > 0:
            valid.append(source)
    return valid


def grounded_fx_profit(question, sources, citations, today=None):
    if not latest_fx_requested(question) or not re.search(r'\bprofit\b', question, re.I):
        return None
    # Keep this calculation family narrow; other currencies/shapes use the agent.
    if set(_find_currencies(question)[:2]) != {'USD', 'INR'}:
        return None
    revenue = re.search(r'\brevenue\s+(?:is\s+)?₹\s*([\d,]+(?:\.\d+)?)', question, re.I)
    expenses = re.findall(r'(?:US\$|USD\s*|\$)\s*([\d,]+(?:\.\d+)?)', question, re.I)
    if not revenue or len(expenses) != 1:
        return None
    revenue_value, expense_value = Decimal(revenue.group(1).replace(',', '')), Decimal(expenses[0].replace(',', ''))
    if revenue_value <= 0:
        return None
    today = today or datetime.now(timezone.utc).date()
    for source in fresh_fx_sources(question, sources, today):
        if source.observation.indicator != 'USD/INR exchange rate':
            continue
        citation = next((c for c in citations if c.url == source.url), None)
        if citation is None:
            continue
        rate = Decimal(str(source.observation.value))
        converted = (expense_value*rate).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        profit = revenue_value-converted
        margin = profit/revenue_value*100
        ref = f'[{citation.ref_id}]'
        note = ('The provider’s latest endpoint returned a reference date earlier than the request date. '
                'The provider did not return a reason for the publication gap; '
                'a weekend, holiday or delayed update cannot be confirmed.'
                if source.observation.period != today.isoformat() else 'The reference date matches the request date.')
        return (
            f'Latest retrieved USD/INR rate: 1 USD = {rate} INR; reference date {source.observation.period}. '
            f'Provider: {source.provider}. {ref}\n\n'
            f'Calculation assumption: the US${expense_value:,.2f} amount represents expenses and revenue is ₹{revenue_value:,.2f}:\n\n'
            f'Converted expenses = {expense_value} × {rate} = ₹{converted:,.2f}\n'
            f'Profit = ₹{revenue_value:,.2f} − ₹{converted:,.2f} = ₹{profit:,.2f}\n'
            f'Profit margin = {profit} ÷ {revenue_value} × 100 = {margin:.2f}%\n\n'
            f'Request date (UTC): {today.isoformat()}. Reference-date note: {note}'
        )
    return None
