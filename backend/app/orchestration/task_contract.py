"""Task Contract, Stage A (shadow only).

One deterministic record of what a request asks for, built once from the
models and checks that already exist, instead of each stage reading the raw
message again (architecture assessment, 29 Oct 2026):

- case scope and history facts: conversation_resolver.ConversationResolution
  (relevant_turns, anchor_turn, ResolvedFact) and what
  conversation.with_essential_context would add beyond it;
- request parts: the intent_planner.SubTask shape, filled from
  service.request_parts / websearch.sub_questions on the request part of the
  message (case_text.request_part);
- missing inputs: the existing input checks (input_requirements) and the
  calculator's own clarification;
- deliverables: answer_coverage.RequestedDeliverable;
- calculation requirements: calculations.schemas.CalculationTaskState from
  the CalculationResult;
- applicable validations: the validation categories of the assessment.

Stage A records the contract (kriton.task_contract log; a JSON-lines file
only when KRITON_TASK_CONTRACT_SHADOW is on). Nothing in the pipeline reads
it, so answers are unchanged. No model, network or database call is made.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.orchestration.answer_coverage import RequestedDeliverable
from app.orchestration.calculations.schemas import CalculationResult, CalculationTaskState
from app.orchestration.intent_planner import SubTask

logger = logging.getLogger("kriton.task_contract")
_LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "task-contract-shadow.jsonl"
CONTRACT_VERSION = "task-contract-a1"

MessageType = Literal["request", "case_study", "reply", "context", "correction", "statement", "empty"]
Validation = Literal[
    "input_validity", "numerical_correctness", "numerical_provenance", "accounting_treatment",
    "deliverable_completeness", "case_integrity", "visualization_suitability", "final_disposition",
]
DeliverableKind = Literal[
    "amount", "allocation", "journal_entry", "schedule", "classification", "explanation", "procedures",
    "report_wording", "citation", "chart", "financial_statements",
]


class ContractFact(BaseModel):
    """A figure the request may rely on, with where it came from. The only
    new record: ResolvedFact covers history only and CalculationInput covers
    what a calculator parsed, neither says which case a figure belongs to."""
    model_config = ConfigDict(frozen=True)

    text: str
    source: Literal["request", "background", "history", "calculator_input"]
    turn: Optional[int] = None
    in_scope: bool = True


class CaseScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    # Stage B: the message sets out a case of its own; no earlier turn is in
    # its scope (starts_new_case). The pipeline uses this decision.
    new_case: bool = False
    resolution_kind: str
    relevant_turns: list[int] = Field(default_factory=list)
    anchor_turn: Optional[int] = None
    explicit_reply: bool = False
    history_turns: int = 0
    # Earlier turns with_essential_context would add that the resolver did not
    # choose: where another case's facts can enter (defect class 4).
    essential_turns_outside_scope: list[int] = Field(default_factory=list)


class OutputConstraints(BaseModel):
    model_config = ConfigDict(frozen=True)

    statements_requested: bool = False
    # statement_rules.is_statement_request fires on the whole message but not
    # on its request part: background wording, not a request (defect class 3).
    statement_words_in_background_only: bool = False
    chart_requested: bool = False
    # Stage C: a VAT/GST amount is to be produced (vat_amount_requested).
    vat_amount_requested: bool = False
    # Stage F (3 Nov 2026): the report headings the request lists
    # (answer_coverage.report_section_names on the whole message, as before).
    report_sections: list[str] = Field(default_factory=list)


class RequestedOutput(BaseModel):
    """One output a part asks to be produced, by name: "Calculate annual
    depreciation and the carrying amount after three years" asks for two
    amounts. The finaliser checks each is in the answer (Stage F)."""
    model_config = ConfigDict(frozen=True)

    part: int
    kind: str
    name: str


class TaskContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = CONTRACT_VERSION
    message_type: MessageType
    request_fingerprint: str
    has_background: bool
    case: CaseScope
    parts: list[SubTask] = Field(default_factory=list)
    facts: list[ContractFact] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    invalid_inputs: list[str] = Field(default_factory=list)
    deliverables: list[RequestedDeliverable] = Field(default_factory=list)
    # Stage F: each output the parts ask for, by name (requested_outputs).
    outputs: list[RequestedOutput] = Field(default_factory=list)
    calculation: Optional[CalculationTaskState] = None
    calculation_status: str = "not_run"
    output_constraints: OutputConstraints = Field(default_factory=OutputConstraints)
    validations: list[Validation] = Field(default_factory=list)
    # Stage C-1 (shadow): what each part needs retrieved. Recorded only.
    retrieval: list["RetrievalRequirement"] = Field(default_factory=list)
    # Stage S2 (shadow): whether every claim must be cited from governed or
    # official sources, computed as the pipeline computes it
    # (verification_service.requires_authoritative_evidence). Recorded only;
    # the pipeline still computes and uses its own. None when not computed.
    authority_required: Optional[bool] = None

    def deliverable_kinds(self) -> list[str]:
        return [d.description.split(":", 1)[0] for d in self.deliverables]

    def with_calculation(self, result: CalculationResult | None) -> "TaskContract":
        """The contract with what the calculator chain matched (or did not)."""
        if result is None:
            return self
        state = None
        if result.matched:
            state = CalculationTaskState(task_type=list(result.formula_ids), inputs=list(result.inputs),
                                         derived_results=list(result.outputs), assumptions=list(result.notes))
        missing = list(self.missing_inputs)
        if result.status == "clarification_required" and result.message and result.message not in missing:
            missing.append(result.message)
        facts = list(self.facts) + [ContractFact(text=item.display_value, source="calculator_input")
                                    for item in result.inputs if item.display_value]
        validations = list(self.validations)
        if result.matched and "numerical_correctness" not in validations:
            validations.insert(1, "numerical_correctness")
        return self.model_copy(update={"calculation": state, "calculation_status": result.status,
                                       "missing_inputs": missing, "facts": facts, "validations": validations})

    def summary(self) -> dict:
        """The log record: structure and counts, never message text."""
        return {
            "version": self.version, "message_type": self.message_type, "fingerprint": self.request_fingerprint,
            "has_background": self.has_background, "case": self.case.model_dump(),
            "parts": [part.kind for part in self.parts], "deliverables": self.deliverable_kinds(),
            "outputs": [o.kind for o in self.outputs],
            "facts": {source: sum(f.source == source for f in self.facts)
                      for source in ("request", "background", "history", "calculator_input")},
            "facts_out_of_scope": sum(not f.in_scope for f in self.facts),
            "missing_inputs": len(self.missing_inputs), "calculation": self.calculation.task_type if self.calculation else [],
            "calculation_status": self.calculation_status, "constraints": self.output_constraints.model_dump(),
            "validations": list(self.validations),
            "retrieval": [{"official": r.needs_official, "fact": r.fact_type, "jurisdictions": r.jurisdictions,
                           "publisher": r.publisher, "connector": r.connector, "official_pages": r.official_pages,
                           "topics": r.topics, "period": r.period.kind}
                          for r in self.retrieval],
            "authority_required": self.authority_required,
        }


# ── Deliverables: what each part asks to be produced ─────────────────────────
# Ordered; a part may ask for several ("Calculate … and pass the journal").
_DELIVERABLE_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("journal_entry", re.compile(r"\bjournal\b|\b(?:pass|record|post)\s+(?:the\s+|an?\s+)?(?:necessary\s+|correcting\s+)?entr(?:y|ies)\b", re.I)),
    ("allocation", re.compile(r"\ballocat\w*\b", re.I)),
    ("schedule", re.compile(r"\b(?:schedule|amorti[sz]ation\s+table|liability\s+table)\b", re.I)),
    ("amount", re.compile(r"\b(?:calculate|compute|quantify|work\s+out|how\s+much|reconstruct\s+the\s+correct|"
                          r"what\s+is\s+the\s+(?:amount|impact|total)|determine\s+the\s+(?:amount|impact))\b"
                          # a percentage of an amount: "What is 18% GST on ₹50,000?"
                          r"|\d+(?:\.\d+)?\s*%\s*(?:[A-Za-z]+\s+){0,2}(?:on|of)\s+[£$€₹]\s?\d", re.I)),
    ("classification", re.compile(r"\bclassif\w*\b", re.I)),
    ("procedures", re.compile(r"\bprocedures?\b", re.I)),
    ("report_wording", re.compile(r"\b(?:auditor'?s\s+report|report\s+should\s+say|form\s+3cd|qualify\s+(?:your|the)\s+audit\s+report)\b", re.I)),
    ("citation", re.compile(r"\bcite\b|\bwhich\s+section\b", re.I)),
    ("chart", re.compile(r"\b(?:chart|graph|plot)\b", re.I)),
    ("explanation", re.compile(r"\b(?:explain|why|how\s+(?:does|should|is)|describe|discuss|evaluate|assess|"
                               r"analy[sz]e|critique|justify|identify|specify|outline|is\s+the\s+\w+|can\s+the\s+\w+|"
                               r"what\s+(?:are|is|disclosures|observations))\b", re.I)),
)
_STANDARD = re.compile(r"\b(?:IFRS|IAS|Ind\s?AS|ASC|FRS|GAAP|ISA)\b", re.I)


def _part_deliverables(text: str) -> list[str]:
    from app.orchestration.statement_rules import is_statement_request
    kinds = [kind for kind, pattern in _DELIVERABLE_RULES if pattern.search(text)]
    # The existing detector, on this part alone: "3. Explain how the lease
    # cost is presented in the income statement" asks about presentation
    # (its "Explain" is not preparing), not for statements (defect class 3).
    if is_statement_request(_PART_LABEL.sub("", text, count=1)):
        kinds.append("financial_statements")
    return list(dict.fromkeys(kinds)) or ["explanation"]


# A question's own label ("• Q2.1 (Revenue Audit):", "3.") is not a figure:
# request_parts read its digits as one and called every part a calculation.
_PART_LABEL = re.compile(r"^\s*(?:[-*•]\s*)?(?:Q\d+(?:\.\d+)*|\d+[.)])?\s*(?:\([^)\n]{0,60}\))?\s*:?\s*", re.I)


_INLINE_NUMBER = re.compile(r"(?:^|(?<=[\s:]))(\d{1,2})[.)]\s+(?=[A-Z])")


def _inline_items(text: str) -> list[str]:
    """The items of a numbered list written on one line, when the numbers run
    1, 2, … in order (at least two); [] otherwise."""
    marks = [m for m in _INLINE_NUMBER.finditer(text or "")]
    run, expected = [], 1
    for mark in marks:
        if int(mark.group(1)) == expected:
            run.append(mark)
            expected += 1
    if len(run) < 2 or "\n" in (text or "")[run[0].start():run[-1].start()]:
        return []
    bounds = [m.start() for m in run] + [len(text)]
    return [text[start:end].strip() for start, end in zip(bounds, bounds[1:]) if text[start:end].strip()]


def _part(text: str) -> SubTask:
    """One part in the SubTask shape, classified by service.request_parts."""
    from app.orchestration.service import request_parts
    classified = request_parts(_PART_LABEL.sub("", text, count=1), calculated=False)
    kinds = [item["kind"] for item in classified]
    kind = next((k for k in ("tax_calculation", "calculation") if k in kinds), None) or (kinds[0] if kinds else "explanation")
    tools = list(dict.fromkeys(tool for item in classified for tool in item.get("tools", [])))
    return SubTask(kind=kind, text=text.strip()[:300], needs_evidence=any(item.get("needs_evidence") for item in classified),
                   tools=tools, missing_inputs=[])


def _message_type(query: str, task_query: str, history: Sequence, explicit_reply: bool) -> str:
    from app.orchestration.case_text import request_part
    from app.orchestration.input_requirements import statement_not_question
    from app.orchestration.message_intent import CONTEXT, CORRECTION, classify_message
    if not (query or "").strip():
        return "empty"
    if explicit_reply:
        return "reply"
    if request_part(query) != query:
        return "case_study"
    kind = classify_message(query, list(history))
    if kind == CONTEXT:
        return "context"
    if kind == CORRECTION:
        return "correction"
    if statement_not_question(task_query):
        return "statement"
    return "request"


# A case that points outside itself: "the company above", "the previous
# case", "the same lease". Without one, its pronouns ("the company") are its
# own: "the company breached a loan covenant" in a pasted Brightwater case
# was read as pointing at the Northwind case before it (29 Oct 2026).
_BACK_REFERENCE = re.compile(
    r"\b(?:above|previous(?:ly)?|earlier|prior\s+(?:case|question|message|answer|scenario)"
    r"|same\s+(?:company|entity|case|scenario|figures|facts|lease|contract|client|business)"
    r"|(?:that|this)\s+(?:case|scenario|lease|contract|transaction)\b(?!\s+(?:study|is|has|was)))\b",
    re.I,
)


def starts_new_case(query: str, history: Sequence = ()) -> bool:
    """The message sets out a case of its own: a background with its own
    facts, then the questions about it (case_text.request_part), and no
    reference outside it. Its scope is the message alone; facts from an
    earlier case never enter it. Any other message keeps the conversation's
    scope as before."""
    from app.orchestration.case_text import request_part
    from app.orchestration.conversation_resolver import amounts
    if not history:
        return False
    asked = request_part(query or "")
    if asked == (query or ""):
        return False
    background = (query or "")[: len(query) - len(asked)]
    if not amounts(background) and len(background.split()) < 40:
        return False
    return not _BACK_REFERENCE.search(query or "")


def build_task_contract(query: str, *, task_query: str | None = None, history: Sequence = (),
                        resolution=None, explicit_reply: bool = False,
                        selected_jurisdiction: str | None = None) -> TaskContract:
    """The contract for a request, from the existing checks, before any of
    them acts. history is the screened conversation the pipeline uses."""
    from app.orchestration.case_text import request_part
    from app.orchestration.conversation import with_essential_context
    from app.orchestration.conversation_resolver import amounts, resolve_conversation
    from app.orchestration.input_requirements import missing_tax_inputs, missing_vat_country, missing_vat_inputs
    from app.orchestration.statement_rules import is_statement_request
    from app.orchestration.websearch import sub_questions
    from app.domains.model_gateway.agent import chart_requested
    from app.orchestration.answer_coverage import report_section_names

    query = query or ""
    task_query = task_query or query
    history = list(history or [])
    asked = request_part(query)
    background = query[: len(query) - len(asked)] if asked != query else ""
    new_case = starts_new_case(query, history)
    if new_case:
        resolution = new_case_resolution(history)
    elif resolution is None:
        resolution = resolve_conversation(query, history)

    relevant = [index for index in resolution.relevant_turns if index < len(history)]
    essential = [] if new_case else with_essential_context(task_query, history, [history[i] for i in relevant])
    essential_turns = sorted({index for index, message in enumerate(history) if any(message is chosen for chosen in essential)})
    outside = [index for index in essential_turns if index not in relevant]
    case = CaseScope(
        case_id=(f"turn-{resolution.anchor_turn}" if resolution.follows_up and resolution.anchor_turn is not None
                 else "current"),
        new_case=new_case,
        resolution_kind=resolution.kind, relevant_turns=relevant, anchor_turn=resolution.anchor_turn,
        explicit_reply=explicit_reply, history_turns=len(history), essential_turns_outside_scope=outside,
    )

    facts = [ContractFact(text=figure, source="request") for figure in amounts(asked)]
    facts += [ContractFact(text=figure, source="background") for figure in amounts(background)]
    facts += [ContractFact(text=fact.text, source="history", turn=fact.turn_index) for fact in resolution.facts]
    for index in outside:
        if getattr(history[index], "role", "") == "user":
            facts += [ContractFact(text=figure, source="history", turn=index, in_scope=False)
                      for figure in amounts(getattr(history[index], "content", ""))]

    message_type = _message_type(query, task_query, history, explicit_reply)
    # A context statement, correction or plain statement asks for nothing.
    # The task's questions: for a reply, the request it completes and the
    # reply together, as the calculators read it (task_query).
    asked_task = request_part(task_query)
    questions = (sub_questions(asked_task) if asked_task.strip() and message_type not in ("context", "correction", "statement")
                 else [])
    # S2b: a numbered list written on one line ("Questions to Answer: 1.
    # Calculate … 2. What is …") is split here, in the contract only; the
    # shared splitter web search uses is unchanged.
    # The production decisions below (VAT amount, statements) keep the shared
    # splitter's parts: split finer, "2. How it flows through the income
    # statement." read as a request for statements.
    shared_parts = [_part(text) for text in questions] if questions else []
    questions = [item for text in questions for item in (_inline_items(text) or [text])]
    parts = [_part(text) for text in questions] if questions else []
    deliverables = [RequestedDeliverable(description=f"{kind}: {part.text[:120]}", status="required")
                    for part in parts for kind in _part_deliverables(part.text)]

    # Every existing missing-input check, with the same conditions the
    # pipeline applies (service.ask_kriton, input checks stage).
    from app.orchestration.service import dangling_reference, figureless_calculation_request
    from app.orchestration.supplied_context import missing_in_supplied_context
    # Stage C: the VAT inputs are asked for only when a VAT amount is a
    # deliverable; "What is the GST rate on job work services after the 2025
    # changes?" asks for a rate, not an amount (defect class 1).
    vat_amount = vat_amount_requested(shared_parts, task_query)
    missing = [message for message in (missing_tax_inputs(task_query),
                                       missing_vat_inputs(task_query, history) if vat_amount else None,
                                       missing_vat_country(task_query)) if message]
    if not history and dangling_reference(query):
        missing.append("the figures the request refers to")
    if not history and figureless_calculation_request(query):
        missing.append("the tax, country and figures to calculate")
    gap = missing_in_supplied_context(query, [getattr(m, "content", "") for m in history])
    if gap is not None:
        missing.append(gap.message)

    # Stage C: statements are requested when a part asks for them, read part
    # by part with the existing detector; with no parts, the request part.
    statements = (any(is_statement_request(_PART_LABEL.sub("", part.text, count=1)) for part in shared_parts) if shared_parts
                  else is_statement_request(asked))
    constraints = OutputConstraints(
        statements_requested=statements,
        vat_amount_requested=vat_amount,
        statement_words_in_background_only=bool(background) and not statements and is_statement_request(background),
        chart_requested=bool(chart_requested(asked)),
        report_sections=report_section_names(query),
    )

    kinds = {d.description.split(":", 1)[0] for d in deliverables}
    validations: list[str] = ["input_validity"]
    if kinds & {"amount", "allocation", "journal_entry", "schedule"} or any(p.kind.endswith("calculation") for p in parts):
        validations.append("numerical_correctness")
    if facts:
        validations.append("numerical_provenance")
    if kinds & {"journal_entry", "classification", "allocation", "financial_statements"} or _STANDARD.search(task_query):
        validations.append("accounting_treatment")
    if deliverables:
        validations.append("deliverable_completeness")
    if history:
        validations.append("case_integrity")
    if "chart" in kinds or constraints.chart_requested:
        validations.append("visualization_suitability")
    validations.append("final_disposition")

    # Stage S2 (shadow): the strictness switch, with the pipeline's own inputs
    # (service.ask_kriton, "authority_required"). Never raises.
    try:
        from app.orchestration.pasted_material import review_instruction
        from app.orchestration.verification_service import requires_authoritative_evidence
        authority = requires_authoritative_evidence(review_instruction(query) or query,
                                                    context=f"{resolution.scenario_text()}\n\n{query}")
    except Exception:  # noqa: BLE001
        authority = None

    return TaskContract(
        message_type=message_type,
        request_fingerprint=hashlib.sha256(query.encode()).hexdigest()[:12],
        has_background=bool(background.strip()), case=case, parts=parts, facts=facts,
        missing_inputs=missing, deliverables=deliverables, outputs=requested_outputs(parts),
        output_constraints=constraints, validations=validations,
        retrieval=retrieval_requirements(parts, task_query, asked_task, selected_jurisdiction) if message_type not in ("context", "correction", "statement") else [],
        authority_required=authority,
    )


# ── Stage F: each requested output, by name ──────────────────────────────────
# The amounts a part asks for are the items after its calculation verb,
# split on commas and "and": "Calculate annual straight-line depreciation and
# the carrying amount after three full years" -> two amounts. Other kinds
# (journal entry, schedule, chart, citation) are one output per part.
_AMOUNT_ASK = re.compile(r"\b(?:calculate|compute|quantify|work\s+out|determine|reconstruct)\s+(?P<items>[^.?!:\n]+)", re.I)
_ITEM_SPLIT = re.compile(r"\s*,\s+(?!(?:19|20)\d{2}\b)(?:and\s+)?|\s+and\s+(?=(?:the|an?|its|their|total|net|gross|annual|closing|opening"
                         r"|margin|ratio|percentage|rate|[cis]gst|utgst|prepare|pass|record|post|explain|show|draw|present|draft|state"
                         r"|describe|discuss|comment|advise|identify|list|provide|give)\b)"
                         r"|\s+and\s+(?=\w+\s+(?:amount|value|charge|cost|expense|liability|balance|profit|loss|tax|vat|gst|margin)\b)",
                         re.I)
_LEADING = re.compile(r"^(?:the|an?|its|their|both)\s+", re.I)
# An item that is another instruction ("… and prepare the schedule"), not an amount.
_INSTRUCTION = re.compile(r"^(?:prepare|pass|record|post|explain|show|draw|present|draft|state|describe|discuss|"
                          r"comment|advise|identify|list|provide|give|set\s+out)\b", re.I)
_CHECKED_KINDS = ("journal_entry", "schedule", "chart", "citation")


def requested_outputs(parts: Sequence[SubTask]) -> list[RequestedOutput]:
    outputs: list[RequestedOutput] = []
    for index, part in enumerate(parts):
        text = _PART_LABEL.sub("", part.text or "", count=1).strip()
        kinds = _part_deliverables(text)
        if "amount" in kinds and (match := _AMOUNT_ASK.search(text)):
            for item in _ITEM_SPLIT.split(match.group("items").strip()):
                name = _LEADING.sub("", item.strip(" ;:")).strip()
                if name and len(name.split()) <= 12 and not _INSTRUCTION.match(name):
                    outputs.append(RequestedOutput(part=index, kind="amount", name=name))
        outputs += [RequestedOutput(part=index, kind=kind, name=kind.replace("_", " ")) for kind in kinds if kind in _CHECKED_KINDS]
    return outputs


_CURRENCY_AMOUNT = re.compile(r"[£$€₹¥]\s?\d|\b\d[\d,]*(?:\.\d+)?\s*(?:lakhs?|crores?|million|bn)\b", re.I)


def vat_amount_requested(parts: Sequence[SubTask], task_query: str) -> bool:
    """A part about VAT/GST asks for an amount: a calculation deliverable, or
    the existing VAT amount wording ("VAT payable", "how much VAT") with an
    amount given. A rate or rule asked about is not an amount."""
    from app.orchestration.input_requirements import _VAT, _VAT_AMOUNT_QUESTION
    has_amount = bool(_CURRENCY_AMOUNT.search(task_query or ""))
    for part in parts:
        if not _VAT.search(part.text):
            continue
        if "amount" in _part_deliverables(part.text) or (_VAT_AMOUNT_QUESTION.search(part.text) and has_amount):
            return True
    return False


def new_case_resolution(history: Sequence = ()):
    """The conversation resolution for a message that starts a new case:
    standalone, with no earlier turn relevant to it."""
    from app.orchestration.conversation_resolver import ConversationResolution
    return ConversationResolution(kind="standalone", reasons=("new_case",), _history=tuple(history or ()))


def _shadow_file_enabled() -> bool:
    return os.getenv("KRITON_TASK_CONTRACT_SHADOW", "").strip().lower() in {"1", "true", "yes", "on"}


def record(contract: TaskContract | None, *, query_id: str, stage: str) -> None:
    """Log the contract. Never raises: shadow mode must not affect an answer."""
    if contract is None:
        return
    try:
        logger.info("Task contract query=%s stage=%s %s", query_id, stage, json.dumps(contract.summary(), default=str))
        if _shadow_file_enabled():
            _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_FILE.open("a") as handle:
                handle.write(json.dumps({"query_id": query_id, "stage": stage, "contract": contract.model_dump(mode="json")},
                                        default=str) + "\n")
    except Exception:  # noqa: BLE001
        logger.warning("task_contract_record_failed", extra={"query_id": query_id})


def shadow_build(query: str, **kwargs) -> TaskContract | None:
    """build_task_contract that never raises (None on any failure)."""
    try:
        return build_task_contract(query, **kwargs)
    except Exception:  # noqa: BLE001
        logger.warning("task_contract_build_failed", exc_info=True)
        return None


# ── Stage C-1 (shadow): retrieval requirements ───────────────────────────────
# What each part needs retrieved, decided once, from the part's own wording
# and the existing publisher map (source_guarantee._OFFICIAL) and jurisdiction
# detector (source_taxonomy). Recorded only: retrieval does not read it yet.
# An official current figure or rule (a rate, threshold, deadline or legal
# rule) is distinguished from a calculation on given figures and from a
# conceptual explanation, which need no official current figure.

FactType = Literal["rate", "threshold", "deadline", "rule", "standard", "calculation", "explanation"]


class RetrievalRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    part: str
    needs_official: bool
    fact_type: FactType
    jurisdictions: list[str] = Field(default_factory=list)
    publisher: Optional[str] = None
    # An existing official connector that would serve the part (none added).
    connector: Optional[str] = None
    # The existing fixed official pages (official_evidence.official_pages)
    # that cover the part, as (title, url); none added.
    official_pages: list[tuple[str, str]] = Field(default_factory=list)
    # The domains retrieval's search is restricted to for the part's
    # jurisdictions and topic (source_taxonomy.allowed_domains).
    official_domains: list[str] = Field(default_factory=list)
    reason: str = ""
    # Stage S2 (shadow): the part's topics (source_taxonomy.detect_topics) and
    # the period it asks about. Recorded only; nothing routes on them yet.
    topics: list[str] = Field(default_factory=list)
    period: "Period" = Field(default_factory=lambda: Period())
    # Option 3 (shadow, KRITON_COUNTRY_RESOLUTION): the deterministic country
    # resolution with its evidence. Recorded only; nothing routes on it.
    country_resolution: Optional[dict] = None


class Period(BaseModel):
    """The period a part asks about, as written: "current" (now, latest,
    today, or an official figure with no period named), a "year" ("in 2022",
    "FY 2025-26"), "before" / "after" a date ("on or after 1 January 2023",
    "after the 2025 changes"), a "range", "historical" ("used to") or
    "unspecified" (nothing asked about time)."""
    model_config = ConfigDict(frozen=True)

    kind: Literal["current", "implied_current", "year", "before", "after", "range", "historical", "unspecified"] = "unspecified"
    start: Optional[str] = None
    end: Optional[str] = None
    text: str = ""


_FACT_RATE = re.compile(r"\b(?:(?:tax|vat|gst|interest|bank|base|duty|withholding|tds|corporation\s+tax|standard|"
                        r"reduced|effective|main|contribution)\s+rates?|rates?\s+of\s+(?:\w+\s+){0,3}(?:tax|vat|gst|duty|tds|"
                        r"contributions?|insurance)|flat\s+rate\s+percentage|slabs?|tax\s+bands?)\b", re.I)
_FACT_THRESHOLD = re.compile(r"\b(?:thresholds?|exemption\s+limit|(?<!time\s)limit\s+for|turnover\s+limit|standard\s+deduction|"
                             r"personal\s+allowance|tax[- ]free\s+allowance|employment\s+allowance|annual\s+allowance|wage\s+base|"
                             r"maximum\s+deduction|nil[- ]rate\s+band|turnover\s+before|"
                             # S2c: named tax allowances, limits and exemptions ("marriage
                             # allowance", "registration limit", "estate tax exemption").
                             r"(?:marriage|dividend|trading|property|savings|personal\s+savings|blind\s+person'?s)\s+allowance|"
                             r"registration\s+limits?|(?:vat|gst|turnover|exemption)\s+limits?|exempt(?:ion)?\s+amount|"
                             r"(?:estate|gift|inheritance)\s+tax\s+(?:exemption|exclusion|allowance)s?|annual\s+(?:exclusion|exempt\s+amount)|"
                             r"how\s+much\s+(?:turnover|income|"
                             r"sales)\s+(?:before|can))\b", re.I)
_FACT_DEADLINE = re.compile(r"\b(?:deadlines?|due\s+dates?|last\s+date|filing\s+date|time\s+limits?|by\s+when"
                            r"|when\s+(?:is|are|must|do|should|does)\b[^?.\n]{0,60}\b(?:due|file|filed|pay|paid|submit\w*|register))\b",
                            re.I)
_FACT_RULE = re.compile(r"\b(?:which\s+section|cite\s+the\s+provision|under\s+section|section\s+\d+\w*|is\s+(?:the\s+)?\w+(?:\s+\w+){0,6}\s+"
                        r"(?:allowed|eligible|deductible|exempt|taxable|required|permitted)|can\s+(?:the\s+)?\w+(?:\s+\w+){0,6}\s+be\s+"
                        r"(?:deducted|claimed|carried\s+forward)|consequences?\s+of|penalt(?:y|ies)|late\s+fees?|do\s+i\s+(?:need|have)\s+to\s+register"
                        r"|must\s+(?:i|we|it|the\s+company)\s+register)\b", re.I)
_LEGAL_SUBJECT = re.compile(r"\b(?:tax|vat|gst|gstr-?\w*|tds|itc|input\s+tax|hmrc|irs|cbic|act|section|law|regulations?|register|"
                            r"deduct\w*|penalt\w*|filing)\b", re.I)
# Asks why something exists or for a general account, not for the figure:
# "Why do tax authorities set VAT registration thresholds?"
_CONCEPTUAL = re.compile(r"^\s*(?:how\s+(?:does|do|did|can|could|would|might)\s+[^?]{0,80}\b(?:affect|influence|impact|shape)\b|"
                         r"explain\s+(?:the\s+)?(?:difference|distinction|relationship)\s+between|why\b|explain\s+(?:why|in\s+general|generally|the\s+(?:purpose|concept|idea))|in\s+general\b)", re.I)
# A direct question about how a named tax applies ("Is hot takeaway food
# zero-rated for VAT in the UK?", "How far back can I reclaim VAT ...?"), at
# the start of a sentence; a definition ("Is VAT a tax on ...") or a request
# to explain is not one.
_RULE_QUESTION = re.compile(r"(?:^|[.?!]\s+)(?:(?:can|could|is|are|do|does|must|should|will|am)\s+"
                            r"(?!you\b)(?!\w+\s+an?\s)|when\s+(?:must|should|can|do|does)\b"
                            r"|how\s+(?:far\s+back|long|many|soon)\b|which\s+(?:form|scheme|provision)\b"
                            r"|who\s+(?:can|must|is\s+eligible)\b)", re.I)
_TAX_SUBJECT = re.compile(r"\b(?:vat|gst|tds|hmrc|irs|cbic|income\s+tax|corporation\s+tax|corporate\s+(?:income\s+)?tax|"
                          r"national\s+insurance|sales\s+tax|excise|customs\s+duty|stamp\s+duty|"
                          r"making\s+tax\s+digital|zero[- ]rated|exempt\s+from|flat\s+rate\s+scheme)\b", re.I)
# S2b (from tuning-set failures, 30 Oct 2026). A rate asked for by name from an
# official body or for a named country ("What is the superannuation guarantee
# rate in Australia?", "What is the current RBA cash rate?", "the current
# federal funds target range"): not a ratio or a rate of return.
_NAMED_RATE = re.compile(r"\b(?:what|which)(?:'s|\s+(?:is|are|was|were))\s+the\s+(?:[\w'-]+\s+){0,5}(?:rates?|target\s+range)\b"
                         r"(?![\w\s]{0,12}\b(?:of\s+return|ratio))", re.I)
# A threshold asked as "above / below / up to what turnover, income, value":
# "Above what taxable income does UAE corporate tax apply at 9%?"
_WHAT_LIMIT = re.compile(r"\b(?:above|below|over|under|up\s+to|beyond)\s+what\s+(?:[\w-]+\s+){0,2}"
                         r"(?:turnover|income|value|amount|profits?|sales|revenue)\b", re.I)
# S2c: a rate asked as a percentage or as "how much <tax> applies" ("What
# percentage VAT do UK restaurants charge on hot food?", "How much GST
# applies to two-wheelers in India now?"), when the user gives no figures.
_TAX_PERCENTAGE = re.compile(r"\bpercentage\s+(?:of\s+)?(?:vat|gst|tax|duty)\b|\b(?:vat|gst|tax|duty)\s+percentage\b"
                             r"|\bhow\s+much\s+(?:vat|gst|tax|duty|tds)\s+(?:is|applies|apply|do|does|will|would|are)\b", re.I)
# An explanation request: with no country, not a request for an official figure
# ("Explain the effective interest rate method for amortised cost.").
_EXPLAIN_START = re.compile(r"^\s*(?:explain|describe|outline|discuss)\b", re.I)
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
    # A country the part names, or its authority's, decides; the country a
    # bare tax word implies ("GST" read as India) only when there is none:
    # "What penalty does IRAS impose for late GST filing?" was placed in India
    # and Singapore, and searched on both countries' sites (3 Nov 2026).
    authorities = [key for pattern, key in _AUTHORITY_PLACE if pattern.search(part)]
    explicit = list(dict.fromkeys(detect_jurisdictions(part, infer_from_tax_terms=False) + authorities))
    found = explicit or detect_jurisdictions(part) or detect_jurisdictions(context)
    found = list(dict.fromkeys(found + authorities))
    other = {key for match in _COUNTERPARTY.finditer(part) for name in match.groups() if name
             for key in detect_jurisdictions(name, infer_from_tax_terms=False)}
    kept = [key for key in found if key not in other]
    return kept or found


_RATE_GIVEN = re.compile(r"\d+(?:\.\d+)?\s*%")
# A rate the user states: "at an exchange rate of £1 = $1.25", "at 1.17".
_FX_GIVEN = re.compile(r"\b(?:rate\s+of|at)\s+[£$€₹]?\s?\d[\d.,]*\s*(?:=|[a-z]{3}\b|per\b)|=\s*[£$€₹]\s?\d", re.I)
_FX = re.compile(r"\b(?:exchange\s+rate|fx\s+rate|convert\s+[£$€₹]|into\s+(?:euros|dollars|pounds|rupees))\b", re.I)
# "at today's rate" / "at the latest rate" with a conversion between currencies.
_FX_CURRENT = re.compile(r"\b(?:today'?s|latest|current|live|spot|reference)\s+rate\b(?!\s+of\s)", re.I)
_CONVERSION = re.compile(r"\bconvert\b|\b(?:in|into|to)\s+(?:euros?|pounds|dollars|rupees|usd|eur|gbp|inr|sgd|singapore\s+dollars)\b"
                         r"|how\s+many\s+(?:pounds|euros|dollars|rupees)", re.I)


def _fx(text: str) -> bool:
    return bool(_FX.search(text) or (_FX_CURRENT.search(text) and _CONVERSION.search(text)))
_BANK_RATE = re.compile(r"\b(?:bank\s+rate|base\s+rate|policy\s+rate|repo\s+rate)\b", re.I)
# The HMRC page on when to register (or deregister), not any "VAT-registered".
_UK_VAT_REGISTRATION = re.compile(r"\b(?:thresholds?|deregist\w*|register\s+for|registration\s+(?:thresholds?|rules?|requirements?|limit)"
                                  r"|(?:need|have|required)\s+to\s+register|must\s+(?:\w+\s+)?register|when\s+to\s+register)\b", re.I)


def _publisher(text: str, jurisdictions: Sequence[str] = ()) -> Optional[str]:
    """The publisher map's label for the part; a label for another country
    than the part's is no publisher for it (reported as a gap)."""
    from app.orchestration.source_guarantee import _OFFICIAL, label_country
    for pattern, label in _OFFICIAL:
        if not pattern.search(text or ""):
            continue
        country = label_country(label)
        if country and jurisdictions and country not in jurisdictions:
            continue
        return label
    return None


def _official_pages(part: str, jurisdictions: Sequence[str]) -> list[tuple[str, str]]:
    """The fixed official pages retrieval already reads for this part; the
    country named elsewhere in the request is added to the part's wording."""
    from app.orchestration.official_evidence import official_pages
    return official_pages(" ".join([part, *(key.replace("_", " ").lower() for key in jurisdictions)]))


def _official_domains(part: str, jurisdictions: Sequence[str]) -> list[str]:
    from app.orchestration.source_taxonomy import allowed_domains, detect_jurisdictions, detect_topics
    topics = detect_topics(part)
    domains = {domain for key in jurisdictions for domain in allowed_domains(key, topics, part)}
    # The wording can add the other party's authorities ("billing a US client"
    # added irs.gov to an Indian GST question): drop domains that only the
    # other party's country has (S2b).
    other = {key for match in _COUNTERPARTY.finditer(part) for name in match.groups() if name
             for key in detect_jurisdictions(name, infer_from_tax_terms=False)} - set(jurisdictions)
    own = {domain for key in jurisdictions for domain in allowed_domains(key, topics, "")}
    theirs = {domain for key in other for domain in allowed_domains(key, set(), "")}
    return sorted(domains - (theirs - own))


def _connector(text: str, jurisdictions: list[str]) -> Optional[str]:
    """An official connector that already exists for this fact; none is added."""
    if _fx(text):
        return "exchange_rate"
    if "UK" in jurisdictions and _BANK_RATE.search(text):
        return "bank_of_england"
    if "UK" in jurisdictions and re.search(r"\bvat\b", text, re.I) and _UK_VAT_REGISTRATION.search(text):
        return "hmrc_vat_registration"
    return None


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


def _requirement(text: str, context: str, selected_jurisdiction: str | None = None) -> RetrievalRequirement:
    part = _PART_LABEL.sub("", text or "", count=1).strip()
    jurisdictions = _places(part, context)
    kinds = _part_deliverables(part)
    figures_given = bool(_CURRENCY_AMOUNT.search(part))

    from app.orchestration.source_taxonomy import detect_topics
    from app.orchestration.country_resolution import resolution_enabled, resolve
    topics = sorted(detect_topics(part) or detect_topics(context))
    resolution = resolve(part, context, selected=selected_jurisdiction).__dict__ if resolution_enabled() else None

    def made(needs: bool, fact: str, reason: str) -> RetrievalRequirement:
        return RetrievalRequirement(part=part[:200], needs_official=needs, fact_type=fact, jurisdictions=jurisdictions,
                                    country_resolution=resolution,
                                    publisher=(_publisher(part, jurisdictions) or _publisher(context, jurisdictions)) if needs else None,
                                    connector=_connector(part, jurisdictions) if needs else None,
                                    official_pages=_official_pages(part, jurisdictions) if needs else [],
                                    official_domains=_official_domains(part, jurisdictions) if needs else [], reason=reason,
                                    topics=topics,
                                    # A scenario's dates are not a period asked about (S2b).
                                    period=period_of(part, official=True) if needs else Period())

    if _CONCEPTUAL.search(part):
        return made(False, "explanation", "asks why, or for a general account, not for the current figure or rule")
    # A conversion needs the current rate unless the user gave one, even within a calculation.
    if _fx(part) and _FX_GIVEN.search(part):
        return made(False, "calculation", "a conversion at the exchange rate the user gave")
    if _fx(part):
        # Served by the exchange-rate connector, not a publisher.
        return RetrievalRequirement(part=part[:200], needs_official=True, fact_type="rate", jurisdictions=jurisdictions,
                                    connector="exchange_rate", reason="a current exchange rate", country_resolution=resolution,
                                    topics=topics, period=period_of(part, official=True))
    # Arithmetic on the user's own figures, with the rate given: nothing to look up.
    if kinds and set(kinds) & {"amount", "allocation", "schedule", "journal_entry"} and figures_given \
            and (_RATE_GIVEN.search(context) or not _FACT_RATE.search(part)):
        return made(False, "calculation", "a calculation on figures (and any rate) the user gave")
    if _EXPLAIN_START.search(part) and not jurisdictions:
        return (made(False, "standard", "explains a standard's requirements (source-grounded, not an official current figure)")
                if _STANDARD.search(part) else made(False, "explanation", "an explanation with no country: no official figure"))
    if _FACT_THRESHOLD.search(part) or _WHAT_LIMIT.search(part):
        return made(True, "threshold", "an official threshold or limit")
    if _TAX_PERCENTAGE.search(part) and not figures_given:
        return made(True, "rate", "a tax rate asked as a percentage or amount, with no figures given")
    if _FACT_DEADLINE.search(part):
        return made(True, "deadline", "an official deadline")
    if _FACT_RATE.search(part) and not _RATE_GIVEN.search(part):
        return made(True, "rate", "an official current rate")
    if _NAMED_RATE.search(part) and jurisdictions and not _RATE_GIVEN.search(part):
        return made(True, "rate", "an official rate asked for by name, for a named country or body")
    if _FACT_RULE.search(part) and _LEGAL_SUBJECT.search(part):
        return made(True, "rule", "a legal or tax rule, with its provision")
    if _RULE_QUESTION.search(part) and _TAX_SUBJECT.search(part) and jurisdictions:
        return made(True, "rule", "how a named tax applies in a named jurisdiction")
    if _STANDARD.search(part):
        return made(False, "standard", "explains a standard's requirements (source-grounded, not an official current figure)")
    if set(kinds) & {"amount", "allocation", "schedule", "journal_entry"}:
        return made(False, "calculation", "a calculation or entry on the user's facts")
    return made(False, "explanation", "a conceptual explanation")


def retrieval_requirements(parts: Sequence[SubTask], task_query: str, asked: str,
                           selected_jurisdiction: str | None = None) -> list["RetrievalRequirement"]:
    """One requirement per part; for a request without separate parts, one
    for the request itself. Shadow only: a failure here records nothing and
    never reaches the request."""
    texts = [part.text for part in parts] or ([asked] if (asked or "").strip() else [])
    try:
        return [_requirement(text, task_query, selected_jurisdiction) for text in texts]
    except Exception:  # noqa: BLE001
        logger.exception("Retrieval requirements not recorded")
        return []



# ── Stage C-2a (shadow): what retrieval actually supplied ────────────────────
# For each part the contract says needs an official figure or rule: whether an
# official source reached the final answer's citations, and which kind. The
# citations are the answer's as a whole (not bound to a part). Recorded only.

_DOMAIN = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/[a-z0-9/_-]+)?", re.I)
_CONNECTOR_SOURCES = {"hmrc_vat_registration": ("gov.uk/register-for-vat",),
                      "bank_of_england": ("bankofengland.co.uk", "bank of england"),
                      "exchange_rate": ("frankfurter", "ecb.europa.eu", "european central bank")}


def _host(url: str) -> str:
    return re.sub(r"^https?://(?:www\.)?", "", (url or "").lower())


def served_by(requirement: RetrievalRequirement, citations: Sequence) -> list[str]:
    """How the answer's citations cover an official part: the part's fixed
    official page, its connector, its publisher's domain, a domain retrieval
    trusts for the part's jurisdiction, or another source marked official.
    Empty when none of them did."""
    kinds = []
    for citation in citations or ():
        place = _host(getattr(citation, "url", "") or "")
        origin = f"{place} {(getattr(citation, 'provider', '') or '').lower()} {(getattr(citation, 'title', '') or '').lower()}"
        if place and any(place.startswith(_host(url)) for _, url in requirement.official_pages):
            kinds.append("official_page")
        elif requirement.connector and any(marker in origin for marker in _CONNECTOR_SOURCES.get(requirement.connector, ())):
            kinds.append("connector")
        elif place and requirement.publisher and any(
                (site := place.split("/")[0]) == (host := domain.lower().split("/")[0]) or site.endswith("." + host)
                for domain in _DOMAIN.findall(requirement.publisher)):
            kinds.append("publisher")
        elif place and any((site := place.split("/")[0]) == domain or site.endswith("." + domain)
                           for domain in requirement.official_domains):
            # A domain retrieval trusts for the jurisdiction: an authority, or
            # a professional body on the allowlist (att.org.uk, oecd.org).
            kinds.append("allowlisted")
        elif getattr(citation, "authority", None) == "official":
            kinds.append("other_official")
    return list(dict.fromkeys(kinds))


def record_retrieved(contract: TaskContract | None, response, *, query_id: str, trace: dict | None = None) -> None:
    """Log, for each official part, what the final answer cites, and the
    retrieval path the request took (trace: agent or standard, and what was
    pre-fetched; empty when the response came before retrieval, such as a
    calculator answer or a clarification). Never raises."""
    try:
        if contract is None or not any(r.needs_official for r in contract.retrieval):
            return
        answer = getattr(response, "answer", None)
        citations = list(getattr(answer, "citations", None) or [])
        observed = [{"part": r.part[:120], "fact": r.fact_type, "jurisdictions": r.jurisdictions,
                     "expected": {"publisher": r.publisher, "connector": r.connector, "domains": r.official_domains,
                                  "official_pages": [title for title, _ in r.official_pages]},
                     "served_by": served_by(r, citations)}
                    for r in contract.retrieval if r.needs_official]
        summary = {"outcome": getattr(response, "outcome", None), "route": getattr(response, "route", None),
                   "retrieval": dict(trace) if trace else {"path": "before_retrieval"},
                   "citations": len(citations),
                   "hosts": list(dict.fromkeys(_host(getattr(c, "url", "") or "").split("/")[0] for c in citations
                                               if getattr(c, "url", None)))[:10],
                   "official_parts": observed}
        logger.info("Task contract query=%s stage=retrieved %s", query_id, json.dumps(summary, default=str))
        if _shadow_file_enabled():
            _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_FILE.open("a") as handle:
                handle.write(json.dumps({"query_id": query_id, "stage": "retrieved", "retrieved": summary}, default=str) + "\n")
    except Exception:  # noqa: BLE001
        logger.warning("task_contract_retrieved_failed", extra={"query_id": query_id})


RetrievalRequirement.model_rebuild()
TaskContract.model_rebuild()
