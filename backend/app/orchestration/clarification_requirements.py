"""What a request needs before it can be answered, and the question to ask
when it is missing (3 Nov 2026; on unless KRITON_CONTRACT_CLARIFICATION is
false).

Before this, missing information was caught by one pattern per past failure
(income tax "how much", corporation tax "owe", VAT registration "my/our"…);
anything else went to the model, which guessed. On 26 probe questions across
tax, accounting, audit and calculations, 4 of 18 incomplete requests were
asked about. The requirement is now decided from what the request is:

1. Jurisdiction. A part the Task Contract says needs an official figure or
   rule (a rate, threshold, deadline or legal rule) with no country resolved,
   no jurisdiction selected and none stated earlier in the case.
2. Calculation inputs. A part that asks for an amount is matched to a task
   type in TASKS below; each lists the inputs it needs as generic slot types
   (an amount, a rate, a term, cash flows). A calculator in
   calculations.engine that recognises the task asks for its own inputs, so
   it is left to do so.
3. A referent with nothing behind it: "this project", "the sale", "this
   misstatement" asked to be calculated or judged with no figures in the
   message or the conversation.

Inputs are looked for in the request, the reply that answers an earlier
clarification (task_query), and the earlier turns of the same case, so a user
who has already given them is not asked again. Deterministic; no model call.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Optional, Sequence


def enabled() -> bool:
    return os.getenv("KRITON_CONTRACT_CLARIFICATION", "true").strip().lower() not in {"0", "false", "no", "off"}


# ── Slot types ───────────────────────────────────────────────────────────────
_MONEY = re.compile(r"[£$€₹¥]\s?\d|\b\d[\d,]*(?:\.\d+)?\s*(?:k|m|bn|million|billion|lakhs?|crores?|"
                    r"gbp|usd|eur|inr|aud|cad|sgd|aed|nzd|zar|sar)\b|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{4,}(?:\.\d+)?\b", re.I)
_RATE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|per\s*cent|percent|pc\b)", re.I)
_TERM = re.compile(r"\b\d+(?:\.\d+)?\s*(?:years?|yrs?|months?|mths?|quarters?|periods?|instal?ments?|payments?)\b"
                   r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|twenty-five|thirty)\s+(?:years?|months?)\b",
                   re.I)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _money_count(text: str) -> int:
    # A year ("in 2025") is not an amount.
    return sum(1 for m in _MONEY.finditer(text) if not _YEAR.fullmatch(m.group(0).strip()))


# A company named by ticker or name: not the tax and accounting acronyms or the
# words that open a question.
_NOT_A_COMPANY = {"VAT", "GST", "HST", "SST", "UK", "US", "USA", "EU", "UAE", "IFRS", "IAS", "GAAP", "ISA", "NPV", "IRR",
                  "EPS", "PE", "P", "E", "PAYE", "NI", "NIC", "HMRC", "IRS", "ATO", "CRA", "IRAS", "CEO", "CFO", "AI", "ETF",
                  "USD", "GBP", "EUR", "INR", "AUD", "CAD", "SGD", "AED", "JPY", "I", "OK", "TDS", "FX"}
_OPENING = {"what", "which", "how", "is", "are", "calculate", "compute", "give", "tell", "show", "find", "get", "explain",
            "the", "a", "an", "can", "could", "please", "what's", "whats", "do", "does", "list", "compare"}


def _names_company(text: str) -> bool:
    for sentence in re.split(r"(?<=[.?!])\s+|\n", text or ""):
        words = re.findall(r"[A-Za-z][\w&.'-]*", sentence)
        for index, word in enumerate(words):
            bare = re.sub(r"'s$", "", word).strip(".")
            if index == 0 and bare.lower() in _OPENING:
                continue
            if bare.upper() in _NOT_A_COMPANY or bare.lower() in _OPENING:
                continue
            if re.fullmatch(r"[A-Z]{1,5}", bare) or (bare[:1].isupper() and len(bare) > 1 and index > 0) \
                    or (index == 0 and bare[:1].isupper() and len(words) == 1):
                return True
    return False


_CURRENCY_AMOUNT = re.compile(r"[£$€₹¥]\s?\d|\d[\d,]*(?:\.\d+)?\s*(?:gbp|usd|eur|inr|jpy|aud|cad|sgd|aed|nzd|chf|"
                              r"pounds?|dollars?|euros?|rupees?|yen)\b", re.I)
_CURRENCY_NAME = re.compile(r"\b(?:pounds?|sterling|gbp|dollars?|usd|euros?|eur|rupees?|inr|yen|jpy|yuan|cny|"
                            r"dirhams?|aed|riyals?|francs?|chf)\b|[£$€₹¥]")
_POPULATION = re.compile(r"\bpopulation\b[^.?!]{0,40}\d|\b\d[\d,]*\s+(?:items|transactions|invoices|entries|records|"
                         r"balances|payments|claims)\b", re.I)
_SAMPLING_RISK = re.compile(r"\d+(?:\.\d+)?\s*%|\bconfidence\b|\btolerable\b|\bexpected\s+(?:deviation|error)\b", re.I)

SLOTS: dict[str, tuple[str, Callable[[str], bool]]] = {
    # Or the figures to work it out: "A share costs $150 and EPS is $6. What is
    # the P/E ratio?" was asked which company (6 Nov 2026).
    "company": ("the company (its name or ticker, and the exchange if it trades on more than one)",
                lambda t: _names_company(t) or _money_count(t) >= 2),
    # An amount with its currency, or two currencies named ("How many rupees
    # is one US dollar worth?"): the source is then stated.
    "source_currency": ("the currency of the amount you want to convert (for example £5,000 or 5,000 USD)",
                        lambda t: bool(_CURRENCY_AMOUNT.search(t)) or len(set(_CURRENCY_NAME.findall(t.lower()))) >= 2),
    "salary": ("the gross salary or pay and its period (for example £40,000 a year or £3,000 a month)",
               lambda t: _money_count(t) >= 1),
    "country": ("the country the employee is paid in", lambda t: _jurisdiction_known(t, None)),
    "population": ("the population (how many items, and their total value for a substantive test)",
                   lambda t: bool(_POPULATION.search(t))),
    "sampling_risk": ("the confidence level and the tolerable and expected deviation (or misstatement)",
                      lambda t: bool(_SAMPLING_RISK.search(t))),
    "amount": ("the amount", lambda t: _money_count(t) >= 1),
    "principal": ("the loan amount", lambda t: _money_count(t) >= 1),
    "rate": ("the interest rate", lambda t: bool(_RATE.search(t))),
    "discount_rate": ("the discount rate", lambda t: bool(_RATE.search(t))),
    "term": ("the term (number of years or payments)", lambda t: bool(_TERM.search(t))),
    "cash_flows": ("the cash flows for each period (including any initial investment)", lambda t: _money_count(t) >= 1),
    "benchmark": ("the benchmark figure (for example profit before tax, revenue or total assets) and its amount",
                  lambda t: _money_count(t) >= 1),
    "misstatement_and_materiality": ("the misstatement amount and the materiality level (or the benchmark it is set from)",
                                     lambda t: _money_count(t) >= 2),
    "transaction": ("the transaction details: what happened, the amount and the date or period",
                    lambda t: _money_count(t) >= 1),
}


@dataclass(frozen=True)
class Task:
    name: str
    label: str
    pattern: re.Pattern
    slots: tuple[str, ...]


# A task is a kind of request, with the inputs every instance of it needs.
TASKS: tuple[Task, ...] = (
    Task("market_figure", "the market figure",
         re.compile(r"\b(?:share|stock)\s+price\b|\bmarket\s+cap(?:itali[sz]ation)?\b|\b(?:p/?e|price[- ]to[- ]earnings)\s+ratio\b"
                    r"|\bdividend\s+yield\b|\b52[- ]week\s+(?:high|low)\b", re.I),
         ("company",)),
    Task("fx_conversion", "the conversion",
         re.compile(r"\bconvert\b[^.?!]{0,40}\b(?:to|into)\b|\bhow\s+many\s+(?:euros|dollars|pounds|rupees|yen)\b", re.I),
         ("source_currency",)),
    Task("net_pay", "the take-home pay",
         re.compile(r"\b(?:take[- ]home|net)\s+pay\b|\bpayslip\b|\bpayroll\s+deductions\b|\bpaye\s+(?:on|for)\b", re.I),
         ("salary", "country")),
    Task("sample_size", "the sample size",
         re.compile(r"\bsample\s+size\b|\bhow\s+many\s+(?:items|transactions|invoices)\s+(?:should|do|must)\s+(?:i|we)\s+(?:test|sample)\b", re.I),
         ("population", "sampling_risk")),
    Task("loan_repayment", "the loan repayment",
         re.compile(r"\b(?:loan|mortgage|borrowing)\b[^.?!]{0,60}\b(?:repayments?|instal?ments?|payments?|emi)\b"
                    r"|\b(?:repayments?|instal?ments?|emi)\b[^.?!]{0,40}\b(?:loan|mortgage)\b|\bemi\b", re.I),
         ("principal", "rate", "term")),
    Task("npv", "the net present value",
         re.compile(r"\b(?:npv|net\s+present\s+value)\b", re.I), ("cash_flows", "discount_rate")),
    Task("irr", "the internal rate of return",
         re.compile(r"\b(?:irr|internal\s+rate\s+of\s+return)\b", re.I), ("cash_flows",)),
    Task("payback", "the payback period",
         re.compile(r"\bpayback\s+period\b", re.I), ("cash_flows",)),
    Task("materiality_judgement", "whether it is material",
         re.compile(r"\b(?:misstatements?|errors?|differences?|adjustments?)\b[^.?!]{0,60}\bmaterial\b"
                    r"|\bis\s+(?:this|it|that)\s+(?:\w+\s+){0,2}material\b", re.I),
         ("misstatement_and_materiality",)),
    Task("materiality", "materiality",
         re.compile(r"\b(?:calculate|compute|set|determine|work\s+out)\b[^.?!]{0,50}\b(?:overall\s+|performance\s+)?materiality\b"
                    r"|\b(?:overall|performance)\s+materiality\b[^.?!]{0,30}\b(?:for|of)\s+(?:our|my|the|this)\b", re.I),
         ("benchmark",)),
    Task("indirect_tax_amount", "the tax amount",
         re.compile(r"\b(?:calculate|compute|work\s+out)\b[^.?!]{0,40}\b(?:vat|gst|hst|sales\s+tax)\b"
                    r"|\b(?:vat|gst|hst|sales\s+tax)\s+(?:on|for)\s+(?:my|our|the|this)\b", re.I),
         ("amount",)),
    Task("journal_entry", "the journal entry",
         re.compile(r"\bjournal\b|\b(?:record|post|pass)\s+(?:the\s+|an?\s+)?(?:\w+\s+)?entr(?:y|ies)\b", re.I),
         ("transaction",)),
)

# Named only alongside other questions ("loan repayments start at what
# income?", "materiality as a concept"): these need a calculation request.
# NPV, IRR and payback are calculations whatever the wording.
_CALCULATIONS = {"loan_repayment", "materiality"}
_CONCEPT_QUESTION = re.compile(
    r"^\W*(?:what\s+(?:is|are|does)\s+(?:an?\s|the\s+(?:formula|meaning|purpose|difference)\b)|explain\b|define\b|describe\b"
    r"|how\s+(?:is|are|do|does|should)\b[^?]{0,80}\b(?:calculated|computed|determined|measured|work|works|set)\b"
    # A process walk-through ("Show how a draft journal entry becomes an
    # approved posted journal entry", QA case E02) asks how it works, not for an entry.
    r"|(?:show|explain|describe|walk\s+(?:me\s+)?through)\s+how\b[^?.]{0,80}\b(?:becomes?|moves?|flows?|goes|progress(?:es)?)\b"
    r"|why\b)", re.I)

# A request about a specific item it never describes ("this project", "the
# sale", "this misstatement"), to be calculated or judged.
_REFERENT = re.compile(r"\b(?:this|that|the|my|our)\s+(?:project|investment|sale|purchase|transaction|invoice|loan|"
                       r"misstatement|error|adjustment|contract|lease|asset|machine|payment|bill|expense|balance)\b", re.I)
_ACT = re.compile(r"\b(?:calculate|compute|work\s+out|record|post|pass|is|what\s+is|what's|how\s+much|determine)\b", re.I)


def _jurisdiction_known(context: str, selected: Optional[str]) -> bool:
    """A country the user stated: named, or implied by a term only one
    country has (HMRC, PAYE, GSTR-3B). A bare "VAT" or "GST" is not one:
    detect_jurisdictions' default reads them as UK and India."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    from app.orchestration.task_contract import _AUTHORITY_PLACE
    from app.orchestration.input_requirements import _SINGLE_COUNTRY_CURRENCY
    text = context or ""
    if selected or detect_jurisdictions(text, infer_from_tax_terms=False):
        return True
    # An authority or central bank (RBA, IRAS, ECB), a currency only one
    # country uses (£, ₹, Rs), or a country-specific scheme, form or body the
    # deterministic resolver knows (Flat Rate Scheme, GST Council).
    if any(pattern.search(text) for pattern, _ in _AUTHORITY_PLACE) or _SINGLE_COUNTRY_CURRENCY.search(text) \
            or re.search(r"\bRs\.?\s?\d", text):
        return True
    try:
        from app.orchestration.country_resolution import resolve
        return bool(resolve(text, "").countries)
    except Exception:  # noqa: BLE001
        return False


# Asked in general, as a comparison or about a method, not for one country's
# figure: "What is the difference between VAT and GST as tax systems?", "How
# do VAT registration thresholds work in general?". An accounting or auditing
# standard (IFRS 9, ASC 280, ISA 320) defines its own rule.
_GENERAL = re.compile(r"\b(?:difference\s+between|in\s+general|generally|as\s+(?:tax\s+)?systems?|in\s+principle|"
                      r"compared?\s+(?:to|with)|vs\.?|versus|method|concept|why\s+do)\b", re.I)


def _official_without_country(contract) -> list[tuple[str, str]]:
    """(part, fact) for each part asking a country's official figure or rule:
    as the contract classifies it, or a practical question (not an
    explanation) about a jurisdiction-bound subject in the registry (VAT,
    sales tax, payroll, minimum wage…), which the contract classifies only
    once a country is known."""
    from app.orchestration import task_contract as tc
    from app.orchestration.source_registry import subjects_of
    found = []
    for r in contract.retrieval:
        if r.connector == "exchange_rate" or _GENERAL.search(r.part) or tc._STANDARD.search(r.part):
            continue
        if r.needs_official:
            found.append((r.part, r.fact_type))
        elif (r.fact_type == "explanation" and set(subjects_of(r.part)) - {"fx"} and not _RATE.search(r.part)
              and not tc._CONCEPTUAL.search(r.part) and not tc._EXPLAIN_START.search(r.part)
              and (tc._RULE_QUESTION.search(r.part) or tc._FACT_RATE.search(r.part) or tc._NAMED_RATE.search(r.part)
                   or re.search(r"\bwhat\s+is\s+the\b|\bwhat\s+\w+(?:\s+\w+){0,3}\s+(?:applies|apply|is\s+charged|"
                                r"is\s+payable|is\s+due|do\s+i\s+pay)\b", r.part, re.I))):
            found.append((r.part, "rule"))
    return found


def _jurisdiction_question(contract, context: str, selected: Optional[str]) -> Optional[str]:
    if contract is None or _jurisdiction_known(context, selected):
        return None
    from app.orchestration.source_registry import subjects_of
    from app.orchestration.task_contract import _STANDARD
    official = _official_without_country(contract)
    # A standard named in the case (ASC 280's 10% segment threshold) defines
    # a non-tax figure itself; a tax part still needs its country.
    if _STANDARD.search(context or ""):
        official = [(part, fact) for part, fact in official if set(subjects_of(part)) - {"fx"}]
    if not official:
        return None
    asked = " and ".join(sorted({fact for _, fact in official}))
    return f"Which country (and state or province, if relevant) should the {asked} be for?"


def missing_inputs(contract, *, task_query: str, context: str, selected_jurisdiction: Optional[str] = None,
                   calculator_matched: bool = False, earlier: Sequence[str] = ()) -> list[str]:
    """The inputs the request still needs, as short phrases (empty when it is
    complete). context: the request with the reply (task_query) and earlier
    turns; earlier: those turns' user messages. A task's inputs come from the
    request and from earlier turns about the same task only."""
    needs: list[str] = []
    request = task_query or ""
    kinds = set(contract.deliverable_kinds()) if contract is not None else set()
    # A definition or method question needs no inputs: "What is a P/E ratio?",
    # "How is a sample size determined?".
    if _CONCEPT_QUESTION.search(request):
        return needs
    for task in TASKS:
        if calculator_matched and task.name not in ("materiality_judgement", "journal_entry"):
            continue
        if not task.pattern.search(request):
            continue
        # A tax amount only when the contract records one as requested ("How
        # much GST is charged on gold jewellery in India?" asks for the rate);
        # a calculation only when one is asked for ("At what income do Plan 2
        # student loan repayments start?" asks for a threshold).
        if task.name == "indirect_tax_amount" and not (contract is not None and contract.output_constraints.vat_amount_requested):
            continue
        if task.name in _CALCULATIONS and not kinds & {"amount", "schedule"}:
            continue
        same_task = "\n".join([request, *(text for text in earlier if task.pattern.search(text))])
        for slot in task.slots:
            phrase, present = SLOTS[slot]
            if not present(same_task) and phrase not in needs:
                needs.append(phrase)
        break   # one task per request: the first, most specific match
    if not needs and not calculator_matched and _REFERENT.search(request) and _ACT.search(request) \
            and _money_count(context) == 0 and contract is not None \
            and any(d.description.split(":", 1)[0] in ("amount", "journal_entry", "schedule") for d in contract.deliverables):
        needs.append("the figures for it (amounts, dates and any rates)")
    return needs


def _user_text(messages: Sequence) -> str:
    return "\n".join(getattr(m, "content", "") for m in messages or () if getattr(m, "role", "") == "user")


def clarification(contract, *, task_query: str, history: Sequence = (), selected_jurisdiction: Optional[str] = None,
                  calculator_matched: bool = False, input_history: Sequence | None = None) -> Optional[str]:
    """The question to ask before answering, or None when the request is
    complete. history: this case's turns (with its setting statements),
    which can name the country; input_history: the turns the request itself
    follows from, which alone can supply a calculation's inputs (another
    open task's "₹50,000, GST 18%" is not a loan's amount and rate). Only
    user turns count."""
    if not enabled() or contract is None or contract.message_type in ("context", "correction", "statement", "empty"):
        return None
    context = f"{_user_text(history)}\n{task_query}"
    questions = []
    country = _jurisdiction_question(contract, context, selected_jurisdiction)
    earlier_inputs = [getattr(m, "content", "") for m in (history if input_history is None else input_history) or ()
                      if getattr(m, "role", "") == "user"]
    # The referent rule reads the whole case ("that lease" has its figures in
    # an earlier setting turn); a task's inputs only its own turns (earlier).
    needs = missing_inputs(contract, task_query=task_query, context=context, selected_jurisdiction=selected_jurisdiction,
                           calculator_matched=calculator_matched, earlier=earlier_inputs)
    if needs:
        task = next((t for t in TASKS if t.pattern.search(task_query or "")), None)
        label = task.label if task else "this"
        listed = needs[0] if len(needs) == 1 else ", ".join(needs[:-1]) + " and " + needs[-1]
        questions.append(f"To work out {label} I need {listed}.")
    if country:
        questions.append(country)
    if not questions:
        return None
    return " ".join(questions) + " Reply with those details and I'll continue from your original question."


# ── Which message is the request a reply completes ─────────────────────────
def is_own_request(text: str) -> bool:
    """A message that asks for something on its own: the Task Contract finds a
    calculation, journal entry, schedule or official figure in it, or it is a
    task the input requirements know (a loan repayment, an NPV). A reply
    ("₹50,000, GST 18%", "It excludes GST", "UK", "What if it's inclusive?")
    is not one."""
    text = (text or "").strip()
    if len(text.split()) < 3:
        return False
    from app.orchestration.task_contract import build_task_contract
    if any(task.pattern.search(text) for task in TASKS):
        return True
    try:
        contract = build_task_contract(text)
    except Exception:  # noqa: BLE001
        return False
    if contract.message_type in ("context", "correction", "statement", "empty", "reply"):
        return False
    return bool(set(contract.deliverable_kinds()) & {"amount", "journal_entry", "schedule"}
                or any(r.needs_official for r in contract.retrieval))


def current_request_chain(previous_query: str | None, query: str) -> str | None:
    """The request a reply completes: the carried messages from the latest
    one that is a request of its own. None when the current message is
    itself a new request (it starts a new chain)."""
    if is_own_request(query):
        return None
    lines = [line for line in (previous_query or "").split("\n") if line.strip()]
    starts = [index for index, line in enumerate(lines) if is_own_request(line)]
    return "\n".join(lines[starts[-1]:]) if starts else (previous_query or "")


_ACKNOWLEDGEMENT = re.compile(r"^\W*(?:ok(?:ay)?|sure|fine|thanks?|thank\s+you|go\s+ahead|continue|proceed|done|right|"
                              r"alright|yep|cool|great)\W*$", re.I)


def reply_adds_nothing(reply: str, chain: str) -> bool:
    """A reply that cannot have answered the question: an acknowledgement
    ("ok", "sure") or the request's own words again ("₹50,000, GST 18%"
    sent twice). One that names a figure, a country or a treatment counts."""
    text = (reply or "").strip().strip('"\'“”').strip()
    if not text:
        return True
    if _ACKNOWLEDGEMENT.match(text):
        return True
    normal = lambda value: " ".join(re.findall(r"[\w₹£$€%.,]+", value.lower()))  # noqa: E731
    return bool(normal(text)) and normal(text) in normal(chain)
