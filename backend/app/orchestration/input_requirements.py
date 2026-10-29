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
    if (re.search(r'\bincome tax\b',query,re.I)
            and re.search(r'\b(?:how much|owe|should I pay|missing information)\b',query,re.I)
            and not re.search(r'\d+(?:\.\d+)?\s*%',query)):
        return ('An exact income-tax amount needs the country/jurisdiction, currency, tax year, '
                'business or employment structure, other income and relevant deductible expenses, allowances and reliefs. '
                'Receipts less stated expenses is not necessarily taxable income. Please confirm those details.')
    if (re.search(r'\bcorporation tax\b', query, re.I)
            and re.search(r'\b(?:owe|how much corporation tax|exact tax liability)\b', query, re.I)
            and not re.search(r'\b(?:threshold|current rate|effective date)\b', query, re.I)
            and not re.search(r'\d+(?:\.\d+)?\s*%', query)):
        return ('An exact corporation-tax amount cannot be determined from accounting profit alone. '
                'Please confirm the tax jurisdiction and accounting period, taxable profit after adjustments, '
                'associated-company details where relevant, and applicable reliefs, losses and credits. '
                'For arithmetic only, provide taxable profit and the rate to assume.')
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


# A VAT/GST amount question needs: the country, the rate(s), and whether the
# figures include VAT. "Sales £120,000, purchases £48,000. How much VAT do I
# owe?" was answered "(£120,000 − £48,000) × r" — silently assuming the
# figures exclude VAT and that every item carries one rate.
_VAT = re.compile(r"\b(?:vat|gst)\b", re.I)
_VAT_AMOUNT_QUESTION = re.compile(
    r"\b(?:how much|owe[sd]?|payable|liabilit\w*|due to|pay (?:to )?(?:hmrc|the tax))\b"
    r"|\b(?:calculate|compute|work out|what is|what's)\b[^.?]{0,40}\b(?:vat|gst)\b"
    r"|\b(?:vat|gst)\s+(?:on|of)\s+[£$€₹]?\s*\d",
    re.I,
)
_VAT_LOOKUP_ONLY = re.compile(r"\b(?:register|registration|threshold|deadline|records?|reclaim period)\b", re.I)
_TREATMENT = re.compile(
    r"\b(?:incl(?:ud(?:e|es|ed|ing)|usive|\.)?|excl(?:ud(?:e|es|ed|ing)|usive|\.)?|net of|gross of|plus vat|plus gst|"
    r"before (?:vat|gst)|after (?:vat|gst)|vat[- ]inclusive|vat[- ]exclusive|ex[- ]vat|inc[- ]vat)\b",
    re.I,
)
_SINGLE_COUNTRY_CURRENCY = re.compile(r"£|₹|\b(?:gbp|hmrc|sterling|inr|rupees?|aed|dirhams?|sar|riyals?)\b", re.I)
_SAME_RATE = re.compile(r"\b(?:all|every|each)\b[^.?]{0,60}\b(?:standard[- ]rated|at \d|same rate|attracts?\s+\d+(?:\.\d+)?\s*%)|\bsame rate\b", re.I)
_EXPLICIT_SHARED_RATE = re.compile(
    r'\b(?:apply|use)\s+(?:the\s+)?(?:supplied\s+)?\d+(?:\.\d+)?%\s+(?:(?:GST|VAT)\s+)?rate\s+to\s+'
    r'(?:net\s+)?(?:sales\s+and\s+(?:net\s+)?purchases|purchases\s+and\s+(?:net\s+)?sales)\b', re.I,
)


def _rate_per_item(query: str) -> bool:
    from app.orchestration.calculations.engine import item_rate
    return (item_rate(query, ("sales", "turnover", "outputs")) is not None
            and item_rate(query, ("purchases", "purchase", "inputs")) is not None)


def _country_stated(question: str, earlier: str) -> bool:
    """The country is stated in this question, or in an earlier turn when this
    question does not move to another country's currency: a "UK business" two
    messages back carried over to "supplies for €6,000" (24 Oct 2026)."""
    from app.orchestration.source_taxonomy import currency_contradicts, detect_jurisdictions
    if detect_jurisdictions(question, infer_from_tax_terms=False) or _SINGLE_COUNTRY_CURRENCY.search(question):
        return True
    before = detect_jurisdictions(earlier, infer_from_tax_terms=False) or (
        ["UK"] if re.search(r"£|\b(?:gbp|hmrc|sterling)\b", earlier, re.I) else [])
    return bool(before) and not any(currency_contradicts(key, question) for key in before)


# The rule word must be about VAT or GST itself ("VAT rate", "register for
# VAT"), and the foreign currency an amount: "Compare the GBP/USD reference
# rate … and cite the VAT rules" asks about an exchange rate.
_VAT_RATE_OR_RULE = re.compile(
    r"\b(?:vat|gst)\s+(?:rates?|threshold|registration|exempt\w*)\b"
    r"|\b(?:rates?|threshold)\s+(?:of|for)\s+(?:vat|gst)\b"
    r"|\b(?:register|registration|reclaim\w*)\s+(?:for\s+)?(?:the\s+)?(?:vat|gst)\b", re.I)
_FOREIGN_AMOUNT = re.compile(
    r"[€$¥]\s?\d|\b\d[\d,.]*\s?(?:eur|euros?|usd|dollars?|aud|cad|sgd|aed|chf|jpy)\b"
    r"|\b(?:eur|usd|aud|cad|sgd|aed|chf|jpy)\s?\d", re.I)


def missing_vat_country(query: str) -> str | None:
    """A VAT or GST rate or rule asked about in another country's currency,
    with no country named: "What VAT rate applies to my €5,000 sale?" was
    answered with UK rates. Asked, not assumed."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    q = query or ""
    if not (_VAT_RATE_OR_RULE.search(q) and _FOREIGN_AMOUNT.search(q)) or detect_jurisdictions(q):
        return None
    return ("Which country is the business VAT- or GST-registered in? Rates and rules differ by country, and the "
            "amount you gave is not in pounds, so I won't assume the UK.")


def missing_vat_inputs(query: str, history=None) -> str | None:
    """The inputs a VAT/GST amount needs that the question does not give —
    only those — or None when it can be calculated (or is not that question).

    The country, rate and treatment may have been stated in an earlier user
    turn ("UK business, everything at 20%"); those are read too, never asked
    again. Only what the user stated: nothing is assumed."""
    q = re.sub(r'\b(?:ignore|disregard)\s+(?:VAT|GST)\b', '', query or '', flags=re.I)
    earlier = " ".join(getattr(m, "content", "") or "" for m in list(history or [])[-6:]
                       if getattr(m, "role", "user") == "user")
    context = f"{earlier} {q}"
    if not (_VAT.search(q) and _VAT_AMOUNT_QUESTION.search(q) and re.search(r"\d", q)) or _VAT_LOOKUP_ONLY.search(q):
        return None
    if re.search(r"[-−–]\s*\d+(?:\.\d+)?\s*%", q):
        return None  # an impossible rate is rejected first by the calculator (INVALID_PERCENTAGE)
    from app.orchestration.calculations.engine import output_vat_lines
    if output_vat_lines(q) is not None:
        # Output VAT on sales lines that each state a rate: calculated on the
        # values given, with the VAT-inclusive alternative shown — not a
        # question about input VAT or treatment the user did not ask about.
        return None
    from app.orchestration.source_taxonomy import detect_jurisdictions
    has_rate = bool(re.search(r"\d+(?:\.\d+)?\s*%", context))
    sales_and_purchases = bool(re.search(r"\b(?:sales|turnover|output)\b", q, re.I)
                               and re.search(r"\b(?:purchases?|costs?|expenses|input)\b", q, re.I))
    missing = []
    if not _country_stated(q, earlier):
        missing.append("which country the business is VAT-registered in")
    if not has_rate:
        missing.append("the VAT rate or rates that apply (standard, reduced, zero-rated or exempt)")
    elif sales_and_purchases and not _SAME_RATE.search(context) and not _EXPLICIT_SHARED_RATE.search(context) and not _rate_per_item(q):
        missing.append("whether all the sales and purchases are at that rate, or some are zero-rated, exempt or outside VAT")
    if not _TREATMENT.search(context):
        missing.append("whether the amounts include VAT or exclude VAT")
    if not missing:
        return None
    items = "; ".join(f"({index}) {item}" for index, item in enumerate(missing, start=1))
    goal = ("output VAT on sales, input VAT on purchases and the amount payable"
            if sales_and_purchases else "the VAT amount and the total")
    return (f"To work out the VAT I need: {items}. With those I can calculate {goal} — "
            "I won't assume a rate or whether the figures include VAT.")


_ATTACHED_REFERENCE = re.compile(
    r"\b(?:the|this|my|our|these)\s+(?:attached|uploaded|enclosed)\s+(?:\w+\s+){0,3}(?:report|file|document|statements?|accounts|spreadsheet|"
    r"workbook|pdf|csv|balance sheet|p\s*&\s*l|ledger|trial balance|invoice)\b", re.I)


def references_attachment(query: str) -> bool:
    """The question is about a file the user says is attached ("Please review
    the attached annual financial report …")."""
    return bool(_ATTACHED_REFERENCE.search(query or ""))


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
    r"translate|retrieve|get|make|write|rewrite|rephrase|proofread|draft|review|confirm|highlight|outline|identify|correct|update|"
    r"work\s+out|break\s+down|visuali[sz]e)\b", re.I)
_STATEMENT_VERB = re.compile(
    r"\b(?:is|are|was|were|came|comes|has|have|had|did|does\s+not|do\s+not|provided|states?|stated|said|"
    r"shows?|showed|reported|returned|gave|removed|failed|works?|worked|may|might|can|could|should)\b", re.I)
_FIRST_PERSON = re.compile(r"\b(?:i|i'm|i've|my|our|we|we're|us)\b", re.I)
_AMOUNT = re.compile(r"[₹£$€]\s*\d|\d[\d,.]*\s*(?:%|lakh|crore|million|usd|inr|gbp|eur)\b", re.I)

STATEMENT_CLARIFICATION = "What would you like me to do with this text? Choose an action or describe what you need."
# A bullet, a numbered item, a table row (tab or pipe separated) or a
# "Label: description" line: material the user pasted, not their request.
_PASTED_ITEM = re.compile(r"^\s*(?:[•●▪◦\-*–]\s|\d+[.)]\s|[^\t\n]*\t|\|.*\|)")
_LABEL_LINE = re.compile(r"^\s*([A-Z][\w&()' -]{2,60}):\s+\S")
_SUBORDINATE_OPENING = re.compile(r"^\W*(?:when|where|while|if|once|after|before)\s+[^,?\n]{3,120},\s*", re.I)
_ECHOED_CLARIFICATION = re.compile(
    r"(?:That reads as a statement rather than a question\.\s*What would you like me to do with it\b[^?]*\?"
    r"|" + re.escape(STATEMENT_CLARIFICATION) + r")\s*(?:Context:\s*)?", re.I)
STATEMENT_ACTIONS = [
    "Check whether these claims are accurate.",
    "Explain this text in plain language.",
    "Rewrite this text for clarity.",
]


def _pasted_item(line: str) -> bool:
    """A line of pasted material. "Phase 1: Immediate Preparedness" is a
    label; "Plot monthly sales as a line chart: Jan 40, …" and "Sales: Jan
    200, Feb 250. Only give the total." carry a request."""
    if _PASTED_ITEM.match(line):
        return True
    return bool(_LABEL_LINE.match(line) and not _REQUEST_WORD.search(line) and not _QUESTION_START.search(line))


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
    # Kriton's own clarification pasted back with the text asks nothing new;
    # its "?" made the whole paste read as a question (27 Oct 2026).
    text = _ECHOED_CLARIFICATION.sub("", text).strip()
    words = re.findall(r"[A-Za-z']+", text)
    if "?" in text or len(words) < 4:
        return None
    # The user's own framing, not the pasted material: "Verify the Beneficial
    # Ownership…" in a table row and "Review Local Documentation" in a bullet
    # are its content, not a request to Kriton (27 Oct 2026).
    framing = "\n".join(line for line in text.splitlines() if not _pasted_item(line))
    # "When addressing an audit, leaders should…" opens a clause, not a question.
    framing = _SUBORDINATE_OPENING.sub("", framing.strip(), count=1)
    if (_QUESTION_START.search(framing) or _REQUEST_WORD.search(framing)
            or _FIRST_PERSON.search(text) or _AMOUNT.search(text)
            or not _STATEMENT_VERB.search(text)):
        return None
    return STATEMENT_CLARIFICATION
