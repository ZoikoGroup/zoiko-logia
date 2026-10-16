"""A request about something the supplied text does not contain.

"Show the original, incorrect, and correcting entries together. Context:
<a critique of IFRS presentation>" asks for journal entries the text does not
have. Searched and composed like any question, it came back "the sources found
do not state this", and once as an invented "Debit Expense … Credit Cash"
example. The plain answer is that the text holds no entries — so say that,
name the text, and ask for what is needed.

Only a request that refers to supplied material is checked: the text after
"Context:" (a follow-up), a pasted document in the same message, or — when the
request points back ("these entries", "the figures") — the earlier messages.
A general question ("What are adjusting entries?") is never checked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from app.orchestration.websearch import is_pasted_material

_CONTEXT_FOLLOW_UP = re.compile(r"^(?P<ask>.+?[.?!])\s+Context:\s+(?P<material>.+)$", re.S)
_INSTRUCTION_CHARS = 400

# What the request needs from the material.
_WANTS_ENTRIES = re.compile(
    r"\b(?:journal\s+entr(?:y|ies)|(?:original|incorrect|correcting|correction|adjusting|reversing|"
    r"closing|accrual|opening)\s+entr(?:y|ies)|(?:these|those|the)\s+entries|debits?\s+and\s+credits?|"
    r"double[- ]entry)\b",
    re.I,
)
_WANTS_FIGURES = re.compile(
    r"\b(?:P&L|P\s*&\s*L|profit\s+and\s+loss|AR|accounts?\s+receivables?|receivables|balance\s+sheet|cash\s+flow)"
    r"(?:\s+and\s+(?:P&L|AR|receivables|balance\s+sheet))?\s+impacts?\b"
    r"|\bimpacts?\s+on\s+(?:profit|the\s+P&L|receivables|AR|equity|cash)\b"
    r"|\b(?:these|those|the|above)\s+(?:\w+\s+){0,2}(?:figures|amounts|numbers|balances|totals)\b",
    re.I,
)
# A request that points back at earlier messages rather than asking in general.
_POINTS_BACK = re.compile(
    r"\b(?:these|those|the\s+above|above|the\s+same|this|that|the\s+original|the\s+downstream)\b", re.I,
)

# What the material contains.
_HAS_ENTRIES = re.compile(
    r"\bjournal\s+entr|\bDr\.?\s|\bCr\.?\s|\b(?:debit|dr)\b[^\n]{0,80}\b(?:credit|cr)\b", re.I,
)
_AMOUNT = re.compile(
    r"[£$€₹]\s?\d[\d,]*(?:\.\d+)?|\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b|\b(?!(?:19|20)\d{2}\b)\d{4,}(?:\.\d+)?\b"
)


@dataclass(frozen=True)
class MissingInContext:
    wanted: str          # "journal entries" | "figures"
    title: str           # what the user supplied, by its title or first line

    @property
    def message(self) -> str:
        if self.wanted == "journal entries":
            need = ("there are no original, incorrect or correcting entries to show, and no entries "
                    "whose profit-and-loss or receivables impact could be worked out")
            ask = "paste the entries you mean (account, debit, credit and amount)"
        else:
            need = "there are no amounts to work out an impact or total from"
            ask = "paste the figures you mean (item, amount and period)"
        return (f"The text this refers to — “{self.title}” — contains no {self.wanted}, so {need}. "
                f"To go on, {ask}, or ask about what the text itself covers.")


def _title(material: str) -> str:
    for line in material.splitlines():
        line = line.strip().strip("#>*_ ").strip()
        if line:
            return line if len(line) <= 100 else line[:97].rstrip() + "…"
    return "the supplied text"


def _contains(wanted: str, material: str) -> bool:
    if _HAS_ENTRIES.search(material):
        return True            # entries carry the amounts an impact is worked out from
    return wanted == "figures" and len(_AMOUNT.findall(material)) >= 2


def _wanted(ask: str) -> Optional[str]:
    if _WANTS_ENTRIES.search(ask):
        return "journal entries"
    if _WANTS_FIGURES.search(ask):
        return "figures"
    return None


def missing_in_supplied_context(query: str, history: Iterable[str] = ()) -> Optional[MissingInContext]:
    """What the request asks for that the material it refers to lacks, or None."""
    text = (query or "").strip()
    follow_up = _CONTEXT_FOLLOW_UP.match(text)
    if follow_up:
        ask, material = follow_up.group("ask"), follow_up.group("material")
    elif is_pasted_material(text):
        ask, material = text[:_INSTRUCTION_CHARS] + "\n" + text[-_INSTRUCTION_CHARS:], text
    else:
        earlier = [message for message in history if message and message.strip()]
        if not earlier or not _POINTS_BACK.search(text):
            return None
        ask, material = text, "\n\n".join(earlier)
    wanted = _wanted(ask)
    if wanted is None or _contains(wanted, material):
        return None
    return MissingInContext(wanted=wanted, title=_title(material if follow_up or is_pasted_material(text)
                                                         else earlier[0]))
