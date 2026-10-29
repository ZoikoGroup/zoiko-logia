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
    r"discuss|outline|summari[sz]e|journali[sz]e|quantify|measure|allocate|recogni[sz]e|present|check|verify|review|validate|"
    r"increase|decrease|correct|recalculate|adjust"
)
_COMPUTE_VERB = (r"calculate|compute|determine|prepare|record|journali[sz]e|work\s+out|estimate|reconcile|"
                 r"quantify|measure|allocate|recogni[sz]e|draft|construct")
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
# "that amount", "that lease": a reference when the noun names a figure or an
# item an earlier message set out. Not "conclude that revenue is …", where
# "that" opens a clause after a verb of saying or concluding.
_QUANTITY_NOUN = r"amounts?|figures?|totals?|sums?|balances?|numbers?|results?|values?"
_ITEM_NOUN = (r"profits?|loss(?:es)?|income|payments?|prices?|leases?|contracts?|assets?|liabilit(?:y|ies)|loans?|"
              r"scenarios?|transactions?|entr(?:y|ies)|calculations?|acquisitions?|investments?|projects?|bonds?|"
              r"awards?|options?|grants?|deals?|compan(?:y|ies)|entit(?:y|ies)|clients?|invoices?|machines?|equipment")
_THAT_REFERENCE = re.compile(rf"\b(\w+)?\s*\bthat\s+(?:[a-z][\w-]*\s+)?({_QUANTITY_NOUN}|{_ITEM_NOUN})\b", re.I)
_CLAUSE_VERBS = frozenset("""conclude concludes concluded say says said show shows showed ensure ensures note notes
believe believes mean means assume assumes given so such than state states confirm confirms find finds
argue argues suggest suggests indicate indicates claim claims""".split())
# "it"/"them" as the object of a task: "Show the journal entry for it",
# "record it". Not a dummy subject ("Why is it important to …").
_PRONOUN_OBJECT = re.compile(
    r"\b(?:for|of|on|to|with|from|about|into|record|show|explain|calculate|compute|post|journali[sz]e|allocate|"
    r"recogni[sz]e|book|classify|measure|use|apply|present|disclose|reverse|adjust)\s+(?:it|them)\b", re.I)
# Opens a step on what came before: "Now calculate …", "Next, …".
_CONTINUATION = re.compile(r"^\W*(?:ok(?:ay)?,?\s+)?(?:now|next)\b", re.I)
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
    kind: str                         # first_turn | standalone | scenario_only | follow_up | ambiguous
    reasons: tuple[str, ...] = ()
    relevant_turns: tuple[int, ...] = ()   # history indices, in order
    anchor_turn: int | None = None    # the scenario message the request builds on
    facts: tuple[ResolvedFact, ...] = ()
    # The narrow phrase patterns matched: earlier behaviour (whole history) is kept.
    legacy_follow_up: bool = False
    # A phrase-pattern follow-up whose own chain holds no figures keeps the
    # whole history, as before; otherwise only its chain is used, so a later
    # "And at 30%?" cannot bring back a scenario the user did not choose.
    whole_history: bool = False
    # kind == "ambiguous": the earlier scenarios the reference could mean, and
    # the question to ask instead of choosing one.
    candidates: tuple[int, ...] = ()
    clarification: str = ""
    _history: tuple = field(default=(), repr=False, compare=False)

    @property
    def follows_up(self) -> bool:
        return self.kind == "follow_up"

    def history(self, history: Sequence | None = None) -> list:
        """The earlier messages this request depends on, unchanged and in order."""
        messages = list(history if history is not None else self._history)
        if not self.follows_up:
            return []
        if self.whole_history:
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


# Entities are matched by their whole name. A name token is capitalised and
# may be CamelCase ("Meridian", "EuroTech", "ParentCorp"). An entity is
# introduced with a legal or trade suffix ("Meridian Inc.", "Titan
# Development corp", "Matrix Distributing") or is CamelCase on its own
# ("SubCorp", "Apex BioTech"). Capitalised words alone are never entities:
# "Task for the Bot:" chained ten unrelated questions (22 Oct 2026).
_NAME_TOKEN = r"[A-Z][A-Za-z]*[a-z][A-Za-z]*"
_SUFFIX = (r"(?:Inc|Corp|Corporation|Ltd|Limited|LLC|LLP|plc|PLC|Co|Company|Group|Holdings|Manufacturing|"
           r"Industries|Industrial|Global|Energy|Retailers|Distributing|Partners|Technologies|Bank|Enterprises|"
           r"Trading|Services|(?i:corp|inc|ltd|llc|plc))")
_ENTITY_WITH_SUFFIX = re.compile(rf"\b((?:{_NAME_TOKEN}\s+){{0,2}}{_NAME_TOKEN})\s+{_SUFFIX}\b\.?")
_CAMEL_ENTITY = re.compile(r"\b((?:[A-Z][a-z]+\s+)?[A-Z][a-z]+[A-Z][A-Za-z]*)\b")


def _entities(text: str) -> set[tuple[str, ...]]:
    """Entities the text introduces, each as its full tuple of name tokens."""
    found: set[tuple[str, ...]] = set()
    for pattern in (_ENTITY_WITH_SUFFIX, _CAMEL_ENTITY):
        for match in pattern.finditer(text or ""):
            # The whole name is the identity: "Vanguard Industrial" and
            # "Vanguard Energy" are different companies.
            tokens = tuple(word for word in match.group(1).split() if word not in _NOT_NAMES)
            if tokens:
                found.add(tokens)
    # "Apex BioTech" also matches "BioTech" alone: keep the longest name only.
    return {entity for entity in found
            if not any(other != entity and len(other) > len(entity) and other[-len(entity):] == entity for other in found)}


def _mentions(current: str, entity: tuple[str, ...], current_entities: set[tuple[str, ...]]) -> bool:
    """The message refers to an earlier entity: by its full name, or by its
    first name when nothing in the message names a different entity with the
    same first name ("Apex BioTech" is not "Apex Manufacturing")."""
    # A different entity with the same first name in this message decides it,
    # even though the shared word appears ("Apex BioTech" contains "Apex").
    if any(other != entity and other[0] == entity[0] for other in current_entities):
        return False
    if re.search(r"\b" + r"\s+".join(map(re.escape, entity)) + r"\b", current or ""):
        return True
    return bool(re.search(rf"\b{re.escape(entity[0])}\b", current or ""))


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
    earlier message describes ("this lease" ↔ "a 5-year equipment lease";
    "that amount" ↔ an earlier message's figure)."""
    earlier_words = _content_words(earlier)
    for match in _DEMONSTRATIVE.finditer(current or ""):
        # Modifiers after the referent are not its identity: "those facts
        # alone" must not link to an earlier claim containing "alone".
        words = match.group(1).split()
        referent = next((word for word in words if word.lower() not in {"particular", "specific", "aforementioned"}), "")
        prefix = current[:match.start()]
        if _content_words(referent) & _content_words(prefix):
            continue
        local_scenario = any(not asks_something(sentence) and len(sentence.split()) >= 8
                             for sentence in _sentences(prefix))
        if local_scenario and referent.lower() in {"fact", "facts", "scenario", "result", "results", "figures", "amounts"}:
            continue
        if _content_words(referent) & earlier_words:
            return True
    for match in _THAT_REFERENCE.finditer(current or ""):
        if (match.group(1) or "").lower() in _CLAUSE_VERBS:
            continue
        noun = match.group(2)
        if re.fullmatch(_QUANTITY_NOUN, noun, re.I):
            if scenario_figures(earlier):
                return True
        elif _content_words(noun) & earlier_words:
            return True
    return False


def _quantity_reference(text: str) -> bool:
    """"that amount", "this figure", "the above total": a reference to a
    figure that names nothing else to identify it by."""
    for match in _THAT_REFERENCE.finditer(text or ""):
        if (match.group(1) or "").lower() not in _CLAUSE_VERBS and re.fullmatch(_QUANTITY_NOUN, match.group(2), re.I):
            return True
    return bool(re.search(rf"\b(?:this|these|those|the\s+(?:above|same|said))\s+(?:{_QUANTITY_NOUN})\b", text or "", re.I))


def _clarification(history: Sequence, roots: list[int]) -> str:
    """A short question naming each candidate scenario by its first figure."""
    lines = ["Earlier messages set out more than one scenario with figures:"]
    for index in roots[:3]:
        text = " ".join(_content(history[index]).split())
        figures = scenario_figures(text)
        snippet = text if len(text) <= 70 else text[:67].rstrip() + "…"
        lines.append(f"• {figures[0] if figures else 'figures'} — “{snippet}”")
    # Ends with the question, so the reply is read as its answer.
    lines.append("Which amount or scenario do you mean?")
    return "\n".join(lines)


def scenario_figures(text: str) -> list[str]:
    """Figures that set out a scenario: amounts and counts, not percentages or
    rates, which are parameters of a task ("…the tax on that amount at 25%")."""
    return [figure for figure in amounts(text) if not figure.rstrip().endswith("%")]


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

    # Identity: an entity the message names, matched by its whole name.
    current_entities = _entities(current)
    earlier_entities = [(index, _entities(text)) for index, text in users]
    known = {entity for _, entities in earlier_entities for entity in entities}
    for index, entities in reversed(earlier_entities):
        for entity in sorted(entities):
            if _mentions(current, entity, current_entities):
                return index, [f"named_party:{' '.join(entity)}"], False
    own = scenario_figures(current)
    # A different entity with its own figures is a new task, whatever else its
    # wording shares with earlier messages ("Apex BioTech" after "Apex
    # Manufacturing").
    if current_entities - known and len(own) >= 2:
        return None, [], False
    with_figures = [(index, text) for index, text in users if scenario_figures(text)]
    supplied_reference = re.search(
        r'\b(?:my|our|the)\s+(?:previously\s+)?(?:supplied|provided|reported|original)\s+(?:figures|amounts|data|results)\b'
        r'|\b(?:original\s+and\s+(?:corrected|revised)|(?:corrected|revised)\s+and\s+original)\s+results\b',
        current or '', re.I)
    if supplied_reference and not own and with_figures:
        return with_figures[-1][0], ["supplied_input_reference"], False
    # "Now calculate … for that lease" after an unrelated break-even question
    # was continued from the break-even turn: "Now" was read before "that
    # lease". A reference naming an earlier turn that the previous one does not
    # describe links to that earlier turn (27 Oct 2026).
    if not _MONEY.search(current or "") and not _refers_to(current, previous_text):
        for index, text in reversed(users[:-1]):
            if _refers_to(current, text):
                return index, ["demonstrative_reference"], False
    # The previous message's own scenario, not merely the latest message with
    # figures: after a clarification choice those differ.
    if _CONTINUATION.match(current or "") and asks_something(current) and with_figures:
        return previous_index, ["continuation"], False
    if re.match(r'^\W*(?:increase|decrease|correct|recalculate)\b', current or '', re.I) and with_figures:
        return previous_index, ["scenario_revision"], False
    if _PRONOUN_OBJECT.search(current or "") and not own and with_figures:
        return previous_index, ["pronoun_reference"], False
    # A reference to something set out earlier ("this lease", "that amount").
    # A message bringing its own money figures sets out its own scenario
    # instead: "A manufacturer recorded a £75,000 sale …".
    if not _MONEY.search(current or ""):
        for index, text in reversed(users):
            if _refers_to(current, text):
                return index, ["demonstrative_reference"], False

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
    # A computation with no figures of its own works on the previous ones
    # ("compute the cash flow step by step"). A conceptual question ("explain
    # why auditors treat revenue as a fraud risk") does not inherit them.
    # "Why is it important to reconcile …" asks for an explanation, whatever its verb.
    computes = (bool(re.search(rf"\b(?:{_COMPUTE_VERB})\b", current or "", re.I))
                and not re.match(r"^\W*why\b", current or "", re.I))
    if asks and computes and not own and scenario_figures(previous_text):
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
    # Questions answered by a choice: the clarification after them lists every
    # candidate scenario and is not passed on once answered.
    answered_questions: set[int] = set()

    def root(index: int) -> int:
        seen = set()
        while parent.get(index) is not None and index not in seen:
            seen.add(index)
            index = parent[index]
        return index

    def candidate_scenarios(question: str, earlier: list[tuple[int, str]]) -> list[int]:
        """Earlier scenarios a bare "that amount" could mean, most recent first;
        empty when it is clear. Clear: one scenario with figures, or the message
        just before states exactly one amount."""
        if not _quantity_reference(question) or not earlier:
            return []
        # The message just before settles it when it states exactly one amount,
        # or when it set out a scenario and asked nothing and the reference is
        # to its figures as a set ("…using these figures"). A single "that
        # amount" beside a scenario of several amounts is still asked about.
        previous = earlier[-1][1]
        collective = re.search(rf"\b(?:these|those|the\s+(?:above|same|said))\s+(?:{_QUANTITY_NOUN})\b", question, re.I)
        if len(_MONEY.findall(previous)) == 1 or (collective and is_scenario_only(previous)):
            return []
        roots = list(dict.fromkeys(root(index) for index, text in reversed(earlier) if scenario_figures(text)))
        return roots if len(roots) > 1 else []

    def choice(reply: str, position: int) -> int | None:
        """The scenario a short reply picks for the ambiguous question just
        before it (position is the reply's place among user turns). Read from
        the user's own messages: the page does not send the clarification back."""
        if position < 1 or not _is_choice_reply(reply):
            return None
        options = candidate_scenarios(user_turns[position - 1][1], user_turns[:position - 1])
        chosen = [index for index in options if _chooses(reply, _content(history[index]))]
        return chosen[0] if options and len(chosen) == 1 else None

    for position, (index, text) in enumerate(user_turns):
        picked = choice(text, position)
        if picked is not None:
            # The question and its answer belong to the chosen scenario, so
            # later follow-ups stay on it.
            parent[user_turns[position - 1][0]] = picked
            parent[index] = user_turns[position - 1][0]
            answered_questions.add(user_turns[position - 1][0])
            continue
        anchor, _, _ = _depends_on(text, user_turns[:position], history[:index], legacy_follow_up, standalone)
        parent[index] = anchor

    picked = choice(query, len(user_turns))
    if picked is not None:
        question_index = user_turns[-1][0]
        parent[question_index] = picked
        answered_questions.add(question_index)
        anchor, reasons, legacy = question_index, ["clarification_reply", f"chose_scenario:{picked}"], False
    else:
        anchor, reasons, legacy = _depends_on(query, user_turns, history, legacy_follow_up, standalone)
    if anchor is None:
        kind = "scenario_only" if is_scenario_only(query) else "standalone"
        return ConversationResolution(kind=kind, _history=tuple(history))

    chain_roots = [root(anchor)]
    anchor_extra: list[int] = []
    if not legacy and not (reasons and reasons[0].startswith(("named_party", "clarification_reply"))):
        options = candidate_scenarios(query, user_turns)
        if options:
            # Several earlier scenarios could be meant: ask, never guess.
            return ConversationResolution(
                kind="ambiguous", reasons=("ambiguous_reference",), candidates=tuple(options),
                clarification=_clarification(history, options), _history=tuple(history),
            )

    chain_users = [index for index, _ in user_turns if root(index) in chain_roots or index in chain_roots + anchor_extra]
    relevant: list[int] = []
    for index in chain_users:
        relevant.append(index)
        # The reply to that turn, when it is the very next message (not a
        # clarification that has been answered).
        if (index + 1 < len(history) and _role(history[index + 1]) == "assistant"
                and index not in answered_questions):
            relevant.append(index + 1)
    facts = tuple(ResolvedFact(turn_index=index, text=figure)
                  for index in chain_users for figure in amounts(_content(history[index])))
    return ConversationResolution(
        kind="follow_up", reasons=tuple(reasons), relevant_turns=tuple(sorted(set(relevant))),
        anchor_turn=anchor, facts=facts, legacy_follow_up=legacy,
        whole_history=legacy and not any(scenario_figures(_content(history[index])) for index in chain_users),
        _history=tuple(history),
    )


def _is_choice_reply(text: str) -> bool:
    """A short answer naming a figure or a scenario, not a new task: "The
    $180,000 profit.", "I mean the Nexus contract"."""
    words = re.findall(r"[A-Za-z$£€₹\d][\w,.$£€₹%-]*", text or "")
    return 0 < len(words) <= 12 and not re.search(rf"\b(?:{_COMPUTE_VERB})\b", text or "", re.I)


def _chooses(reply: str, scenario: str) -> bool:
    """The reply names this scenario: one of its figures, or its wording."""
    digits = lambda value: re.sub(r"[^\d.]", "", value)  # noqa: E731
    reply_figures = {digits(figure) for figure in amounts(reply)}
    if reply_figures & {digits(figure) for figure in amounts(scenario)}:
        return True
    return bool(_content_words(reply) & _content_words(scenario))
