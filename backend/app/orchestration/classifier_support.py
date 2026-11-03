"""Helpers the E3 classifier shadow needs, copied verbatim from the clean
copy's task_contract.py (stages C-1, S2, S2b) so that the shadow can run
without changing the Task Contract that production reads (30 Oct 2026). When
the classifier becomes the contract's single owner (a later, separately
approved stage), these move back and this module goes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Period:
    kind: str = "unspecified"
    start: Optional[str] = None
    end: Optional[str] = None
    text: str = ""


# A rate the user states: "at an exchange rate of £1 = $1.25", "at 1.17".
_FX_GIVEN = re.compile(r"\b(?:rate\s+of|at)\s+[£$€₹]?\s?\d[\d.,]*\s*(?:=|[a-z]{3}\b|per\b)|=\s*[£$€₹]\s?\d", re.I)
_FX = re.compile(r"\b(?:exchange\s+rate|fx\s+rate|convert\s+[£$€₹]|into\s+(?:euros|dollars|pounds|rupees))\b", re.I)
# "at today's rate" / "at the latest rate" with a conversion between currencies.
_FX_CURRENT = re.compile(r"\b(?:today'?s|latest|current|live|spot|reference)\s+rate\b(?!\s+of\s)", re.I)
_CONVERSION = re.compile(r"\bconvert\b|\b(?:in|into|to)\s+(?:euros?|pounds|dollars|rupees|usd|eur|gbp|inr|sgd|singapore\s+dollars)\b"
                         r"|how\s+many\s+(?:pounds|euros|dollars|rupees)", re.I)


def _fx(text: str) -> bool:
    return bool(_FX.search(text) or (_FX_CURRENT.search(text) and _CONVERSION.search(text)))


# Authorities and central banks that place a question in a country.
_AUTHORITY_PLACE = (
    (re.compile(r"\b(?:rba|reserve\s+bank\s+of\s+australia|ato)\b", re.I), "AUSTRALIA"),
    (re.compile(r"\b(?:federal\s+reserve|fed\s+funds|federal\s+funds|fomc)\b", re.I), "US"),
    (re.compile(r"\b(?:ecb|european\s+central\s+bank)\b", re.I), "EU"),
    (re.compile(r"\b(?:rbi|reserve\s+bank\s+of\s+india)\b", re.I), "INDIA"),
    (re.compile(r"\biras\b", re.I), "SINGAPORE"),
    (re.compile(r"\bnorthern\s+ireland\b", re.I), "UK"),
)
# The other party's country is not the tax country: "billing a US client",
# "sales to EU consumers", "a client in Germany".
_COUNTERPARTY = re.compile(
    r"\b(?:an?|our|my|the|to|for)\s+((?:[A-Z][\w.]*\s*){1,3})\s*(?:-based\s+)?(?:clients?|customers?|consumers?|buyers?|vendors?|suppliers?)\b"
    r"|\b(?:clients?|customers?|consumers?|buyers?|vendors?|suppliers?)\s+(?:in|from|based\s+in)\s+((?:[A-Z][\w.]*\s*){1,3})")


def _places(part: str, context: str) -> list[str]:
    """The countries a part is about: as detected, plus those its authority
    or central bank places it in, less the other party's country when
    another remains."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    found = detect_jurisdictions(part) or detect_jurisdictions(context)
    found = list(dict.fromkeys(found + [key for pattern, key in _AUTHORITY_PLACE if pattern.search(part)]))
    other = {key for match in _COUNTERPARTY.finditer(part) for name in match.groups() if name
             for key in detect_jurisdictions(name, infer_from_tax_terms=False)}
    kept = [key for key in found if key not in other]
    return kept or found


_DATE = r"(?:\d{1,2}\s+[A-Z][a-z]+\s+(?:19|20)\d{2}|[A-Z][a-z]+\s+(?:19|20)\d{2}|(?:19|20)\d{2})"
_PERIOD_BEFORE = re.compile(rf"\b(?:on\s+or\s+before|before|until|up\s+to|prior\s+to)\s+(?:the\s+)?({_DATE})", re.I)
_PERIOD_AFTER = re.compile(rf"\b(?:on\s+or\s+after|after|from|since|starting)\s+(?:the\s+)?({_DATE})(?:\s+changes?)?", re.I)
_PERIOD_RANGE = re.compile(rf"\b(?:between|from)\s+({_DATE})\s+(?:and|to|-|–)\s+({_DATE})", re.I)
_PERIOD_FISCAL = re.compile(r"\b(?:FY|financial\s+year|tax\s+year|assessment\s+year|AY)\s*((?:19|20)\d{2}\s*[-/–]\s*\d{2,4})"
                            r"|\b((?:19|20)\d{2}\s*/\s*\d{2})\b", re.I)
_PERIOD_YEAR = re.compile(r"\b(?:in|for|of|during)\s+((?:19|20)\d{2})\b|\b((?:19|20)\d{2})\b", re.I)
# "Used to" only in its past sense ("the rate used to be 17.5%"), not "made use
# of" ("which source should be used to verify current rates", 30 Oct 2026 trial).
_PERIOD_HISTORICAL = re.compile(r"\b(?:used\s+to\s+(?:be|have|charge|apply|cost|pay|levy|require|attract|exist|get)\b|historically|"
                                r"historical|previously|formerly|in\s+the\s+past)\b", re.I)
_PERIOD_CURRENT = re.compile(r"\b(?:current(?:ly)?|latest|today'?s?|now|at\s+present|this\s+year|as\s+of\s+today)\b", re.I)
_PERIOD_NOW = re.compile(r"\b(?:now|currently)\b", re.I)


def period_of(text: str, *, official: bool = False) -> "Period":
    """The period a part asks about, as written (Stage S2, recorded only).
    An official figure with no period named is the current one ("implied")."""
    text = text or ""
    if match := _PERIOD_RANGE.search(text):
        return Period(kind="range", start=match.group(1), end=match.group(2), text=match.group(0))
    if match := _PERIOD_BEFORE.search(text):
        return Period(kind="before", end=match.group(1), text=match.group(0))
    if match := _PERIOD_AFTER.search(text):
        return Period(kind="after", start=match.group(1), text=match.group(0))
    if match := _PERIOD_FISCAL.search(text):
        value = match.group(1) or match.group(2)
        return Period(kind="year", start=value, end=value, text=match.group(0))
    # A named year before "historical": "What was the threshold in 2022?" is 2022.
    if match := _PERIOD_YEAR.search(text):
        value = match.group(1) or match.group(2)
        return Period(kind="year", start=value, end=value, text=match.group(0))
    # "It used to be 7%. What is it now?" asks for the current figure.
    if (match := _PERIOD_HISTORICAL.search(text)) and not _PERIOD_NOW.search(text):
        return Period(kind="historical", text=match.group(0))
    if match := _PERIOD_CURRENT.search(text):
        return Period(kind="current", text=match.group(0))
    return Period(kind="implied_current" if official else "unspecified")
