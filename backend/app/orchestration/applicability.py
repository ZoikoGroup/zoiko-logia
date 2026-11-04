"""Conservative question-period parsing. Never guess a financial-year calendar."""
import re
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class RequestedPeriod:
    start: date | None = None
    end: date | None = None
    clarification: str = ""


def requested_period(query: str, start=None, end=None) -> RequestedPeriod:
    dates = re.findall(r"\b(20\d{2}|19\d{2})-(\d{2})-(\d{2})\b", query)
    if dates:
        try:
            values = [date(*map(int, d)) for d in dates]
        except ValueError:
            return RequestedPeriod(clarification="Clarify the invalid requested date.")
        if len(values) > 2 or values[0] > values[-1]:
            return RequestedPeriod(clarification="Clarify the requested date range.")
        return RequestedPeriod(values[0], values[-1])
    if start and end:
        return RequestedPeriod(start, end) if start <= end else RequestedPeriod(clarification="Clarify the reporting period.")
    years = re.findall(r"\b(?:19|20)\d{2}\b", query)
    if years:
        if re.search(r"\b(?:fy|financial year|fiscal year|year ended|year ending|tax year)\b", query, re.I):
            return RequestedPeriod(clarification="Specify the reporting-period start and end dates; financial-year calendars differ.")
        if len(set(years)) == 1:
            year = int(years[0])
            return RequestedPeriod(date(year, 1, 1), date(year, 12, 31))
        return RequestedPeriod(clarification="Specify the requested period boundaries.")
    if re.search(r"\b(?:historical|previous|prior|last year|last financial year)\b", query, re.I):
        return RequestedPeriod(clarification="Specify the historical period start and end dates.")
    return RequestedPeriod(start or end, end or start)


# These are applicability gates, not a general-purpose classifier. A general
# concept or a macro series does not become tax law merely by containing "tax".
_RULE_APPLICATION = re.compile(
    r"\b(?:rates?|thresholds?|limits?|caps?|deadlines?|eligib\w*|exempt\w*|registr\w*|reclaim\w*|"
    r"recover\w*|refund\w*|qualif\w*|compulsory|mandatory|legally|laws?|statutory|"
    r"regulat\w*|penalt\w*|filing|file|submit|must|required|entitl\w*|who can|who may|can use)\b", re.I)
_MACRO_SERIES = re.compile(
    r"\b(?:inflation|GDP|gross domestic product|unemployment|economic growth|"
    r"consumer price index|government revenue|government debt|national debt)\b", re.I)
_TAX_SUBJECT = re.compile(r"\b(?:tax|VAT|GST|HMRC|CBIC)\b", re.I)
_CONCEPT = re.compile(
    r"\b(?:what (?:is|are)|define|definition|meaning|concept|explain|overview|"
    r"checklist|worked example|grounded example)\b", re.I)


def macroeconomic_only(query: str) -> bool:
    """Macro data keeps its own dated, country-specific connector checks."""
    return bool(_MACRO_SERIES.search(query)) and not (
        (_TAX_SUBJECT.search(query) and _RULE_APPLICATION.search(query))
        or re.search(r"\b(?:statutory|legally|regulat\w*|minimum wage|employment law|company law|IFRS|IAS|GAAP)\b", query, re.I))


def requires_rule_applicability(query: str) -> bool:
    """Whether answering entails jurisdiction-dependent material rules.

    This never grants a right or makes a version eligible. Rights, status,
    dates, conflicts and active request filters are still checked downstream.
    """
    from app.orchestration.calculation_service import is_self_contained_calculation, needs_lookup, _SUPPLIED_TAX_RATE
    if macroeconomic_only(query):
        return False
    if is_self_contained_calculation(query) and not needs_lookup(query):
        return False
    if (_SUPPLIED_TAX_RATE.search(query) and not needs_lookup(query)
            and re.search(r"\b(?:EPS|earnings per share|net income|profit|cash flow)\b", query, re.I)
            and not (_TAX_SUBJECT.search(_SUPPLIED_TAX_RATE.sub(" ", query))
                     and _RULE_APPLICATION.search(_SUPPLIED_TAX_RATE.sub(" ", query)))):
        return False
    if re.search(r"\b(?:IFRS|IAS|GAAP)\b", query, re.I):
        return True
    if _TAX_SUBJECT.search(query):
        return bool(_RULE_APPLICATION.search(query) or not _CONCEPT.search(query))
    # Unknown material contexts retain the prior conservative behavior.
    return True
