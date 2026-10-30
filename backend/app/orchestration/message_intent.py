"""What a message is: a question, a calculation request, a context statement,
a correction, or ambiguous pasted material.

On 28 Oct 2026 "We are a United Kingdom company reporting under IFRS 16 for
the year ending 31 December 2025." was answered "Not answered — insufficient
evidence", and "We lease equipment: annual payments of £20,000 in arrears,
discount rate 5%, lease term 4 years." with a provider failure: both state
context for later questions and ask nothing. Built from the conversation
resolver's existing classifiers (asks_something, is_scenario_only,
scenario_figures) and the context patterns the history selection uses
(conversation.py), not from new per-wording rules.

A context statement or correction is acknowledged with the facts read from it,
and the facts stay in the conversation: the history selection carries them
into later requests (conversation.with_essential_context) and the figure
checks count them as the user's own (service.stated_history).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.orchestration.conversation import _JURISDICTION_OR_FRAMEWORK, _PERIOD, _SCENARIO_NOTE
from app.orchestration.conversation_resolver import asks_something, is_scenario_only, scenario_figures

QUESTION, CALCULATION, CONTEXT, CORRECTION, AMBIGUOUS = (
    "question", "calculation_request", "context_statement", "correction", "ambiguous")

_ORGANISATION = re.compile(r"^\W*(?:we|our|the\s+(?:company|entity|business|group|client|lessee|lessor))\b", re.I)
_CORRECTION = re.compile(r"\bcorrect(?:ion|ed)?\b|\bnot\s+\d|\binstead\s+of\b|\bshould\s+(?:be|read|have\s+been)\b|"
                         r"\bactually\b|\bI\s+meant\b", re.I)
_COMPUTE = re.compile(r"\b(?:calculate|compute|work\s+out|determine|how\s+much|what\s+(?:is|are)\s+the\s+"
                      r"(?:total|amount|liability|profit|margin|vat|tax))\b", re.I)


@dataclass
class ContextFacts:
    jurisdiction: list[str] = field(default_factory=list)
    framework: list[str] = field(default_factory=list)
    period: list[str] = field(default_factory=list)
    figures: list[str] = field(default_factory=list)

    def any(self) -> bool:
        return bool(self.jurisdiction or self.framework or self.period or self.figures)


_FRAMEWORKS = re.compile(r"\b(?:IFRS(?:\s?\d+)?|IAS\s?\d+|US\s+GAAP|UK\s+GAAP|FRS\s?\d+|Ind\s?AS(?:\s?\d+)?|ASC\s?\d+)\b")


def context_facts(text: str) -> ContextFacts:
    found = ContextFacts()
    for match in _JURISDICTION_OR_FRAMEWORK.finditer(text or ""):
        target = found.framework if _FRAMEWORKS.fullmatch(match.group(0)) else found.jurisdiction
        if match.group(0) not in target:
            target.append(match.group(0))
    period = re.search(r"\b(?:(?:financial\s+|accounting\s+|tax\s+)?(?:year|period|quarter)s?\s+end(?:ing|ed)?\s+"
                       r"[^,.;:\n]{3,30}|FY\s?\d{2,4})", text or "", re.I)
    if period or _PERIOD.search(text or ""):
        found.period.append((period.group(0) if period else _PERIOD.search(text).group(0)).strip())
    # Amounts, rates and durations, as written: "£20,000", "5%", "4 years".
    found.figures = list(dict.fromkeys(
        scenario_figures(text or "")
        + [m.group(0).strip() for m in _RATE_OR_TERM.finditer(text or "")]))
    return found


_RATE_OR_TERM = re.compile(r"\b\d+(?:\.\d+)?\s?%|\b\d+(?:\.\d+)?[\s-]+(?:years?|months?|quarters?)\b", re.I)


def classify_message(text: str, history=()) -> str:
    """One of QUESTION, CALCULATION, CONTEXT, CORRECTION, AMBIGUOUS.

    AMBIGUOUS is pasted material that states facts about others with no
    framing of the user's own; input_requirements.statement_not_question
    handles it, as before."""
    t = (text or "").strip()
    if asks_something(t):
        return CALCULATION if scenario_figures(t) and _COMPUTE.search(t) else QUESTION
    # A request without a question mark ("… straight line depreciation yearly
    # and monthly how much") is still a request: the calculator recognises it.
    from app.orchestration.calculations.engine import calculate_from_query
    if _COMPUTE.search(t) or calculate_from_query(t).matched:
        return CALCULATION
    earlier_users = [getattr(m, "content", "") for m in history or () if getattr(m, "role", "") == "user"]
    if _CORRECTION.search(t) and re.search(r"\d", t) and any(re.search(r"\d", e) for e in earlier_users):
        return CORRECTION
    # A context statement is declarative: it opens with a subject ("We …",
    # "The company …", "Swift Transport exchanges …"), never an instruction
    # ("Draw a pie chart …", "Pass the journal entry …", "Convert £10,000 …")
    # or a bare noun phrase ("Pie chart of …"), all of which ask for something.
    from app.orchestration.input_requirements import _REQUEST_WORD
    facts = context_facts(t)
    if (facts.any() and (is_scenario_only(t) or _ORGANISATION.search(t)) and _DECLARATIVE_START.match(t)
            and not _REQUEST_WORD.search(t)):
        return CONTEXT
    return AMBIGUOUS


_DECLARATIVE_START = re.compile(
    r"^\W*(?:(?i:we|our|my|i|the|a|an|this|these|its|their)\b"
    r"|[A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){0,4}\s+(?:is|are|was|were|has|have|had|holds?|owns?|leases?|sells?|"
    r"buys?|bought|sold|recogni[sz]ed|recogni[sz]es|reports?|reported|operates?|acquired|acquires|issued|issues|"
    r"pays?|paid|received|receives|made|makes|incurred|incurs|entered|enters|signed|signs)\b)")


def acknowledgement(text: str, kind: str) -> str:
    """The reply to a context statement or correction: what was read, and
    what Kriton can do with it. Nothing is calculated or asserted."""
    facts = context_facts(text)
    parts = []
    if facts.jurisdiction:
        parts.append("jurisdiction: " + ", ".join(facts.jurisdiction))
    if facts.framework:
        parts.append("framework: " + ", ".join(facts.framework))
    if facts.period:
        parts.append("period: " + ", ".join(facts.period))
    if facts.figures:
        parts.append("figures: " + ", ".join(facts.figures))
    noted = "; ".join(parts)
    if kind == CORRECTION:
        head = f"Noted — I'll use this correction in place of the earlier figure ({noted})."
    else:
        head = f"Noted — I'll use this for the rest of the conversation ({noted})."
    return head + " What would you like me to do with it? For example, calculate figures, explain the accounting " \
                  "treatment, or prepare journal entries."


CONTEXT_ACTIONS = ["Calculate the figures", "Explain the accounting treatment", "Prepare the journal entries"]


def is_context_action(query: str) -> bool:
    """One of the acknowledgement's actions applied to the user's own context
    ("Explain the accounting treatment Context: The company recognised
    revenue of £500,000 …"): a professional explanation of the user's facts,
    not a research question. It was refused as "the sources provided do not
    establish an answer" (28 Oct 2026)."""
    head, separator, subject = (query or "").partition(" Context: ")
    if not separator:
        return False
    actions = {action.lower() for action in CONTEXT_ACTIONS}
    return head.strip().rstrip(".").lower() in actions and classify_message(subject.strip()) in (CONTEXT, CORRECTION)


def opens_new_context(text: str) -> bool:
    """A statement with its own subject and figures ("We lease a van: annual
    payments of £8,000 …") sent while Kriton's clarification question is
    open: new context, not the answer to that question. It was taken as a
    reply and answered at length (28 Oct 2026). A reply supplying figures
    ("Sales are £100,000 and purchases £50,000.") has no such subject, and
    one that does usually answers a single point ("Our turnover is £95,000
    for the last 12 months."), so a new scenario needs three figures."""
    return bool(_ORGANISATION.match(text or "")) and len(context_facts(text).figures) >= 3
