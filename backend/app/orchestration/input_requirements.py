"""Deterministic missing-input guards and bounded user-figure follow-ups."""
import re
from decimal import Decimal
from app.orchestration.calculation_service import _number_for_label, _REVENUE_LABEL


def expense_followup_query(query: str, history) -> str:
    # Carry only explicitly supplied user inputs into bounded follow-ups.
    from app.orchestration.calculations.engine import expense_scenario, _input
    revised = expense_scenario(query)
    if revised and _input(query, "revenue") is None:
        for message in reversed(history):
            if message.role != "user":
                continue
            original = _input(message.content, "revenue")
            if original is None:
                continue
            revenue = original.value
            original_currency = original.currency
            revised_currency = revised.group("symbol") or revised.group("code") or original_currency or ""
            return (f"Calculate profit and profit margin. Revenue is {original_currency or ''} {revenue}; "
                    f"expenses are {revised_currency}{revised.group('amount')}.")
    if re.search(r"\bsame\b.*\brate\b", query, re.I) and not re.search(r"\d+(?:\.\d+)?\s*%", query):
        for message in reversed(history):
            if message.role != "user":
                continue
            rates = re.findall(r"(?<![\d.])[+\-−]?\s*\d+(?:\.\d+)?\s*%", message.content)
            if len(rates) == 1:
                return query + " Using the supplied rate " + rates[0] + "."
            if rates:
                break
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
    if (re.search(r"\b(?:register|registration)\b", query, re.I)
            and re.search(r"\bvat\b", query, re.I) and re.search(r"\b(?:my|our)\b", query, re.I)
            and not re.search(r"\b(?:uk|united kingdom|britain|ireland|uae|saudi|germany|france)\b", query, re.I)
            # A single-country currency or authority names the country: "My
            # sales were £87,000 … do I need to register for VAT?" is UK.
            and not re.search(r"£|\b(?:gbp|hmrc|pounds?|sterling|aed|dirhams?|sar|riyals?)\b", query, re.I)):
        return "Which country and currency apply? Please confirm the taxable turnover period and whether you expect to exceed the registration threshold soon."
    if re.search(r"\b(?:calculate|compute|work out)\b.*\b(?:company.?s?\s+tax|tax liability)\b", query, re.I) and not re.search(r"\d", query):
        return ("Please provide the tax jurisdiction, tax year or period, company type, taxable profit "
                "and relevant deductions or credits. If you want arithmetic only, provide the taxable amount and tax rate.")
    return None


def needs_invoice_attachment(query: str) -> bool:
    return bool(re.search(r"\b(?:invoice|subtotal)\b", query, re.I)
                and re.search(r"\b(?:extract|attached|uploaded|sample invoice)\b", query, re.I))


def gst_answer_gaps(query: str, answer: str) -> list[str]:
    """Detect obvious omissions; a statement of unchanged rates is not a value."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    if not ('INDIA' in detect_jurisdictions(query) and re.search(r"\bgst\b", query, re.I)):
        return []
    gaps = []
    if (re.search(r'\b(?:export|exports|us client|uk client|foreign|overseas)\b',query,re.I)
            and re.search(r'\b(?:charge|charging|zero|lut|treatment|taxable)\b',query,re.I)):
        if not re.search(r'zero[-‑ ]rated',answer,re.I):
            gaps.append('conditional zero-rating for qualifying exports of services')
        if not re.search(r'\b(?:if|provided|qualif\w*|conditions|subject to)\b',answer,re.I):
            gaps.append('export-of-services qualification conditions; a foreign client alone is insufficient')
        if not re.search(r'\b(?:LUT|letter of undertaking|bond)\b',answer,re.I):
            gaps.append('LUT/bond conditions for export without payment of IGST')
    if re.search(r"\bregistration\b", query, re.I):
        if not re.search(r"\b(?:goods|services)\b", query, re.I):
            value = re.search(r"(?:₹|rs\.?|inr)\s*[\d,]+|\d[\d,.]*\s*(?:lakh|lac|crore)", answer, re.I)
            gap = re.search(r"(?:sources?|evidence)[^.]*\b(?:not|missing|unavailable)\b[^.]*\bthreshold", answer, re.I)
            if not value and not gap:
                gaps.append("applicable goods/services turnover thresholds and state-dependent conditions")
        for topic in ("goods", "services"):
            if not re.search(r"\b" + topic + r"\b", query, re.I):
                continue
            # A gap admission is useful, but is still incomplete coverage.
            sentences = re.split(r"[.\n]", answer)
            answer_topic = r"services?" if topic == "services" else topic
            covered = any(re.search(r"\b" + answer_topic + r"\b", line, re.I)
                          and re.search(r"(?:₹|rs\.?|inr)\s*[\d,]+|\d[\d,.]*\s*(?:lakh|lac|crore)", line, re.I)
                          for line in sentences)
            if not covered:
                gaps.append(topic + " turnover threshold and applicable state exceptions")
    return gaps


def registration_comparison_gaps(query: str, answer: str) -> list[str]:
    if not re.search(r"\bregistration\b", query, re.I):
        return []
    markets = [("Australia", r"australia"), ("Singapore", r"singapore"), ("United Kingdom", r"uk|united kingdom")]
    requested = [(name, pattern) for name,pattern in markets if re.search(r"\b(?:"+pattern+r")\b", query,re.I)]
    if len(requested) < 2:
        return []
    return [name + " registration rules, turnover period and exceptions" for name,pattern in requested
            if not re.search(r"\b(?:"+pattern+r")\b", answer,re.I)]


def uk_vat_rules_requested(query: str) -> bool:
    return bool(re.search(r"\b(?:uk|united kingdom|hmrc)\b", query, re.I)
                and re.search(r"\bvat\b", query, re.I)
                and re.search(r"\b(?:registration rules|registration requirements|when to register|when.*register|registration deadlines?)\b", query, re.I))


def tax_rate_comparison_gaps(query: str, answer: str) -> list[str]:
    from app.orchestration.source_taxonomy import detect_jurisdictions
    if not re.search(r'\b(?:vat|gst)\b', query, re.I) or not re.search(r'\brates?\b', query, re.I):
        return []
    countries = detect_jurisdictions(query)
    if len(countries) < 2 or re.search(r'\bregistration\b', query, re.I):
        return []
    lines = answer.splitlines()
    if re.search(r'\btable\b', query, re.I):
        # Mentioning every country in prose does not fulfil a requested table
        # if verification has removed its rows.
        lines = [line for line in lines if line.strip().startswith('|')]
    return [country.replace('_', ' ').title() + ' standard VAT/GST rate'
            for country in countries
            if not any(country in detect_jurisdictions(line) and re.search(r'\d+(?:\.\d+)?\s*%', line)
                       for line in lines if not line.strip().startswith('```'))]


def uk_vat_answer_gaps(query: str, answer: str) -> list[str]:
    """Completeness is separate from whether each included claim is true.

    No threshold value is hardcoded: current amounts must come from sources.
    Apply only when registration rules were requested, not a bare historical rate.
    """
    if not uk_vat_rules_requested(query):
        return []
    checks = [
        ("rolling taxable-turnover period", r"(?:last|previous|rolling|preceding|past)\s+(?:12|twelve)[\s\-\u202f]*months?"),
        ("expected taxable turnover in the next thirty days", r"next\s+(?:30|thirty)[\s\-\u202f]*days?"),
        ("registration deadline after a retrospective threshold crossing", r"(?:30|thirty)\s+days?[^.\n]*end\s+of\s+(?:the\s+)?month"),
        ("registration deadline for an expected threshold crossing", r"(?:by|before)[^.\n]*end[^.\n]*(?:30|thirty)[\s\-\u202f]*day[^.\n]*period"),
    ]
    text = re.sub(r"\s+", " ", answer)
    gaps = [label for label,pattern in checks if not re.search(pattern, text, re.I)]
    if re.search(r"\bheadroom\b", query, re.I) and not re.search(r"\b(?:assum(?:e|es|ing|ption)|provided.*period|same.*period)\b", text, re.I):
        gaps.append("headroom assumption about the supplied turnover period, without a registration exemption conclusion")
    return gaps


_QUESTION_START = re.compile(
    r"^\W*(?:what|how|why|when|where|which|who|whom|whose|is|are|was|were|do|does|did|can|could|"
    r"should|would|will|shall|may|might|must|has|have)\b", re.I)
_REQUEST_WORD = re.compile(
    r"\b(?:calculate|compute|convert|show|explain|list|compare|find|give|tell|draw|create|plot|chart|"
    r"graph|prepare|summari[sz]e|check|verify|analy[sz]e|estimate|help|please|need|want|describe|define|"
    r"translate|retrieve|get|make|write|draft|review|confirm|work\s+out|break\s+down|visuali[sz]e)\b", re.I)
_STATEMENT_VERB = re.compile(
    r"\b(?:is|are|was|were|came|comes|has|have|had|did|does\s+not|do\s+not|provided|states?|stated|said|"
    r"shows?|showed|reported|returned|gave|removed|failed|works?|worked)\b", re.I)
_FIRST_PERSON = re.compile(r"\b(?:i|i'm|i've|my|our|we|we're|us)\b", re.I)
_AMOUNT = re.compile(r"[₹£$€]\s*\d|\d[\d,.]*\s*(?:%|lakh|crore|million|usd|inr|gbp|eur)\b", re.I)


def statement_not_question(query: str) -> str | None:
    """A clarification for input that states something rather than asking.

    "The 31 Dec 2024 rate came from a company filing." was answered "The
    rate reported for 31 Dec 2024 is 25%", and a quoted sentence ("The
    sources provided do not state the applicable rules…") with three
    paragraphs on investment arbitration: search found something, so
    something was said. A question, a request, the user's own figures or
    first-person context ("My revenue is ₹500,000.") never match."""
    # Questions are often pasted inside quotation marks; the quotes say
    # nothing about whether it is a question.
    text = (query or "").strip().strip("\"'“”‘’ ").strip()
    words = re.findall(r"[A-Za-z']+", text)
    if "?" in text or len(words) < 4:
        return None
    if (_QUESTION_START.search(text) or _REQUEST_WORD.search(text)
            or _FIRST_PERSON.search(text) or _AMOUNT.search(text)
            or not _STATEMENT_VERB.search(text)):
        return None
    return ("That reads as a statement rather than a question. What would you like me to do with it — "
            "check whether it is correct, explain it, or something else?")
