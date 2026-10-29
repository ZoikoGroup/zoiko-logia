"""A requested diagram whose structure the user did not type.

Diagrams are drawn only from structure stated in the message, through strict
parsers (extraction.py, kroki_diagrams.py), so "Draw the purchase-to-pay
process as a swimlane diagram" — no steps given — drew nothing. Here the
model is asked for the standard structure, written in exactly the typed form
those parsers accept ("Clerk: Raise PO -> Manager: Approve PO"); it is then
appended to the question and goes through the same parsers and renderers.
Nothing else changes: if the structure does not parse completely, there is
no diagram, as before. The answer is labelled as a general illustration.

Charts are never illustrated: their numbers must come from real data.
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable

from app.orchestration import kroki_diagrams as kroki
from app.orchestration.extraction import extract_graph

FLOW = "flow"
_FLOW_REQUEST = re.compile(r"\b(?:flow\s?chart|flow diagram|process flow|process diagram|work\s?flow|process map)\b", re.I)
# "Draw an accounts-payable three-way match flow from PO to payment" (QA case
# E01) names no diagram type, so nothing was drawn and the model typed the
# flow as text art. A cash or fund flow is a figure, not a process.
_FLOW_BETWEEN = re.compile(r"(?<!cash )(?<!fund )(?<!funds )\bflow\s+from\b[^.?!]*\bto\b", re.I)
_DRAW_REQUEST = re.compile(r"\b(?:draw|create|make|show|give|generate|prepare|diagram|illustrate|visuali[sz]e|map)\b", re.I)

# The typed form each kind's parser accepts, with one accounting example.
_FORMATS: dict[str, tuple[str, str]] = {
    FLOW: ("flowchart", "Step one -> Step two -> Step three (one line, steps joined by ->)"),
    kroki.SWIMLANE: ("swimlane diagram", "Clerk: Raise PO -> Manager: Approve PO -> Finance: Pay supplier "
                                        "(every step written as Role: step, steps joined by ->)"),
    kroki.BPMN: ("BPMN diagram", "Raise PO -> Approve PO -> Receive goods -> Pay supplier (steps joined by ->)"),
    kroki.ACTIVITY: ("activity diagram", "Receive invoice -> Match to PO -> Approve invoice -> Pay (steps joined by ->)"),
    kroki.SEQUENCE: ("sequence diagram", "Clerk -> Manager: Request approval; Manager -> Finance: Approve payment "
                                         "(each message as From -> To: message, separated by ;)"),
    kroki.STATE: ("state diagram", "Draft -> Approved: approve; Approved -> Paid: pay "
                                   "(each as From -> To: event, separated by ;)"),
    kroki.ERD: ("ERD", "Customer has many Invoice; Invoice has many Invoice Line "
                       "(only: has many, has one, belongs to; separated by ;)"),
    kroki.CLASS: ("class diagram", "Invoice (number, date, total); Customer has many Invoice; Credit Note is a Invoice "
                                   "(classes with fields in brackets; relations: has many, has one, belongs to, is a, uses, "
                                   "depends on; separated by ;)"),
    kroki.USECASE: ("use case diagram", "Clerk: Enter invoice, Record payment; Manager: Approve payment "
                                        "(Actor: use case, use case; separated by ;)"),
    kroki.COMPONENT: ("component diagram", "ERP sends to Bank Feed; Payroll writes to General Ledger "
                                           "(only: connects to, sends to, receives from, reads from, writes to, syncs with, "
                                           "depends on, uses, calls, feeds; separated by ;)"),
    kroki.DEPLOYMENT: ("deployment diagram", "App Server hosts Ledger App; App Server connects to Database Server "
                                             "(only: hosts, runs on, connects to, backs up to, replicates to, sends to; "
                                             "separated by ;)"),
    kroki.PACKAGE: ("package diagram", "General Ledger contains Journal, Account; Accounts Payable depends on General Ledger "
                                       "(Package contains A, B; or depends on / uses / imports; separated by ;)"),
}
# Kinds whose content is the user's own data (dates, times, object values):
# never invented.
_NOT_ILLUSTRATED = {kroki.GANTT, kroki.TIMING, kroki.OBJECT}

NOTE = ("General illustration: the diagram shows a standard process or structure from established accounting "
        "practice, not your organisation's. Adjust it to your own steps, roles and controls.")
MAX_PAYLOAD_CHARS = 1200

_PROMPT = (
    "You are Kriton, an accounting, audit, tax and finance assistant. Write the standard structure for the "
    "{label} requested below, in exactly this format: {format}.\n"
    "Rules: plain words only; no colons except where the format uses them; no quotes, brackets (unless the "
    "format uses them), semicolons (unless the format uses them), numbers, amounts or dates; each label under "
    "40 characters; between 4 and 12 steps or elements. Reply with the structure only, on one line.\n\n"
    "Request: {question}"
)


def requested_kind(query: str) -> str | None:
    text = query or ""
    for kind, pattern in kroki._REQUESTS.items():  # noqa: SLF001 — the parsers' own request names
        if pattern.search(text):
            return None if kind in _NOT_ILLUSTRATED else kind
    if (_FLOW_REQUEST.search(text) or _FLOW_BETWEEN.search(text)) and _DRAW_REQUEST.search(text):
        return FLOW
    return None


def needs_illustration(query: str) -> bool:
    """A diagram is requested, and the message states no structure for it."""
    return requested_kind(query) is not None and extract_graph(query) is None


async def illustrated_query(query: str, complete: Callable[[str], Awaitable[str]], provider_failure: str) -> str:
    """The question with a standard structure appended in the typed form, or
    "" when none could be produced that the parsers accept completely."""
    kind = requested_kind(query)
    if kind is None:
        return ""
    label, form = _FORMATS[kind]
    try:
        reply = (await complete(_PROMPT.format(label=label, format=form, question=query))) or ""
    except Exception:  # noqa: BLE001 — no illustration is the old behaviour
        return ""
    return _with_structure(query, kind, reply, provider_failure)


# A diagram asked of an attached file is drawn from the file, never from
# general practice: with a file attached nothing was drawn at all, and a
# standard process beside the user's own file would read as theirs.
DOCUMENT_NOTE = ("Diagram drawn from the steps and names in your attached file. "
                 "Check it against the file before relying on it.")
NOT_IN_DOCUMENT_NOTE = ("No diagram was drawn: the attached file does not describe the steps or structure this "
                        "diagram needs. Type the steps in your question to draw them.")
MAX_DOCUMENT_CHARS = 6000
_NONE = "NONE"
_DOCUMENT_PROMPT = (
    "You are Kriton, an accounting, audit, tax and finance assistant. Using ONLY the document below, write the "
    "{label} requested, in exactly this format: {format}.\n"
    "Rules: take every step, role, entity or name from the document's own words; add nothing the document does "
    "not state; plain words only; no colons except where the format uses them; no quotes, brackets (unless the "
    "format uses them), semicolons (unless the format uses them), numbers, amounts or dates; each label under "
    "40 characters; between 3 and 12 steps or elements. If the document does not describe this, reply {none}. "
    "Reply with the structure only, on one line.\n\n"
    "Request: {question}\n\nDocument:\n{document}"
)
# A label is from the document when one of its words is; most must be.
_MIN_GROUNDED_SHARE = 0.8


def _grounded(payload: str, document: str) -> bool:
    text = document.lower()
    labels = [part for part in re.split(r"->|;|,|:|\(|\)", payload) if re.search(r"[A-Za-z]{4,}", part)]
    if not labels:
        return False
    found = sum(any(word in text for word in re.findall(r"[a-z]{4,}", label.lower())) for label in labels)
    return found / len(labels) >= _MIN_GROUNDED_SHARE


async def document_query(query: str, document: str, complete: Callable[[str], Awaitable[str]],
                         provider_failure: str) -> str:
    """The question with the structure the attached file describes appended in
    the typed form, or "" when the file describes none, or the reply does not
    parse completely or is not taken from the file."""
    kind = requested_kind(query)
    if kind is None or not (document or "").strip():
        return ""
    label, form = _FORMATS[kind]
    document = document[:MAX_DOCUMENT_CHARS]
    try:
        reply = (await complete(_DOCUMENT_PROMPT.format(
            label=label, format=form, none=_NONE, question=query, document=document))) or ""
    except Exception:  # noqa: BLE001 — no diagram is the old behaviour
        return ""
    if reply.strip().strip("`.").upper() == _NONE or not _grounded(reply, document):
        return ""
    return _with_structure(query, kind, reply, provider_failure)


def _with_structure(query: str, kind: str, reply: str, provider_failure: str) -> str:
    label, _ = _FORMATS[kind]
    payload = " ".join(reply.strip().strip("`").split())
    if not payload or provider_failure in payload or len(payload) > MAX_PAYLOAD_CHARS or re.search(r"\d", payload):
        return ""
    # The parsers read the text after the first colon that follows the
    # diagram's name, so the question is cut just after that name: anything
    # the user wrote after it ("Swimlane: Clerk / Manager / Finance lanes")
    # was read as the payload, the steps did not parse as lanes, and a plain
    # flow was drawn instead of a swimlane.
    text = (query or "").strip().rstrip(".!?:")
    name = (kroki._REQUESTS[kind] if kind != FLOW else _FLOW_REQUEST).search(text)  # noqa: SLF001
    stem = text[:name.end()] if name else f"{text} as a {label}"
    candidate = f"{stem}: {payload}"
    return candidate if extract_graph(candidate) is not None else ""


# The descriptions say what the user supplied; an illustration supplied none.
_SUPPLIED_WORDING = (
    ("supplied accounting-workflow stages", "standard accounting-workflow stages"),
    ("The validated process visualization below does not add or remove stages.",
     "The process visualization below is a general illustration of a standard process."),
    ("Kriton mapped the accounting relationships exactly as supplied:",
     "Kriton mapped a standard set of accounting relationships:"),
    ("The validated visualization below does not infer additional links.",
     "The visualization below is a general illustration, not your organisation's structure."),
)


def illustration_wording(text: str) -> str:
    for supplied, illustrated in _SUPPLIED_WORDING:
        text = (text or "").replace(supplied, illustrated)
    return text
