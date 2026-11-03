"""Whether a statistics or central-bank connector applies to a question
(Task Contract, Stage C-2b).

Each connector gates itself on its own words ("interest rate", "debt",
"wage", "cash rate"), so connectors fired for questions they cannot answer
(offline connector report, 29 Oct 2026):
- an accounting case ("Kestrel ... the interest rate implicit in the lease is
  7%") called the Bank of England, Bank of Canada and RBA, and a statistics
  search;
- "What interest rate does HMRC charge on late VAT payments?" called the
  Bank of Canada and the RBA: HMRC names the UK, but only country names
  counted as naming one;
- "What is the RBA cash rate?" called the Bank of Canada;
- "VAT bad debt relief", "Social Security wage base", "debt-to-equity ratio"
  called a macroeconomic statistics search;
- a US case under ASC 740 called the UK tax-rate search on GOV.UK.
These rules only withhold a connector; none is added and no connector runs
for a question it did not already match.
"""
from __future__ import annotations

import re

# A macroeconomic subject: what the statistics connectors answer.
_MACRO = re.compile(
    r"\b(?:inflation|cpi|consumer\s+prices?|gdp|gross\s+domestic|gni|gnp|unemployment|employment\s+rate|"
    r"labou?r\s+force|population|poverty|trade\s+balance|current\s+account|"
    # Trade figures, not a word in a name ("Horizon Import hedges a purchase").
    r"(?:total|net|goods|merchandise|annual)\s+(?:exports?|imports?)|(?:exports?|imports?)\s+(?:of\s+goods|growth|volumes?|data|statistics|as\s+a)|"
    r"(?:government|public|national|sovereign|federal)\s+(?:debt|deficit|revenue|spending|borrowing)|"
    r"treasury\s+(?:yields?|bills?|notes?|bonds?|statement)|budget\s+deficit|average\s+(?:wages?|earnings)|wage\s+growth)\b",
    re.I)
# An accounting task on the user's own facts, or a comparison of frameworks.
_ACCOUNTING = re.compile(
    r"\b(?:ifrs|ias\s?\d+|gaap|asc\s?\d+|frs\s?\d+|ind\s?as|leases?|leased|lessee|lessor|journal|depreciat\w*|"
    r"amorti[sz]\w*|ratio|share\s+prices?|revenue\s+recogni\w*|recogni[sz]ed\s+revenue|impairment|provisions?|"
    r"valuation\s+allowances?)\b", re.I)
# A tax-administration question (rates and rules come from the tax authority,
# not from a statistics series).
_TAX = re.compile(r"\b(?:vat|gst|hmrc|irs|tds|cbic|corporation\s+tax|income\s+tax|national\s+insurance|"
                  r"social\s+security|payroll\s+tax|bad\s+debt\s+relief|self\s+assessment)\b", re.I)
# A central bank's rate asked for by name.
_CENTRAL_BANK = re.compile(r"\b(?:bank|base|policy|cash|repo|overnight)\s+rates?\b|\bbank\s+of\s+\w+|\breserve\s+bank\b|"
                           r"\b(?:rba|boe|mpc|fed|fomc|federal\s+reserve)\b|\bfed(?:eral)?\s+funds\b", re.I)
# Names that place a question in one country without naming it.
_AUTHORITY_COUNTRY = (
    (re.compile(r"\b(?:hmrc|bank\s+of\s+england|boe|mpc|companies\s+house)\b", re.I), "GB"),
    (re.compile(r"\b(?:rba|reserve\s+bank\s+of\s+australia|ato)\b", re.I), "AU"),
    (re.compile(r"\b(?:bank\s+of\s+canada|cra)\b", re.I), "CA"),
    (re.compile(r"\b(?:irs|federal\s+reserve|fomc|fed\s+funds|us\s+gaap|asc\s?\d+|fasb)\b", re.I), "US"),
    (re.compile(r"\b(?:cbic|rbi|gstr|reserve\s+bank\s+of\s+india)\b", re.I), "IN"),
)
_JURISDICTION_ISO = {"UK": "GB", "US": "US", "INDIA": "IN", "AUSTRALIA": "AU", "CANADA": "CA", "IRELAND": "IE",
                     "GERMANY": "DE", "FRANCE": "FR", "JAPAN": "JP", "CHINA": "CN", "SINGAPORE": "SG"}

STATISTICS = frozenset({"dbnomics", "dbnomics_pair", "fred", "abs", "cso_ireland", "us_treasury"})
CENTRAL_BANKS = frozenset({"bank_of_england", "bank_of_canada", "rba"})
_COUNTRY = {"bank_of_england": "GB", "bank_of_canada": "CA", "rba": "AU", "govuk_tax_rate": "GB", "abs": "AU",
            "cso_ireland": "IE", "fred": "US", "us_treasury": "US"}


def countries(query: str) -> set[str]:
    """The countries a question places itself in: those it names, and those
    its tax authority, central bank or US framework imply."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    found = {_JURISDICTION_ISO.get(key, key) for key in detect_jurisdictions(query or "", infer_from_tax_terms=False)}
    found |= {iso for pattern, iso in _AUTHORITY_COUNTRY if pattern.search(query or "")}
    return found


def applies(connector: str, query: str) -> bool:
    """False when the connector cannot answer this question; True otherwise,
    leaving the connector's own gate to decide as before."""
    text = query or ""
    if connector in STATISTICS and not _MACRO.search(text) and (_ACCOUNTING.search(text) or _TAX.search(text)):
        return False
    if connector in CENTRAL_BANKS and _ACCOUNTING.search(text) and not _CENTRAL_BANK.search(text):
        return False
    country = _COUNTRY.get(connector)
    if country:
        placed = countries(text)
        if placed and country not in placed:
            return False
    return True
