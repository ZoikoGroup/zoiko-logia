"""Conversation resolution: which earlier turns a message depends on.

Replaces the narrow follow-up phrase gate ("what about…", "and…", "same
figures…") as the single decision for whether earlier turns reach retrieval,
planning and composition. On 22 Oct 2026 ten of ten scenario follow-ups failed
that gate — "Calculate the amount of Goodwill resulting from this
acquisition" one message after the acquisition facts — and were answered
"provide the purchase price" or "the sources do not establish this".

Signals are structural, not exact questions:
  • the previous user message stated a scenario and asked nothing;
  • a named party ("Meridian", "Apex Corp.") recurs from an earlier message;
  • a demonstrative reference ("this lease", "the award") names something an
    earlier message describes;
  • a task request carrying no figures follows a message that has them;
  • a short reply answers the assistant's own question;
  • the existing high-confidence phrase patterns still count.

Only the turns of the linked scenario are returned — its own follow-ups and
the replies to them — never an older, unrelated scenario. Original messages
are passed through unchanged, and every figure is traced to its turn. Nothing
is invented: a message that depends on nothing stays standalone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

# Earlier user turns considered; older turns are outside any likely reference.
MAX_USER_TURNS = 12

_AMOUNT = re.compile(
    r"[£$€₹]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:million|billion|bn|m|k)\b)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s?%"
    r"|\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b"
    r"|\b\d+(?:\.\d+)?\s?(?:USD|GBP|EUR|INR|AED)\b",
    re.I,
)
_REQUEST_VERB = (
    r"calculate|compute|determine|explain|identify|classify|prepare|provide|show|state|describe|evaluate|"
    r"assess|record|recommend|compare|list|analy[sz]e|work\s+out|estimate|reconcile|draft|write|give|tell|"
    r"discuss|outline|summari[sz]e|journali[sz]e|quantify|measure|allocate|recogni[sz]e|present"
)
# A sentence that asks: a question mark, a leading request verb or question
# word, or a request verb straight after an introductory phrase
# ("Using the indirect method, compute …").
_ASK_START = re.compile(
    rf"^\W*(?:[a-z ]{{0,30}}question\s*:\s*)?(?:please\s+|kindly\s+|now\s+|also\s+|and\s+|then\s+)?"
    rf"(?:{_REQUEST_VERB}|what|how|why|which|when|where|who|whether|is|are|does|do|did|can|could|should|would|will|"
    rf"has|have)\b",
    re.I,
)
_ASK_AFTER_COMMA = re.compile(rf",\s*(?:please\s+)?(?:{_REQUEST_VERB})\b", re.I)
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Z•\-*(\d])|\n+")
# "that" and "such" are left out: mostly a conjunction ("conclude that revenue
# is misstated") and "such as", not a reference to an earlier message.
_DEMONSTRATIVE = re.compile(
    r"\b(?:this|these|those|the\s+(?:above|same|said|preceding))\s+((?:[A-Za-z][\w-]*\s+){0,2}[A-Za-z][\w-]*)",
    re.I,
)
_MONEY = re.compile(r"[£$€₹]\s?\d|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|GBP|EUR|INR|AED)\b", re.I)
# Capitalised words that are not party names.
_NOT_NAMES = frozenset("""
The This That These Those A An In On At For From To By Of With Without During Using Under Based After Before
If When While However Additionally Also And But Or Year Years Net Income Total Accounts Account Cash Inventory
Assets Asset Liabilities Equity Revenue Statement Statements Balance Sheet Profit Loss Operating Activities
Provided Indirect Direct Method January February March April May June July August September October November
December Monday Tuesday Wednesday Thursday Friday Saturday Sunday Practical Question Calculate Explain Identify
Classify Determine Describe State Provide Show Compute Using Prepare Record Is Are Does Do How What Why Which
Black Scholes Goodwill Step Model Standard Standards Opinion Payable Payables Receivable Receivables Expense
Expenses Depreciation Tax Taxes Deferred Current Noncurrent Non Lease Leases Right Use Interest Rate Rates
Inc Corp Ltd Llc Plc Co Company Group Holdings
""".split())
_STOP = frozenset("""
about above after again against also among amount amounts another before being below between both could
during each either every first following from further given have having here into itself just more most
much must other over provide provided same should show since some such than that their them then there these
they this those through under until upon using very what when where which while whom whose will with within
without would year years year's your yours calculate compute determine explain identify classify describe
state prepare record including include includes total company companies amount using based assume assuming
please step step-by-step method under value values figure figures number numbers question answer
""".split())


@dataclass(frozen=True)
class ResolvedFact:
    """A figure the current request may rely on, and the turn it came from."""
    turn_index: int     # index into the conversation history
    text: str           # the figure exactly as the user wrote it


@dataclass(frozen=True)
class ConversationResolution:
    kind: str                         # first_turn | standalone | scenario_only | follow_up
    reasons: tuple[str, ...] = ()
    relevant_turns: tuple[int, ...] = ()   # history indices, in order
    anchor_turn: int | None = None    # the scenario message the request builds on
    facts: tuple[ResolvedFact, ...] = ()
    # The narrow phrase patterns matched: earlier behaviour (whole history) is kept.
    legacy_follow_up: bool = False
    _history: tuple = field(default=(), repr=False, compare=False)

    @property
    def follows_up(self) -> bool:
        return self.kind == "follow_up"

    def history(self, history: Sequence | None = None) -> list:
        """The earlier messages this request depends on, unchanged and in order."""
        messages = list(history if history is not None else self._history)
        if not self.follows_up:
            return []
        if self.legacy_follow_up:
            return messages
        return [messages[index] for index in self.relevant_turns if index < len(messages)]

    def scenario_text(self) -> str:
        """The user's own scenario messages for this request, oldest first."""
        messages = self.history()
        return "\n\n".join(_content(m) for m in messages if _role(m) == "user")

    def summary(self) -> dict:
        """Trace record: no message text, only turn positions and figures."""
        return {
            "kind": self.kind, "reasons": list(self.reasons), "relevant_turns": list(self.relevant_turns),
            "anchor_turn": self.anchor_turn, "legacy_follow_up": self.legacy_follow_up,
            "facts": [{"turn": fact.turn_index, "figure": fact.text} for fact in self.facts],
        }


def _role(message) -> str:
    return getattr(message, "role", None) or (message.get("role") if isinstance(message, dict) else "") or ""


def _content(message) -> str:
    return getattr(message, "content", None) or (message.get("content") if isinstance(message, dict) else "") or ""


def amounts(text: str) -> list[str]:
    return [match.group(0).strip() for match in _AMOUNT.finditer(text or "")]


def _sentences(text: str) -> list[str]:
    return [part.strip(" \t•*-") for part in _SENTENCES.split(text or "") if part.strip(" \t•*-")]


def asks_something(text: str) -> bool:
    """The message contains a question or a request."""
    if "?" in (text or ""):
        return True
    return any(_ASK_START.match(sentence) or _ASK_AFTER_COMMA.search(sentence) for sentence in _sentences(text))


def is_scenario_only(text: str) -> bool:
    """Facts set out with nothing asked: the question follows in the next message."""
    words = re.findall(r"[A-Za-z]+", text or "")
    return not asks_something(text) and (bool(amounts(text)) or len(words) >= 25) and len(words) >= 8


def _names(text: str) -> set[str]:
    """Party names: capitalised words that are not sentence openers or common terms."""
    found = set()
    for sentence in _sentences(text):
        for match in re.finditer(r"\b([A-Z][a-z]{2,})\b", sentence):
            if match.start() == 0 or match.group(1) in _NOT_NAMES:
                continue
            found.add(match.group(1))
        lead = re.match(r"^\W*([A-Z][a-z]{2,})\s+(?:Inc|Corp|Ltd|LLC|Co|plc|Group|Manufacturing|Holdings)\b", sentence)
        if lead and lead.group(1) not in _NOT_NAMES:
            found.add(lead.group(1))
    return found


# Framework and country acronyms appear in unrelated questions alike.
_GENERIC_ACRONYMS = frozenset({"ASC", "GAAP", "IFRS", "IAS", "ISA", "FRS", "AICPA", "FASB", "IASB", "PCAOB",
                               "US", "UK", "EU", "USD", "GBP", "EUR", "INR", "AED", "VAT", "GST", "HMRC", "IRS"})


def _stem(word: str) -> str:
    """Light suffix stripping, so "sampling" and "sample" meet."""
    word = word.lower()
    for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ed", "es", "s", "e"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _content_words(text: str) -> set[str]:
    words = {_stem(word) for word in re.findall(r"[A-Za-z][A-Za-z-]{3,}", text or "")
             if word.lower() not in _STOP}
    acronyms = {word for word in re.findall(r"\b[A-Z]{2,6}\b", text or "") if word not in _GENERIC_ACRONYMS}
    return {word for word in words if len(word) >= 4 and word not in _STOP} | acronyms


def _refers_to(current: str, earlier: str) -> bool:
    """A demonstrative reference in the current message names something the
    earlier message describes ("this lease" ↔ "a 5-year equipment lease")."""
    earlier_words = _content_words(earlier)
    for match in _DEMONSTRATIVE.finditer(current or ""):
        if _content_words(match.group(1)) & earlier_words:
            return True
    return False


def _clarification_reply(current: str, history: Sequence) -> bool:
    """A short answer to the assistant's own question ("UK", "2025-26")."""
    if not history or _role(history[-1]) != "assistant":
        return False
    asked = _content(history[-1]).rstrip()
    return asked.endswith("?") and len(re.findall(r"\w+", current or "")) <= 6 and not asks_something(current)


def _depends_on(current: str, users: list[tuple[int, str]], history: Sequence,
                legacy: Callable[[str], bool] | None, standalone: Callable[[str], bool] | None
                ) -> tuple[int | None, list[str], bool]:
    """(anchor turn index, reasons, legacy) for one message against earlier user turns."""
    if not users:
        return None, [], False
    previous_index, previous_text = users[-1]
    reasons: list[str] = []
    if legacy is not None and legacy(current):
        return previous_index, ["follow_up_phrase"], True
    if _clarification_reply(current, history):
        return previous_index, ["clarification_reply"], False

    names = _names(current)
    for index, text in reversed(users):
        shared = names & _names(text)
        if shared:
            return index, [f"named_party:{sorted(shared)[0]}"], False
    # A message bringing its own money figures sets out its own scenario; only
    # a named party links it back. "A manufacturer recorded a £75,000 sale …"
    # after an income statement is a new audit question.
    if not _MONEY.search(current or ""):
        for index, text in reversed(users):
            if _refers_to(current, text):
                return index, ["demonstrative_reference"], False

    own = amounts(current)
    # A message with its own figures and no reference is a new task, not a follow-up.
    if standalone is not None and standalone(current):
        return None, [], False
    if len(own) >= 2:
        return None, [], False
    asks = asks_something(current)
    task = bool(re.search(rf"\b(?:{_REQUEST_VERB})\b", current or "", re.I))
    if is_scenario_only(previous_text) and asks:
        # A stated scenario is followed by its question. The exception is a
        # lookup that shares nothing with it: "What is the current UK VAT
        # threshold?" after a payroll scenario is a new question.
        from app.orchestration.calculation_service import needs_lookup
        overlap = _content_words(current) & _content_words(previous_text)
        if overlap or (not own and not needs_lookup(current)):
            reasons.append("answers_previous_scenario")
            return previous_index, reasons, False
    if asks and task and not own and amounts(previous_text):
        return previous_index, ["task_without_own_figures"], False
    return None, [], False


def resolve_conversation(query: str, history: Sequence | None, *,
                         legacy_follow_up: Callable[[str], bool] | None = None,
                         standalone: Callable[[str], bool] | None = None) -> ConversationResolution:
    """Decide which earlier turns the current message depends on."""
    history = list(history or [])
    user_turns = [(index, _content(m)) for index, m in enumerate(history) if _role(m) == "user" and _content(m).strip()]
    user_turns = user_turns[-MAX_USER_TURNS:]
    if not user_turns:
        return ConversationResolution(kind="first_turn", _history=tuple(history))

    # Link every earlier user turn to the one it built on, so a chain
    # (scenario → question → "and the journal entry?") stays together.
    parent: dict[int, int | None] = {}
    for position, (index, text) in enumerate(user_turns):
        anchor, _, _ = _depends_on(text, user_turns[:position], history[:index], legacy_follow_up, standalone)
        parent[index] = anchor

    anchor, reasons, legacy = _depends_on(query, user_turns, history, legacy_follow_up, standalone)
    if anchor is None:
        kind = "scenario_only" if is_scenario_only(query) else "standalone"
        return ConversationResolution(kind=kind, _history=tuple(history))

    def root(index: int) -> int:
        seen = set()
        while parent.get(index) is not None and index not in seen:
            seen.add(index)
            index = parent[index]
        return index

    chain_root = root(anchor)
    chain_users = [index for index, _ in user_turns if root(index) == chain_root]
    relevant: list[int] = []
    for index in chain_users:
        relevant.append(index)
        # The reply to that turn, when it is the very next message.
        if index + 1 < len(history) and _role(history[index + 1]) == "assistant":
            relevant.append(index + 1)
    facts = tuple(ResolvedFact(turn_index=index, text=figure)
                  for index in chain_users for figure in amounts(_content(history[index])))
    return ConversationResolution(
        kind="follow_up", reasons=tuple(reasons), relevant_turns=tuple(sorted(set(relevant))),
        anchor_turn=anchor, facts=facts, legacy_follow_up=legacy, _history=tuple(history),
    )
